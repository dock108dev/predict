import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from uuid import UUID

import httpx
import pytest

from app.collection import novig_experiment_depth as novig
from app.collection.experiment_depth import _reconcile
from app.comparison.sgo_native_binding import capture_catalog
from app.storage.experiment_depth import offer_key, receipt_for


CUTOFF = datetime(2026, 11, 27, 22, 50, tzinfo=timezone.utc)


def uid(number):
    return str(UUID(int=number))


def binding(number=2, line='-10.5'):
    return dict(available=True, phase='scheduled', phase_verified=True,
                starts_at=(CUTOFF + timedelta(minutes=10)).isoformat(), family='spread',
                selected_side='away', signed_line=line, revision='binding-revision',
                event_id=uid(1), market_id=uid(number), outcome_id=uid(number*10),
                opposite_outcome_id=uid(number*10+1))


def market(bind, bid=None):
    line = bind['signed_line'].removeprefix('-')
    return dict(eventId=bind['event_id'], marketId=bind['market_id'], marketType='SPREAD',
                status='OPEN', startsTs=int(datetime.fromisoformat(bind['starts_at']).timestamp()*1000),
                strike=line, fee={'coefficient': '0.06', 'makerCredit': '0.25', 'charged': 'WHEN_LIVE'},
                outcomes=[
                    dict(outcomeId=bind['outcome_id'], name=f'Gonzaga -{line}', status='TBD', subjectId=uid(50)),
                    dict(outcomeId=bind['opposite_outcome_id'], name=f'Creighton +{line}', status='TBD',
                         subjectId=uid(51), bid=bid),
                ])


def receipt(at=CUTOFF, *, limit=10, age=None, date=None):
    receipt = {
        'requested_at': (at-timedelta(milliseconds=250)).isoformat(),
        'received_at': at.isoformat(),
        'date': format_datetime(date or at, usegmt=True),
        'cache-control': f'public, max-age={limit}, stale-while-revalidate={limit}',
    }
    if age is not None:
        receipt['age'] = str(age)
    return receipt


def catalog(bind, row, evidence=None):
    evidence = receipt() if evidence is None else evidence
    return novig.catalog_depth(bind, novig.PublicEventDepth(
        {bind['market_id']: dict(row, receipt=evidence)}, (evidence,)), CUTOFF)


def test_exact_spreads_do_not_alias_and_opposite_bid_uses_penny_payout():
    first, second = binding(), binding(3, '-16.5')
    best = dict(price='0.75', qty=2000)
    result = catalog(first, market(first, best))
    assert result['levels'] == [{'price': '1/4', 'quantity': '2000'}]
    assert result['payout_usd'] == '1/100'
    assert result['complete'] is False
    assert result['fee']['coefficient'] == '0'
    assert result['contract']['signed_line'] == '-10.5'
    second_market = market(second, dict(price='0.90', qty=7000))
    assert catalog(second, second_market)['levels'] == [{'price': '1/10', 'quantity': '7000'}]
    assert catalog(first, second_market)['reason'] == 'identity_or_quote_conflict'
    assert catalog(dict(first, signed_line='-16.5'), market(first, best))['reason'] == 'identity_or_quote_conflict'
    assert catalog(dict(first, starts_at=(CUTOFF+timedelta(minutes=11)).isoformat()),
                   market(first, best))['reason'] == 'identity_or_quote_conflict'
    anchored = dict(first, subject_role_anchors=[dict(away_subject=uid(50), home_subject=uid(51))])
    assert catalog(anchored, market(first, best))['contract']['subjects'] == [uid(50),uid(51)]
    changed = market(first, best)
    changed['outcomes'][0]['subjectId'] = uid(54)
    assert catalog(anchored, changed)['reason'] == 'identity_or_quote_conflict'


def test_exact_total_checks_both_over_and_under_labels():
    bind = dict(binding(), family='total', selected_side='under', signed_line='157.5')
    row = dict(market(bind), marketType='TOTAL', strike='157.5', outcomes=[
        dict(outcomeId=bind['outcome_id'], name='Under 157.5', status='TBD', bid=dict(price='0.52', qty=9000)),
        dict(outcomeId=bind['opposite_outcome_id'], name='Over 157.5', status='TBD', bid=dict(price='0.46', qty=2000)),
    ])
    result = catalog(bind, row)
    assert result['levels'] == [dict(price='27/50', quantity='2000')]
    row['outcomes'][0]['name'] = 'Under 161.5'
    assert catalog(bind, row)['reason'] == 'identity_or_quote_conflict'


