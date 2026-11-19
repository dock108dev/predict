"""Compact history of admitted quotes, with explicit evidence and coverage limits."""
from datetime import timedelta, timezone
from contextlib import contextmanager
from decimal import Decimal
from hashlib import sha256
import logging
import os

from psycopg.types.json import Jsonb

from .odds_retention import pregame, sgo_pregame
from .store import encoded, exact_time, stamp

STAGING_MAX = 64 * 1024 * 1024
SQL_RUNWAY = 192 * 1024 * 1024
MAX_BATCH_ROWS = 1024
MAX_BATCH_BYTES = 512 * 1024
FEEDS = frozenset(('kalshi', 'polymarket_us', 'sportsgameodds'))
VERSION = 1
LOGGER = logging.getLogger(__name__)


def enabled():
    return os.environ.get('PREDICT_ODDS_ARCHIVE_CAPTURE') == '1'


def digest(value):
    return sha256(encoded(value)).hexdigest()


def decimal_key(value):
    if value is None:
        return None
    number = Decimal(value)
    # Decimal.normalize() rounds to the ambient context precision.
    sign, digits, exponent = number.as_tuple()
    if not any(digits):
        return [0, '0', 0]
    digits = ''.join(map(str, digits))
    trimmed = digits.rstrip('0')
    return [sign, trimmed, exponent + len(digits) - len(trimmed)]


def observation(feed, kind, identity, event, source_at, received_at, evidence, data,
                *, material=None, expires_at=None):
    scope = digest([feed, event, identity])
    body = [VERSION, kind, scope, event, source_at, received_at, evidence, data]
    received = stamp(received_at)
    return dict(id=digest(body), identity=digest([kind,scope]),
                material=digest(data if material is None else material),
                day=received.astimezone(timezone.utc).date().isoformat(),
                received_at=received_at,
                expires_at=expires_at or (received + timedelta(days=2)).isoformat(),
                bytes=len(encoded(body)), body=body)


def facts_without_transport(facts):
    if isinstance(facts, list):
        return [facts_without_transport(item) for item in facts]
    if isinstance(facts, dict):
        return {key: facts_without_transport(value) for key, value in facts.items()
                if key not in ('received_at', 'observed_at', 'projected_at', 'receipt_sha256',
                               'material_sha256', 'observed_at_from_quote_receipt')}
    return facts


def normalized_definition(prepared, event, event_revision, contract_revision, *, link=None):
    source = prepared['source']
    feed = source['provider']
    quote = prepared['quote']
    meta = prepared['contract'].get('comparison_source_metadata') or {}
    if not pregame(event['scheduled_start'], prepared['received_at'], source_at=prepared['source_at'],
                   phase=meta.get('phase') if meta.get('phase') != 'unknown' else None,
                   status=meta.get('provider_event_status'), event=event):
        return ()
    contract = facts_without_transport(prepared['contract'])
    matching = {name: contract.pop(name) for name in
                ('verified', 'orientation_evidence', 'event_scope') if name in contract}
    data = dict(event_id=prepared['event_id'], contract_id=prepared['contract_id'],
                source=source, contract=contract,
                quote_rules={name: quote[name] for name in
                             ('rule_note', 'cost_note', 'rules_differ', 'native_predicate',
                              'freshness_policy') if name in quote},
                units={name: value for name, value in quote['original'].items()
                       if name not in ('value', 'native_value')})
    if link:
        data['reference_identity'] = link[0]
    expiry = (stamp(event['scheduled_start']) + timedelta(days=2)).isoformat()
    event_observation = observation(feed, 'event', prepared['event_id'], source['native_event_id'],
                                    None, prepared['received_at'], event_revision,
                                    facts_without_transport(event), expires_at=expiry)
    definition = observation(feed, 'definition', prepared['contract_id'], source['native_event_id'],
                             None, prepared['received_at'], contract_revision, data,
                             expires_at=expiry)
    match = observation(feed, 'matching', prepared['contract_id'], source['native_event_id'],
                        None, prepared['received_at'], contract_revision, matching, expires_at=expiry)
    if not link or prepared['missing']:
        return event_observation, definition, match
    original = quote['original']
    execution = [original['value'], original['units'], original['quantity_units'], quote['state']]
    execution_quote = observation(feed, 'execution_quote', prepared['contract_id'], source['native_event_id'],
                                  prepared['source_at'], prepared['received_at'], [*link,prepared['revision']],
                                  execution, expires_at=expiry)
    return event_observation, definition, match, execution_quote


