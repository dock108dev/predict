"""Admitted aggregate venue prices can reach the desk before finance publication."""
from datetime import timedelta

from app.collection.current_policy import aggregate_scope, native_scope
from app.collection.sportsgameodds_adapter import PROPHETX_BOOKMAKER_ID
from app.comparison.cashflows import exact_wire
from app.comparison.game_phase import LIVE_SECONDS, ODDSLINK_LIVE_SECONDS, PREGAME_SPORTSBOOK_SECONDS
from app.comparison.public_sportsbook_estimate import SOURCE as ODDSLINK, allowed, outcome, select as public_estimate, signature
from app.comparison.sgo_reference import BEST_BOOKS
from app.comparison.sgo_reference_publication import FrameQuoteIndex
from app.comparison.sgo_sportsbook_baseline import select as sportsbook_baseline
from app.comparison.snapshot_fee_outcome import unavailable
from app.comparison.sporting_scope import supported
from app.dashboard.current_contract import price
from app.normalization.registry import Registry
from .comparison_snapshot import expand_row
from .current_native_desk import game_signature
from .current_rows import project_contract
from .ordinary_projection import occurrence_key, source_allowed
from .schedule_metadata import witness
from .sportsgameodds_reference import EventInputs
from .store import hashed, stamp


SGO = 'sportsgameodds'
PREFIX = 'aggregate-current:'


def active_offers(db, *, at, phase, venues, providers, sports, contract=None, event_ids=None):
    # An accepted aggregate source clock cannot be later than its receipt.
    maximum = max(LIVE_SECONDS, ODDSLINK_LIVE_SECONDS) if phase == 'live' else PREGAME_SPORTSBOOK_SECONDS
    return db.execute('''SELECT c.id, c.venue, e.provider, e.competition, e.facts AS event, c.facts AS contract,
        o.source_at, o.received_at, o.revision AS offer_revision, o.price_dependency AS price_revision,
        c.revision AS contract_revision, e.revision AS event_revision,
        CASE WHEN sgo.id IS NOT NULL THEN jsonb_set(o.facts,'{original,value}',sgo.facts->'price_american')
             ELSE o.facts END AS quote
        FROM current_event e JOIN current_contract c ON c.event_id=e.id
        JOIN current_offer_storage o ON o.contract_id=c.id
        LEFT JOIN sgo_quote_revision sgo ON (sgo.id,sgo.revision)=(o.sgo_quote_id,o.sgo_quote_revision)
          AND sgo.event_id=e.native_event_id AND sgo.facts->>'source_at'=o.source_at
          AND sgo.facts->>'odd_id'=c.native_outcome_id AND sgo.facts->'available'='true'::jsonb
          AND (sgo.facts->>'line')::numeric IS NOT DISTINCT FROM (o.facts#>>'{source,native_line}')::numeric
        WHERE e.provider=ANY(%s) AND e.competition=ANY(%s) AND c.venue=ANY(%s)
          AND (%s::text IS NULL OR c.id=%s)
          AND (%s::text[] IS NULL OR e.id=ANY(%s))
          AND e.scheduled_start::timestamptz <= %s AND (e.scheduled_start::timestamptz > %s)=%s
          AND e.expires_order >= extract(epoch FROM %s::timestamptz)
          AND o.source_order >= extract(epoch FROM %s::timestamptz) AND o.source_order <= o.received_order
          AND o.received_order <= extract(epoch FROM %s::timestamptz)
          AND o.native_book_id IS NULL AND o.facts->>'state'='available'
          AND ((e.provider='sportsgameodds' AND sgo.id IS NOT NULL)
               OR (e.provider=%s AND c.venue='prophetx' AND o.sgo_quote_id IS NULL))
        ORDER BY c.id''',
        (providers, sports, venues, contract, contract, event_ids, event_ids, at + timedelta(hours=72), at, phase == 'pregame',
         at, at - timedelta(seconds=maximum), at, ODDSLINK))