def test_current_novig_lifecycle_uses_exact_fresh_receipts_without_altering_checkpoint():
    def serve(request):
        headers = {'Date': format_datetime(CUTOFF), 'Cache-Control': 'public, max-age=10'}
        if '/events/' in request.url.path:
            return httpx.Response(200, headers=headers,
                                  json=dict(eventId=uid(1), status='DELAYED'))
        if request.url.path.endswith(uid(2)):
            return httpx.Response(200, headers=headers,
                                  json=dict(eventId=uid(1), marketId=uid(2), status='CLOSED'))
        headers['Cache-Control'] = 'no-store'
        return httpx.Response(404, headers=headers, json={'code': 'MARKET_NOT_FOUND'})

    async def run():
        async with novig.NovigExperimentDepth(transport=httpx.MockTransport(serve), clock=lambda: CUTOFF) as client:
            cutoff = CUTOFF + timedelta(seconds=8)
            assert (await client.read_event_metadata(uid(1), cutoff))[2] == 'identity_conflict'
            event, witness, reason = await client.read_event_metadata(uid(1), cutoff, lifecycle=True)
            assert reason is None and event['status'] == 'DELAYED' and witness['status'] == 200
            assert (await client.read_market_metadata(uid(1), uid(2), cutoff))[2] == 'native_market_halted'
            assert (await client.read_market_metadata(uid(1), uid(3), cutoff))[2] == 'native_market_withdrawn'

    asyncio.run(run())


def test_prepared_native_alternates_replay_without_an_earlier_sgo_quote():
    first, second, anchor = binding(), binding(3, '-16.5'), binding(4, '-5.5')
    event = dict(id='sgo-event', competition='NCAAB', scheduled_start=first['starts_at'],
                 away='sportsgameodds:NCAAB:sgo-event:away', home='sportsgameodds:NCAAB:sgo-event:home',
                 shared_provider_ids={'novig_event': first['event_id']})
    native_event = dict(eventId=first['event_id'], league='NCAAB', status='OPEN_PREGAME',
                        startsTs=market(anchor)['startsTs'])
    prior = dict(observed_at=(CUTOFF-timedelta(minutes=2)).isoformat(), sha256='1'*64)
    witness = capture_catalog(event['id'], first['event_id'], native_event,
        dict(prior, path=f'/v3/public/catalog/events/{first["event_id"]}'),
        [(dict(items=[market(anchor)]), dict(prior, path=novig.MARKETS_PATH))], {
            anchor['outcome_id']: [dict(odd_id='points-away-game-sp-away', side='away',
                opposing_odd_id='points-home-game-sp-home', market='spread', period='game', line='-5.5')],
            anchor['opposite_outcome_id']: [dict(odd_id='points-home-game-sp-home', side='home',
                opposing_odd_id='points-away-game-sp-away', market='spread', period='game', line='5.5')],
        }, sgo_frame='2'*64)
    witness['revision'] = 'anchored'
    observed = dict(receipt(), path=novig.MARKETS_PATH, sha256='3'*64)

    def snapshot(*bindings):
        return novig.PublicEventDepth({
            bind['market_id']: dict(market(bind, dict(price='0.75', qty=2000)), receipt=observed)
            for bind in bindings
        }, (observed,))

    def final_record(bind, link):
        return dict(event=event, market_identity=dict(family='spread', period='full_game'),
            selection=dict(predicate='cover', participant=event['away'], signed_line=bind['signed_line']),
            quote=dict(venue='novig', state='available', source=dict(provider='sportsgameodds',
                native_event_id=event['id'], native_outcome_id='points-away-game-sp-away')),
            comparison_source_metadata=dict(bookmaker_market_link=link))

    catalog_snapshot = snapshot(first, second)
    plan = _reconcile({}, witness, [], catalog_snapshot, CUTOFF, event=event)
    assert len(plan) == 4  # Two sides for each of the two exact lines.
    rows = {key: novig.catalog_depth(anchored, catalog_snapshot, CUTOFF)
            for key, (anchored, _) in plan.items()}
    event_link = dict(host='novig.com', path=f'/event-markets/{first["event_id"]}/sportsgameodds')
    first_late = final_record(first, event_link)
    first_receipt = receipt_for({'record': first_late}, rows)
    assert (first_receipt['market_id'], first_receipt['outcome_id']) == (first['market_id'], first['outcome_id'])
    second_late = final_record(second, dict(host='novig.com',
        path=f'/events/{second["outcome_id"]}/sportsgameodds'))
    assert receipt_for({'record': second_late}, rows)['market_id'] == second['market_id']
    wrong_side = final_record(second, dict(host='novig.com',
        path=f'/events/{second["opposite_outcome_id"]}/sportsgameodds'))
    assert receipt_for({'record': wrong_side}, rows)['reason'] == 'unmatched_native_outcome_link'

    ambiguity = _reconcile({}, witness, [], snapshot(first, second, binding(6)), CUTOFF, event=event)
    assert ambiguity[offer_key(first_late)][0]['reason'] == 'unmatched_ambiguous_native_contract'
    assert ambiguity[offer_key(second_late)][0]['market_id'] == second['market_id']