def native_book(book, *, revision, event, starts_at):
    raw = book['raw']
    ref = raw['ref']
    feed, event_id, market = ref['venue'], ref['event_id'], ref['market_id']
    state = book['state']
    sequence = str(book['sequence']) if book.get('sequence') is not None else None
    received, source = raw['received_at'], raw.get('exchange_at')
    if not pregame(starts_at, received, source_at=source, event=event):
        return ()
    expires_at = (stamp(starts_at) + timedelta(days=2)).isoformat()
    confirmation = book.get('book_confirmation')
    witness = [revision, sequence]
    closed = state in ('closed', 'settled', 'canceled')
    top = []
    for outcome in book['outcomes']:
        for side in ('asks', 'bids'):
            ladder = outcome[side]
            level = (ladder['levels'] or [None])[0] if ladder else None
            price = level['price']['value'] if level is not None and not closed else None
            quantity = level['quantity']['value'] if level is not None and not closed else None
            units = level['price'].get('unit', level['price'].get('units', 'usd_per_contract')) if level else None
            availability = 'closed' if closed else 'missing_side' if ladder is None else 'empty' if level is None else state
            identity = [market, outcome['outcome_id'], side]
            data = [*identity, price, units, quantity, book['quantity_unit'], availability]
            material = [decimal_key(price), units, decimal_key(quantity), book['quantity_unit'], availability]
            top.append(observation(feed, 'top', identity, event_id, source, received, witness, data,
                                   material=material, expires_at=expires_at))
    if confirmation:
        top.append(observation(feed, 'confirmation', market, event_id, source, received, witness,
                               [market, confirmation], expires_at=expires_at))
    elif not closed and source:
        # An unchanged top with advancing depth time can refresh price authority.
        # Keep the earliest evidenced clock in each bucket. Replay may only
        # renew the prior top for this exact market from this receipt onward.
        top.append(observation(feed, 'book_clock', market, event_id, source, received, witness,
                               [market], material=int(exact_time(source) // 15), expires_at=expires_at))
    if closed:
        top.append(observation(feed, 'book_status', market, event_id, source, received, witness,
                               [market, state], expires_at=expires_at))
    return top


def sgo_material(facts):
    return [decimal_key(facts['price_american']), facts['available'], facts['provider_available'],
            facts['unavailable_reason'], facts['fair']]


def sgo_quote(row, previous=None):
    facts = row['facts']
    if not sgo_pregame(facts):
        return ()
    event = row['event_id']
    feed = 'sportsgameodds'
    source, received = facts['source_at'], facts['received_at']
    evidence = [row['revision'], facts['receipt_sha256'], facts['source_at_original']]
    # Keep the original price, and any source-provided fair price as an input
    # witness, with an explicit null size (the provider exposes no executable size).
    price = facts['price_american']
    context = {name: facts[name] for name in
               ('odd_id', 'opposing_odd_id', 'venue', 'line', 'period', 'market', 'side',
                'settlement', 'alternate', 'consensus') if name in facts}
    event_facts = {name: facts[name] for name in
                   ('aliases', 'league', 'teams', 'starts_at', 'event_status', 'phase')}
    payload = [price, 'american_odds', None, None, facts['available'], facts['provider_available'],
               facts['unavailable_reason'], facts['fair']]
    material = sgo_material(facts)
    expiry = max(stamp(facts['starts_at']) + timedelta(days=2),
                 stamp(received) + timedelta(days=1)).isoformat()
    items = [
        observation(feed, 'top', row['id'], event, source, received, evidence, payload,
                    material=material, expires_at=expiry),
        observation(feed, 'definition', row['id'], event, source, received, evidence,
                    context, expires_at=expiry),
        observation(feed, 'event', event, event, source, received, evidence, event_facts,
                    expires_at=expiry),
    ]
    # A material change already carries both clocks. Witness thinning applies
    # only when the existing reference stayed economically identical.
    if source and previous and sgo_material(previous['facts']) == material:
        items.append(observation(feed, 'quote_clock', row['id'], event, source, received, evidence,
                                 [], material=int(exact_time(source) // 300), expires_at=expiry))
    return items


def source_status(feed, state, at):
    facts = {field: state[field] for field in ('state', 'reason_code', 'observed_sports') if field in state}
    return (observation(feed, 'source_status', feed, None, None, at, None, facts),)


def sgo_page(row):
    at = row['received_at']
    refs = row['sgo_reference_rows']
    receipt = row.get('receipt_sha256') or (refs[0]['facts']['receipt_sha256'] if refs else None)
    # The page receipt attests transport/admission, never freshness for an
    # individual bookmaker quote. No success inferred across omitted events.
    pregame_ids = {frame['event_id'] for frame in row['sgo_event_frames'] if sgo_pregame(frame['facts'])}
    events = sorted((event, league) for event, league in row['event_scopes'].items() if event in pregame_ids)
    if not events:
        return ()
    result = [observation('sportsgameodds', 'page_receipt', row['sport'], None, None, at,
                          receipt, events, material=[at, receipt, events])]
    if row.get('collection_run'):
        # Every successful collection is retained, including unchanged prices.
        # Run receipt time never replaces any individual source timestamp.
        for event, league in events:
            data = dict(collection_run=row['collection_run'], league=league,
                        records=[r for r in row['records'] if r['event']['id']==event],
                        references=[r for r in refs if r['event_id']==event],
                        frames=[f for f in row['sgo_event_frames'] if f['event_id']==event])
            result.append(observation('sportsgameodds', 'collection_snapshot',
                                      [row['collection_run']['id'],event],event,None,at,receipt,data,
                                      material=[row['collection_run']['id'],at,receipt,event]))
    return tuple(result)


def observation_gap(key, at, reason, *, event):
    if event is None or not pregame(event.get('scheduled_start'), at, event=event):
        return ()
    feed, event_id, market = key
    return (observation(feed, 'discovery_gap', market, event_id, None, at, None,
                        [market, reason], material=[at, reason] if reason!='discovery_suspected_absent'
                        else [int(exact_time(at)//900), reason]),)


def runtime_status(feed, owner, at):
    facts = dict(state=owner['state'], dispatch=owner['dispatch'],
                 global_stopped=owner['global_stopped'], paused=feed in owner['paused_sources'],
                 runtime_id=str(owner['runtime_id']))
    return (observation(feed, 'runtime_status', feed, None, None, at, None, facts),)


@contextmanager
def capture(db):
    """Called inside admission, outside any pipelined SQL command region."""
    work = [] if enabled() else None
    yield work
    if not work:
        return
    grouped = {}
    for feed, builder, args, kwargs in work:
        try:
            grouped.setdefault(feed, []).extend(builder(*args, **kwargs))
        except Exception:
            LOGGER.exception('Odds archive could not project admitted %s evidence', feed)
            note_gap(db, feed, 1, 'archive_projection_failed')
    for feed, items in grouped.items():
        record(db, feed, items)


def gap(db, feed, count, reason, *, earliest=None, latest=None):
    db.execute('''INSERT INTO odds_archive_feed_status
        (feed,skipped,first_gap_at,last_gap_at,gap_reason)
        VALUES (%s,%s,COALESCE(%s,clock_timestamp()),COALESCE(%s,clock_timestamp()),%s)
        ON CONFLICT(feed) DO UPDATE SET
            skipped=odds_archive_feed_status.skipped+excluded.skipped,
            first_gap_at=LEAST(odds_archive_feed_status.first_gap_at,excluded.first_gap_at),
            last_gap_at=GREATEST(odds_archive_feed_status.last_gap_at,excluded.last_gap_at),
            gap_reason=excluded.gap_reason''', (feed,count,earliest,latest,reason))


@contextmanager
def archive_write(db):
    with db.transaction():
        previous_timeout = db.execute("SELECT current_setting('lock_timeout') timeout").fetchone()['timeout']
        db.execute("SET LOCAL lock_timeout='200ms'")
        yield
        db.execute("SELECT set_config('lock_timeout',%s,true)", (previous_timeout,))


def note_gap(db, feed, count, reason, **bounds):
    try:
        with archive_write(db):
            # Use the same lock order as staging and acknowledgement even
            # when the original staging savepoint has already rolled back.
            db.execute('SELECT 1 FROM odds_archive_usage WHERE singleton FOR UPDATE')
            gap(db, feed, count, reason, **bounds)
    except Exception:
        LOGGER.exception('Could not persist odds archive gap for %s', feed)


INPUT = '''SELECT ord, decode(id,'hex') id, decode(identity,'hex') identity,
    decode(material,'hex') material, day, received_at, expires_at, bytes, body
    FROM jsonb_to_recordset(%s) AS input(ord integer,id text,identity text,material text,day date,
                              received_at timestamptz,expires_at timestamptz,bytes integer,body jsonb)'''


def _append(db, feed, rows, limit):
    """Current-row lock owns admission order. The usage row serializes only ack."""
    from app.collection.current_storage_policy import SQL_BYTE_CAP

    # Duplicates in a batch must preserve successive moves. Partition them in
    # the caller, where receipt order is the exact source writer's order.
    with db.transaction():
        allowance = db.execute('''SELECT GREATEST(0,LEAST(%s-staged_bytes,
            (%s-pg_database_size(current_database()))/3)) AS bytes
            FROM odds_archive_usage WHERE singleton FOR UPDATE''',
            (limit, SQL_BYTE_CAP - SQL_RUNWAY)).fetchone()['bytes']
        result = db.execute(f'''WITH offered AS ({INPUT}), changes AS (
            SELECT i.* FROM offered i LEFT JOIN odds_archive_head h USING(identity)
            WHERE i.material IS DISTINCT FROM h.material
              AND NOT EXISTS(SELECT 1 FROM odds_archive_stage s WHERE s.id=i.id)
        ), accepted AS (
            SELECT * FROM (SELECT c.*,sum(bytes) OVER (ORDER BY ord) total FROM changes c) ranked
            WHERE total<=%s
        ), staged AS (
            INSERT INTO odds_archive_stage(id,feed,receipt_day,received_at,bytes,body)
            SELECT id,%s,day,received_at,bytes,body FROM accepted RETURNING bytes
        ), heads AS (
            INSERT INTO odds_archive_head(identity,material,expires_at)
            SELECT identity,material,expires_at FROM accepted
            ON CONFLICT(identity) DO UPDATE SET material=excluded.material,expires_at=excluded.expires_at
        ), dropped AS (
            SELECT count(*) skipped,min(received_at) earliest,max(received_at) latest FROM changes c
            WHERE NOT EXISTS(SELECT 1 FROM accepted WHERE id=c.id)
        )
        SELECT (SELECT COALESCE(sum(bytes),0) FROM staged) bytes,
            (SELECT count(*) FROM staged) staged,dropped.* FROM dropped''',
            (Jsonb(rows), allowance, feed)).fetchone()
        if result['staged']:
            db.execute('UPDATE odds_archive_usage SET staged_bytes=staged_bytes+%s WHERE singleton', (result['bytes'],))
            db.execute('''INSERT INTO odds_archive_feed_status(feed,staged,last_staged_at)
                VALUES (%s,%s,clock_timestamp()) ON CONFLICT(feed) DO UPDATE SET
                staged=odds_archive_feed_status.staged+excluded.staged,last_staged_at=excluded.last_staged_at''',
                (feed,result['staged']))
        if result['skipped']:
            gap(db,feed,result['skipped'],'staging_or_disk_capacity',
                earliest=result['earliest'],latest=result['latest'])


def record(db, feed, items, *, limit=STAGING_MAX):
    if feed not in FEEDS:
        raise ValueError('odds_archive_unknown_feed')
    if not items:
        return
    pending = {}
    size = 0
    try:
        with archive_write(db):
            # Preserve per-identity order, but avoid writing repeated event
            # definitions seen on every side of a page.
            for item in items:
                prior = pending.get(item['identity'])
                if prior and prior['material'] == item['material']:
                    continue
                if prior or len(pending) >= MAX_BATCH_ROWS or pending and size + item['bytes'] > MAX_BATCH_BYTES:
                    _append(db, feed, list(pending.values()), limit)
                    pending.clear()
                    size = 0
                pending[item['identity']] = dict(item, ord=len(pending))
                size += item['bytes']
            if pending:
                _append(db, feed, list(pending.values()), limit)
    except Exception:
        # An archive statement failure rolls back its savepoint, while normal
        # source admission keeps its own independently guarded transaction.
        LOGGER.exception('Odds archive staging failed for %s', feed)
        clocks = [stamp(item['received_at']) for item in items]
        note_gap(db, feed, len(items), 'staging_write_failed', earliest=min(clocks), latest=max(clocks))
