"""Publish and inspect one complete pregame board per requested dollar amount."""
from collections import Counter, defaultdict
from fractions import Fraction
from decimal import Decimal
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from time import monotonic

from app.collection.current_storage_policy import SQL_BYTE_CAP, sql_usage
from app.comparison import pregame_reference, pregame_valuation
from app.comparison.calculation_control import checkpoint
from app.comparison.cashflows import exact_wire
from app.comparison.sgo_rule_evidence import RULES
from app.dashboard.snapshot_display import desk_game_aliases, outcome_id, outcome_key
from app.dashboard.trade_desk import direct_venue_offer, game_source_key, published_lines, source_event_key
from app.fees import product_schedules, schedule_lifecycle

from . import comparison_snapshot as snapshots
from .pregame_publication import project
from .ordinary_projection import withdrawn_events
from .sportsgameodds_reference import quote_identity
from .storage_maintenance import REWRITE_RUNWAY_BYTES
from .store import hashed, stamp

SCHEMA = 'predict-pregame-board-1'
MAX_AMOUNTS = 8
MAX_CACHE_BYTES = 48 * 1024 * 1024
MAX_PACKET = 8 * 1024 * 1024
WORK_SECONDS = 1.0


@lru_cache(maxsize=1)
def policy_id():
    directory = Path(pregame_valuation.__file__).parent
    return hashed([SCHEMA, pregame_valuation.VERSION, pregame_valuation.SIZING, pregame_reference.VERSION, [
        sha256(path.read_bytes()).hexdigest() for path in (
            Path(__file__), directory / 'pregame_valuation.py', directory / 'pregame_valuation_fees.py',
            directory / 'pregame_reference.py', RULES, RULES.with_name('sgo-reviewed-jurisdiction-bindings.json'))]])


def request(db, cents):
    """Coalesce outstanding amounts. Prefer retaining recently requested boards."""
    with db.transaction():
        db.execute("SET LOCAL lock_timeout='100ms'")
        if db.execute('''SELECT 1 FROM pregame_unit_board WHERE unit_cents=%s
            AND requested_at>=clock_timestamp()-interval '5 seconds' ''', (cents,)).fetchone():
            return
        if not db.execute('SELECT pg_try_advisory_xact_lock(901197) AS held').fetchone()['held']:
            return
        db.execute('''INSERT INTO pregame_unit_board(unit_cents) VALUES (%s) ON CONFLICT(unit_cents)
            DO UPDATE SET requested_at=clock_timestamp()
            WHERE pregame_unit_board.requested_at<clock_timestamp()-interval '5 seconds' ''', (cents,))
        db.execute('''DELETE FROM pregame_unit_board WHERE unit_cents IN (
            SELECT unit_cents FROM pregame_unit_board ORDER BY requested_at DESC,unit_cents DESC OFFSET %s)''',
            (MAX_AMOUNTS,))


def read(db, cents):
    return db.execute('''SELECT unit_cents,root_id,board_id,policy_id,projection,error
        FROM pregame_unit_board WHERE unit_cents=%s''', (cents,)).fetchone()


def refs(model):
    reference = model['reference']
    if not reference.get('available') or reference.get('source') != 'sportsgameodds':
        return []
    result = []
    for leg in reference['prices']:
        if leg.get('odd_id'):
            line = None
            if leg['line'] is not None:
                signed = Fraction(leg['line'])
                line = Decimal(signed.numerator) / Decimal(signed.denominator)
            result.append(quote_identity(reference['event_id'], reference['book'], leg['odd_id'], line))
    return result


def member_projection(part, cents):
    models = {}
    rows = []
    for row in part['rows']:
        checkpoint()
        if (row['market']['period'] != 'full_game' or not direct_venue_offer(row)
                or row['venue'] == 'pinnacle'
                or row['current_authority']['price'].get('lifecycle', {}).get('state') != 'scheduled'
                or not row['current_authority']['price'].get('expected')
                or set(row['current_authority']['price'].get('reasons', ())) - {'source_expired'}):
            continue
        row = snapshots.expand_row(row)
        model = pregame_valuation.valuation(row, Fraction(cents, 100), publication_id=None,
                                            snapshot_id=part['snapshot_id'])
        models[row['id']] = model
        rows.append(row)
    return dict(rows=rows, games=part['games'], models=models)


def fair_odds(reference):
    value = reference['fair_decimal_odds']
    return dict(american=pregame_valuation.american(Fraction(value)), decimal=value, reason=None)