def test_valid_empty_side_differs_from_stale_later_or_suspended():
    bind = binding()
    row = market(bind)
    assert catalog(bind, row)['complete'] is True
    assert catalog(bind, row)['levels'] == []
    assert catalog(bind, row, receipt(age=11))['reason'] == 'stale'
    assert catalog(bind, row, receipt(date=CUTOFF-timedelta(seconds=11)))['reason'] == 'stale'
    assert catalog(bind, row, receipt(at=CUTOFF+timedelta(milliseconds=1)))['reason'] == 'after_cutoff'
    assert catalog(bind, dict(row, status='SUSPENDED'))['reason'] == 'identity_or_quote_conflict'
    assert catalog(bind, market(bind, dict(price='0.751', qty=2000)))['reason'] == 'identity_or_quote_conflict'


def test_detailed_book_groups_all_orders_in_price_priority_and_tracks_cap():
    bind = binding()
    top = catalog(bind, market(bind, dict(price='0.75', qty=2033)))
    observed = dict(receipt(limit=5), sequence=123)
    orders = [dict(orderId=uid(101), price='0.75', qty=33),
              dict(orderId=uid(102), price='0.75', qty=2000)]
    for index in range(1, 20):
        orders.append(dict(orderId=uid(102+index), price=f'0.{750-index*5:03d}', qty=200))
    book = dict(marketId=bind['market_id'], seq=123, orders={bind['opposite_outcome_id']: orders})
    result = novig.book_depth(bind, novig.PublicBookDepth(book, observed), CUTOFF, catalog=top)
    assert result['reason'] is None
    assert result['complete'] is False
    assert result['levels'][0] == dict(price='1/4', quantity='2033', orders=['33','2000'],
                                        order_ids=[uid(101),uid(102)])
    assert result['receipts'][1]['sequence'] == 123
    assert result['sequence'] == 123
    short = dict(book, orders={bind['opposite_outcome_id']: orders[:2]})
    complete = novig.book_depth(bind, novig.PublicBookDepth(short, observed), CUTOFF, catalog=top)
    assert complete['complete'] is True
    stale = novig.book_depth(bind, novig.PublicBookDepth(book, receipt(limit=5, age=6)), CUTOFF, catalog=top)
    assert stale['reason'] == 'stale'
    assert stale['levels'] == top['levels']
    assert stale['catalog_lower_bound'] is True

    # The same second-tier failure cannot requalify an initially good quote
    # once its first-tier evidence is too old at the decision cutoff.
    old = novig.book_depth(bind, novig.PublicBookDepth(None, None, reason='throttled'),
                           CUTOFF + timedelta(seconds=11), catalog=top)
    assert old['reason'] == 'stale' and 'catalog_lower_bound' not in old


def test_older_book_cannot_replace_a_newer_contradicting_catalog():
    bind = binding()
    top = catalog(bind, market(bind, dict(price='0.75', qty=2033)))
    observed = dict(receipt(limit=5, age=3), sequence=123)
    book = dict(marketId=bind['market_id'], seq=123, orders={bind['opposite_outcome_id']: [
        dict(orderId=uid(101), price='0.75', qty=5000),
    ]})
    result = novig.book_depth(bind, novig.PublicBookDepth(book, observed), CUTOFF, catalog=top)
    assert result['reason'] == 'older_book_top_conflict'
    assert result['levels'] == top['levels']
    assert result['catalog_lower_bound'] is True


def test_fee_cutover_fails_closed_if_date_or_market_terms_are_unverified():
    legacy = {'charged': 'WHEN_LIVE', 'coefficient': '0.06'}
    pregame = {'charged': 'ALWAYS', 'coefficient': '0.03'}
    early = novig.CUTOVER_DATE_UTC - timedelta(microseconds=1)
    assert novig._fee(legacy, early)['coefficient'] == '0'
    assert novig._fee(legacy, novig.CUTOVER_DATE_UTC)['reason'] == 'fee_cutover_time_unverified'
    assert novig._fee(pregame, novig.CUTOVER_DATE_UTC)['coefficient'] == '3/100'
    assert novig._fee(legacy, novig.CUTOVER_DATE_ET)['reason'] == 'fee_schedule_unverified'
    assert novig._fee(pregame, novig.CUTOVER_DATE_ET)['coefficient'] == '3/100'