def prior_finance(prior, quote, authority):
    if not prior or not prior.get('price_current') or prior['original'] != quote['original']:
        return None
    original = prior['current_authority']['price']
    if ((original.get('expected') or ())[:3] != authority['expected']
            or original.get('clock_at') != authority['clock_at']
            or prior.get('times', {}).get('received_at') != quote['times']['received_at']):
        return None
    return expand_row(prior)


def game_for(event, key, prior, games, dependencies, registry):
    if prior:
        expected = prior['current_authority']['price'].get('expected') or ()
        game = games.get(prior['game_key'])
        if expected[1:3] == dependencies[1:3] and game and game_signature(game) == key:
            return game
    league, start, home, away = key
    names = {team: name for name, team in event['participants'].items()}
    participants = [dict(id=team, role=role, name=registry.entities.get(team, {}).get('name', names.get(team, team)))
                    for role, team in (('away', away), ('home', home))]
    return dict(game_key=PREFIX + hashed(event['schedule_metadata']['authority']),
                title=event['title'], league=league, start_at=start.isoformat(), participants=participants)


def overlay(db, result, owner, states, *, at, phase, contract=None, sgo_inputs=None, event_ids=None):
    from app.collection.oddslink_prophetx import live_occurrences
    from .ordinary_publication import pregame_sportsbooks, quote_authority

    if not owner.get('healthy') or not allowed(owner):
        return result
    config = owner['config']
    venues = [name for name in ('novig', 'prophetx') if name not in owner.get('paused_sources', ())]
    sports = set(aggregate_scope(config))
    native_sports = set(native_scope(config))
    providers = [provider for provider in (SGO, ODDSLINK) if source_allowed(states.get(provider, {}))]
    if not (venues and sports and providers):
        return result
    games = {game['game_key']: game for game in result['games']}
    prior = {row['current_authority']['price'].get('dependency'): row for row in result['rows']
             if (row.get('source') or {}).get('provider') in providers}
    blocked = {occurrence_key(row) for row in result['rows']
               if row.get('game_state') in ('final', 'cancelled', 'suspended')}
    live_oddslink = {}
    selected = {}
    registry = Registry.current()
    expected_state = 'live' if phase == 'live' else 'scheduled'
    scope = {} if event_ids is None else {'event_ids': event_ids}
    offers = list(active_offers(db, at=at, phase=phase, venues=venues, providers=providers,
                                sports=sorted(sports), contract=contract, **scope))
    sportsbook_indexes = {}
    public_observations = {}
    if phase == 'pregame':
        inputs = sgo_inputs if sgo_inputs is not None else EventInputs(db)
        frames = inputs.frames(item['event']['id'] for item in offers if item['provider'] == SGO)
        quotes = inputs.quotes(frames, bookmakers=(*BEST_BOOKS, 'novig', 'prophetx', PROPHETX_BOOKMAKER_ID),
                              source_since=at - timedelta(seconds=PREGAME_SPORTSBOOK_SECONDS), game_markets=True)
        sportsbook_indexes = {event_id: FrameQuoteIndex(rows, frames[event_id]) for event_id, rows in quotes.items()}
        public_occurrences = {signature(item['event'], item['competition']) for item in offers
                              if item['provider'] == ODDSLINK}
        if public_occurrences:
            public_observations = pregame_sportsbooks(db, owner, states, at, occurrences=public_occurrences,
                                                      sgo_inputs=inputs)
    for stored in offers:
        q, event, cid, provider = (stored[key] for key in ('quote','event','id','provider'))
        row_source, league = q['source'], stored['competition']
        if (not source_allowed(states[provider], league) or provider == ODDSLINK and league not in native_sports
                or row_source['provider'] != provider or row_source['native_event_id'] != event['id']
                or q['venue'] != stored['venue'] or q['original']['units'] != 'american_odds'):
            continue
        q['times'] = dict(q['times'], source_at=stored['source_at'], received_at=stored['received_at'])
        record = dict(project_contract(event, stored['contract'], stored['received_at']), quote=q, event=event)
        market = record['market_identity']
        family, period = market['family'], market['period']
        if (period != 'full_game' or family not in config['families'] or not supported(league, family, period)
                or event['home'] == event['away'] or stamp(market['scheduled_start']) != stamp(event['scheduled_start'])
                or not outcome(family, record['selection'], event['home'], event['away'])
                or not witness(event)):
            continue
        occurrence = signature(event, league)
        if provider == ODDSLINK and phase == 'live':
            if league not in live_oddslink:
                live_oddslink[league] = live_occurrences(db, league, at)
            if occurrence[1:] not in live_oddslink[league]:
                continue
        dependencies = [stored[field] for field in ('price_revision', 'contract_revision', 'event_revision')]
        raw = dict(original=q['original'], source=row_source, venue=q['venue'], league=league, times=q['times'])
        authority = quote_authority(dict(raw, original_record=record), dict(captured_at=at, dependencies={cid: dependencies}))
        lifecycle = authority['lifecycle']
        if authority['reasons'] or not authority['expected'] or lifecycle['state'] != expected_state:
            continue
        original = prior.get(cid)
        game = game_for(event, occurrence, original, games, dependencies, registry)
        if (game['game_key'], stamp(game['start_at'])) in blocked:
            continue
        games[game['game_key']] = game
        finance = prior_finance(original, q, authority) if original and original['game_key'] == game['game_key'] else None
        row = dict(finance) if finance else dict(raw, probability_missing='finance_pending',
            trade_fee=unavailable('fee_outcome_not_published'),
            reference_calculation=dict(available=False, reason='finance_pending'),
            current_authority=dict(price=authority, references=[]),
            market=dict(market='winner' if family == 'moneyline' else family, period=period, line=market.get('line')),
            selection=dict(record['selection'], result_interpretation='normal_win'),
            cost_per_normal_claim=exact_wire(price(raw)),
            alternate=(record.get('comparison_source_metadata') or {}).get('alternate'))
        row.update(id=PREFIX + cid, kind='single', game_key=game['game_key'], game_title=game['title'],
            start_at=game['start_at'], price_current=True, game_state=lifecycle['state'],
            _desk_event=event,
            game_state_basis=lifecycle.get('basis'), game_state_observed_at=lifecycle.get('observed_at'),
            current_reasons=row.get('current_reasons', []), live_aggregate_desk=True,
            captured_at=row.get('captured_at') or at.isoformat(),
            price_revision=hashed([stored['offer_revision'], stored['received_at']]),
            economic_revision=row.get('economic_revision'))
        baseline = None
        if provider == SGO and (index := sportsbook_indexes.get(event['id'])) is not None:
            baseline = sportsbook_baseline(record, (), index.frame, at=at, index=index)
        elif provider == ODDSLINK and public_observations:
            baseline = public_estimate(dict(raw, original_record=record), authority, public_observations, at=at)
        if baseline is not None:
            row.update(sportsbook_baseline=baseline, sportsbook_return_percent=baseline['return_percent'],
                       economic_revision=hashed([row['economic_revision'], baseline]))
        if contract is not None:
            from app.comparison.inspection_math import offer_disclosures, offer_math

            exact = dict(id=row['id'], original_record=record)
            row['aggregate_inspection'] = dict(offer_math(row), **offer_disclosures(row, row['captured_at'], [exact]))
        selected[cid] = row
    if not selected:
        return result
    retained = [row for row in result['rows'] if row['current_authority']['price'].get('dependency') not in selected]
    rows = retained + list(selected.values())
    current_prices = sum(bool(row.get('price_current')) for row in rows)
    return dict(result, rows=rows, games=list(games.values()),
                publication=dict(result['publication'], current_prices=current_prices, retained_prices=len(rows)-current_prices))