def compact(row, model, title, role):
    from app.dashboard.snapshot_display import odds

    market = row['market']
    source = row['source']
    price = row['current_authority']['price']
    original = row['original']
    reference = model['reference']
    selected_price = next(p['price_american'] for p in reference['prices']
                          if p['side'] == reference['selected_outcome'])
    benchmark = dict(book=reference['book'], selected_price=selected_price,
                     fair_odds=fair_odds(reference),
                     conditioning=reference['conditioning'])
    return dict(id=model['bet_id'], game_key=row['game_key'], game_title=title, start_at=row['start_at'],
        league=row['league'], market=market, line_role=role,
        game_line_id=outcome_id(outcome_key(row)), game_source=game_source_key(row),
        source_event=source_event_key(row), score=model['raw']['opportunity_score'],
        offer=dict(id=row['id'], venue=row['venue'], selection=row.get('selection'), market=market,
            participant=row.get('participant_label'), source_provider=source.get('provider'),
            original=original, odds=odds(original['value'], original['units'], original.get('payout', '1')),
            posted_price=True, current=True, current_until=row['start_at'], desk_quote_key=price['dependency'],
            quote_freshness=row.get('quote_freshness'),
            source_clock_at=(row.get('times') or {}).get('source_at'),
            source_at=(row.get('times') or {}).get('source_at'),
            received_at=(row.get('times') or {}).get('received_at'), price_revision=model['price_revision'],
            economic_revision=model['economic_revision'], evidence_result_id=model['member_result_id'],
            value=exact_wire(Fraction(model['raw']['net_ev']) * 100), valuation_summary=dict(
                selected_usd=model['selected_usd'], raw=model['raw'], display=model['display'],
                evidence_class=model['evidence_class'], reference_snapshot_id=model['reference_snapshot_id'],
                reference=benchmark,
                settlement_revision=model['settlement_revision'], fee_revision=model['fee_revision'],
                fill_revision=model['fill_revision'])))


def guard_inputs(row, model):
    authority = row['current_authority']
    return dict(id=row['id'], venue=row['venue'], contract=authority['price']['dependency'], start_at=row['start_at'],
        contract_terms=row.get('pregame_contract_authority'),
        event=(row['source'].get('provider'), row['source'].get('native_event_id')),
        references=refs(model), fee_product=product_schedules.key_for(row),
        fee_revision=authority.get('public_fee_revision'),
        fee_deadline=(model.get('fee_evidence') or {}).get('review_before'),
        settlement_deadline=((model.get('settlement') or {}).get('venue_rules') or {}).get('review_before'),
        fallback_deadline=((model.get('reference') or {}).get('rules') or {}).get('review_before'),
        catalog=authority.get('sgo_native_contract'))


def assemble(db, parts, root, *, owner, states, epoch, at):
    rows = [r for part in parts for r in part['rows']]
    games = {g['game_key']: g for part in parts for g in part['games']}
    models = {key: model for part in parts for key, model in part['models'].items()}
    # Resolve sporting authority and same-occurrence witnesses before applying
    # market line eligibility or choosing among venues.
    projected = project(db, dict(rows=rows, games=list(games.values()), pairs=[],
        publication=root['publication']), owner, states, at=at, epoch=epoch,
        withdrawn=withdrawn_events(db, at=at))
    aliases = desk_game_aliases(projected['rows'], games, projected['desk_event_facts'])
    active = {}
    for row in projected['rows']:
        if canonical := aliases.get(row['game_key']):
            selection = (row.get('selection') or {}).get('participant')
            role = next((p.get('role') for p in games[row['game_key']]['participants'] if p.get('id') == selection), None)
            row = dict(row, game_key=canonical, line_participant_role=role)
            row.pop('display_outcome_key', None)
        active[row['id']] = row
    partitions = defaultdict(list)
    blockers = defaultdict(Counter)
    drawers = defaultdict(list)
    guards = {}
    scheduled = {}
    exact_bets = defaultdict(set)
    for key, row in active.items():
        if models[key]['bet_id']:
            exact_bets[outcome_key(row)].add(models[key]['bet_id'])
    for key, row in active.items():
        model = models[key]
        if row['start_at'] != next_start(model, row) or not (row.get('pregame_reference') or {}).get('available'):
            if model['status'] == 'qualified':
                model = dict(model, status='indicative',
                    reasons={'reference': 'reference_occurrence_schedule_changed'})
        partitions[outcome_key(row)].append(row)
        scope = (row['game_key'], row['league'], row['market']['market'], row['venue'], row['start_at'])
        scheduled.setdefault(row['game_key'], {})[tuple(
            (row['source'].get(k) for k in ('provider', 'native_event_id')))] = row['start_at']
        blockers[scope]['offers'] += 1
        blockers[scope].update(set(model['reasons'].values()))
        if model['status'] == 'qualified':
            blockers[scope]['qualified'] += 1
        possible = exact_bets[outcome_key(row)]
        bet = model['bet_id'] or (next(iter(possible)) if len(possible) == 1 else None)
        if bet:
            drawers[bet].append(model)
        guards[key] = guard_inputs(row, model)
    main, line_roles = published_lines(partitions, games.values(), alternates=False)
    by_offer = {}
    for group, rows in partitions.items():
        for row in rows:
            by_offer[row['id']] = (group in main, line_roles.get(outcome_id(group)))
    ranked = pregame_valuation.board_order(
        (model for quotes in drawers.values() for model in quotes), include_alternatives=True)
    priorities = {}
    unranked = []
    positive_ids = {model['offer_id'] for model in ranked}
    for bet, choices in drawers.items():
        ordered = pregame_valuation.drawer_order(choices)
        priorities.update((model['offer_id'], index) for index, model in enumerate(ordered))
        drawers[bet] = [dict(id=m['offer_id'], member=m['member_result_id'], guard=guards[m['offer_id']],
                             status=m['status'], reasons=m['reasons'])
                        for m in ordered]
        for model in ordered:
            key = model['offer_id']
            if model['status'] != 'qualified' or model['venue_type'] != 'marketplace' or key in positive_ids:
                continue
            row = active[key]
            unranked.append(dict(bet_id=bet, game_key=row['game_key'], start_at=row['start_at'], league=row['league'],
                                 family=row['market']['market'], main=by_offer[key][0], guard=guards[key],
                                 member=model['member_result_id']))
    candidates = []
    for model in ranked:
        key = model['offer_id']
        main_line, role = by_offer[key]
        row = active[key]
        game = games.get(row['game_key'], {})
        names = [p['name'] for p in game.get('participants', ()) if p.get('name')]
        title = ' vs. '.join(names) if len(names) == 2 else row['game_title']
        candidates.append(dict(row=compact(row, model, title, role), main=main_line, priority=priorities[key],
                               guard=guards[key]))
    inspectable = {i['row']['id'] for i in candidates} | {entry['bet_id'] for entry in unranked}
    return dict(candidates=candidates, unranked=unranked, drawers={key: drawers[key] for key in inspectable},
        reasons=[dict(game_key=key[0], league=key[1], family=key[2], venue=key[3], start_at=key[4], counts=counts)
                 for key, counts in blockers.items()], games=games,
        events={key: [[*event, start] for event, start in events.items()] for key, events in scheduled.items()},
        publication=projected['publication'], aliases=aliases)