def test_paginated_event_is_one_invocation_and_second_market_keeps_own_receipt(monkeypatch):
    monkeypatch.setattr(novig, 'REQUEST_SPACING_SECONDS', 0)
    first, second = binding(), binding(3, '-16.5')
    calls = []

    def server(req):
        calls.append(req)
        row = market(first if len(calls) == 1 else second)
        return httpx.Response(200, json=dict(items=[row], next='cursor' if len(calls) == 1 else None),
                             headers={'date':format_datetime(CUTOFF, usegmt=True),
                                      'cache-control':'public, max-age=10'})

    async def read():
        async with novig.NovigExperimentDepth(transport=httpx.MockTransport(server),
                                             clock=lambda: CUTOFF-timedelta(seconds=1)) as worker:
            return await worker.read_event(first['event_id'], CUTOFF)

    result = asyncio.run(read())
    assert result.reason is None
    assert len(result.markets) == 2
    assert len(calls) == 2 and all(request.method == 'GET' for request in calls)
    assert calls[0].url.params['eventStatus'] == 'OPEN_PREGAME'
    assert calls[1].url.params['after'] == 'cursor'
    assert result.markets[second['market_id']]['receipt']['params']['after'] == 'cursor'
    assert len(result.markets[first['market_id']]['receipt']['sha256']) == 64


def test_checkpoint_catalog_shares_kickoff_without_reusing_later_observation(monkeypatch):
    monkeypatch.setattr(novig, 'REQUEST_SPACING_SECONDS', 0)
    first = binding()
    second = dict(binding(3, '-16.5'), event_id=uid(7))
    start = datetime.fromisoformat(first['starts_at'])
    calls = []
    now = CUTOFF-timedelta(seconds=1)

    def server(request):
        calls.append(request.url)
        rows = [market(first), market(second)]
        return httpx.Response(200, json=dict(items=rows, next=None), headers={
            'date':format_datetime(now, usegmt=True), 'cache-control':'public, max-age=10'})

    async def read():
        nonlocal now
        async with novig.NovigExperimentDepth(transport=httpx.MockTransport(server), clock=lambda: now) as client:
            original, peer = await asyncio.gather(*(client.read_checkpoint_slate('NCAAB', start, CUTOFF)
                                                   for _ in range(2)))
            assert peer is original
            assert novig.catalog_depth(first,peer,CUTOFF)['complete']
            assert novig.catalog_depth(second,peer,CUTOFF)['complete']
            assert novig.catalog_depth(dict(second,event_id=first['event_id']),peer,CUTOFF)['reason']
            now = CUTOFF+timedelta(seconds=29)
            expired = await client.read_checkpoint_slate('NCAAB', start, CUTOFF)
            assert expired.reason == 'after_cutoff'
            followup = await client.read_checkpoint_slate('NCAAB', start, CUTOFF+timedelta(seconds=30))
            assert followup.receipts != original.receipts

    asyncio.run(read())
    assert len(calls) == 2
    assert all(q.params['league']=='NCAAB' and 'event' not in q.params for q in calls)
    assert int(calls[0].params['startsBefore'])-int(calls[0].params['startsAfter']) == 2


@pytest.mark.parametrize('retry_after', ['15', format_datetime(CUTOFF+timedelta(seconds=15), usegmt=True)])
def test_retry_after_blocks_another_event_and_market_without_network(retry_after):
    calls = []

    def server(req):
        calls.append(req)
        return httpx.Response(429, headers={'retry-after':retry_after})

    async def read():
        async with novig.NovigExperimentDepth(transport=httpx.MockTransport(server),
                                             clock=lambda: CUTOFF-timedelta(seconds=1)) as worker:
            first = await worker.read_event(uid(1), CUTOFF)
            assert first.reason == 'throttled'
            assert first.receipts[0]['retry_after_seconds'] > 0
            assert (await worker.read_event(uid(2), CUTOFF)).reason == 'throttled'
            assert (await worker.read_book(uid(3), CUTOFF)).reason == 'throttled'

    asyncio.run(read())
    assert len(calls) == 1


def test_cutoff_cancels_inflight_and_never_sends_after_deadline():
    calls = []

    async def server(req):
        calls.append(req)
        await asyncio.sleep(0.5)
        return httpx.Response(200, json={'items':[]})

    async def read():
        async with novig.NovigExperimentDepth(transport=httpx.MockTransport(server)) as worker:
            cutoff = datetime.now(timezone.utc) + timedelta(milliseconds=50)
            result = await worker.read_event(uid(1), cutoff)
            assert result.reason == 'after_cutoff'
            assert result.receipts == ()
            assert (await worker.read_book(uid(2), cutoff)).reason == 'after_cutoff'

    asyncio.run(read())
    assert len(calls) == 1