def next_start(model, row):
    return ((model.get('canonical_market') or {}).get('kickoff') or row['start_at'])


def turn(db, *, head, owner, states, epoch, at):
    """Build one unit from the ordinary turn, checkpointing immutable member work."""
    root_id = head['result_id']
    if (not root_id or head['facts'].get('finance') != 'ready'
            or head['facts'].get('component_count') != head['facts'].get('expected_components')):
        return {}
    policy = policy_id()
    job = db.execute('''SELECT b.unit_cents FROM pregame_unit_board b
        LEFT JOIN comparison_snapshot_result prior ON prior.id=b.root_id
        WHERE b.root_id IS DISTINCT FROM %s OR b.policy_id IS DISTINCT FROM %s
        ORDER BY (b.error IS NOT NULL), prior.calculated_at NULLS FIRST, b.requested_at DESC, b.unit_cents
        LIMIT 1''', (root_id, policy)).fetchone()
    if not job:
        return {}
    started = monotonic()
    cents = job['unit_cents']
    root = snapshots._decode(db.execute('SELECT result FROM comparison_snapshot_result WHERE id=%s',
                                        (root_id,)).fetchone()['result'])
    if (root.get('_read_fragments') != 'publication-members-v1'
            or root['publication']['epoch'] != epoch):
        return {}
    members = db.execute('''SELECT r.result_id AS id,v.member_id IS NOT NULL AS cached
        FROM comparison_result_reference r LEFT JOIN pregame_unit_member v ON
        (v.member_id=r.result_id AND v.unit_cents=%s AND v.policy_id=%s)
        WHERE r.kind='member' AND r.holder=%s ORDER BY r.position''', (cents, policy, root_id)).fetchall()
    if len(members) != root['publication']['component_count']:
        raise snapshots.SnapshotOperationError('unit_board_membership_unavailable')
    ids = [m['id'] for m in members]
    db.execute('''DELETE FROM pregame_unit_member v WHERE v.unit_cents=%s
        AND (v.policy_id<>%s OR NOT (v.member_id=ANY(%s))) AND NOT EXISTS (
          SELECT 1 FROM pregame_unit_board b JOIN comparison_result_reference r
            ON r.kind='member' AND r.holder=b.root_id AND r.result_id=v.member_id
          WHERE b.unit_cents=v.unit_cents AND b.policy_id=v.policy_id)''', (cents, policy, ids))
    cached = sum(m['cached'] for m in members)
    built = count = 0
    remaining_bytes = headroom(db)
    for m in members:
        if m['cached']:
            continue
        checkpoint()
        if built and monotonic() - started >= WORK_SECONDS:
            return dict(unit_cents=cents, member_builds=built, member_reuses=cached, pending=True)
        row = db.execute('SELECT read_fragment FROM comparison_snapshot_result WHERE id=%s', (m['id'],)).fetchone()
        part = snapshots._decode(row['read_fragment'])
        packet = member_projection(part, cents)
        count += len(packet['models'])
        body = snapshots.pack_read(packet)
        if len(body) > min(MAX_PACKET, remaining_bytes):
            return capacity(db, cents)
        remaining_bytes -= len(body)
        written = db.execute('''INSERT INTO pregame_unit_member(unit_cents,member_id,policy_id,valuation)
            SELECT unit_cents,%s,%s,%s FROM pregame_unit_board WHERE unit_cents=%s FOR KEY SHARE
            ON CONFLICT DO NOTHING''', (m['id'], policy, body, cents))
        if not written.rowcount:
            return {}
        built += 1
    parts = []
    with db.transaction(), db.cursor(name='unit_board_members') as cursor:
        cursor.execute('''SELECT valuation FROM pregame_unit_member
            WHERE unit_cents=%s AND policy_id=%s AND member_id=ANY(%s) ORDER BY member_id''', (cents, policy, ids))
        for row in cursor:
            checkpoint()
            parts.append(snapshots._decode(row['valuation']))
    if len(parts) != len(ids):
        return {}
    projection = assemble(db, parts, root, owner=owner, states=states, epoch=epoch, at=at)
    board_id = hashed([SCHEMA, cents, root_id, ids, policy, projection['events']])
    body = snapshots.pack_read(projection)
    if len(body) > min(MAX_PACKET, headroom(db)):
        return capacity(db, cents)
    with db.transaction():
        if db.execute("SELECT result_id FROM comparison_publication WHERE kind='live' AND id='' FOR SHARE"
                      ).fetchone()['result_id'] != root_id:
            return dict(unit_cents=cents, pending=True, superseded=True)
        if str(db.execute('SELECT epoch FROM current_row_epoch').fetchone()['epoch']) != epoch:
            return dict(unit_cents=cents, pending=True, superseded=True)
        written = db.execute('''UPDATE pregame_unit_board SET board_id=%s,root_id=%s,policy_id=%s,projection=%s,error=NULL
            WHERE unit_cents=%s''', (board_id, root_id, policy, body, cents))
    return dict(unit_cents=cents, published=bool(written.rowcount), board_id=board_id,
                member_builds=built, member_reuses=cached, valuations=count,
                board_bytes=len(body), seconds=round(monotonic() - started, 4))


def headroom(db):
    used = db.execute('''SELECT (SELECT coalesce(sum(octet_length(valuation)),0) FROM pregame_unit_member)
        + (SELECT coalesce(sum(octet_length(projection)),0) FROM pregame_unit_board) AS n''').fetchone()['n']
    return min(MAX_CACHE_BYTES - used, (SQL_BYTE_CAP - sql_usage(db) - REWRITE_RUNWAY_BYTES) // 2)


def capacity(db, cents):
    db.execute("UPDATE pregame_unit_board SET error='unit_board_capacity' WHERE unit_cents=%s", (cents,))
    return dict(unit_cents=cents, error='unit_board_capacity')


def stored_parts(db, cents, policy, member_ids):
    return {r['member_id']: snapshots._decode(r['valuation']) for r in db.execute('''
        SELECT member_id,valuation FROM pregame_unit_member
        WHERE unit_cents=%s AND policy_id=%s AND member_id=ANY(%s)
        ''', (cents, policy, list(member_ids)))}


def service(db, *, head, owner, states, epoch, at):
    """Share one writer between ordinary turns and the app-only worker."""
    from .ordinary_desk_projection import backfill

    if not db.execute('SELECT pg_try_advisory_lock(901198) AS held').fetchone()['held']:
        return dict(busy=True)
    try:
        written = backfill(db, head['result_id'])
        board = turn(db, head=head, owner=owner, states=states, epoch=epoch, at=at)
        return dict(unit_board=board, desk_fragment_bytes=written,
                    more=bool(written or board.get('pending') or board.get('published')))
    finally:
        db.execute('SELECT pg_advisory_unlock(901198)')


def app_turn(db):
    """Service committed inputs when the ordinary data process is absent."""
    from . import ordinary_publication
    from .current_games import utc

    at = stamp(utc())
    owner, states = ordinary_publication.authority(db, at=at, include_diagnostics=False)
    if owner.get('healthy') or owner.get('calculations', {}).get('board') == 'stopped':
        return {}
    head = ordinary_publication.status(db)
    epoch = str(db.execute('SELECT epoch FROM current_row_epoch').fetchone()['epoch'])
    return service(db, head=head, owner=owner, states=states, epoch=epoch, at=at)
