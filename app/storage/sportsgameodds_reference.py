"""Bounded current SGO bookmaker observations, independent of execution venues.

No settlement authority or complete-scope absence is inferred. All updates must
share the calling source-ingress transaction with the product current rows.
"""
from decimal import Decimal
from datetime import timedelta
import re
from psycopg.types.json import Jsonb

from app.storage.current_rows import LOCK
from app.storage import odds_archive
from app.storage.odds_retention import sgo_pregame, sgo_working_expiry
from app.storage.store import encoded, exact_time, hashed, stamp, now

MAX_ROWS = 16000
MAX_BYTES = 8 * 1024 * 1024
MAX_CURRENT_ROWS = 250000
PRUNE_BATCH = 10000
HISTORY_BYTES = 32 * 1024 * 1024
HISTORY_RUNWAY = 64 * 1024 * 1024


def quote_identity(event, venue, odd, line):
    if line is not None:
        value = Decimal(line)
        line = '0' if value == 0 else str(value.normalize())
    return hashed(['sportsgameodds', event, venue, odd, line])


def offer_quote_link(record, references):
    """Resolve the exact accepted source fact before an offer can reference it."""
    from app.collection.sportsgameodds_current_rows import display_venue, source_bookmaker

    quote = record['quote']
    source = quote['source']
    bookmaker = source_bookmaker(record)
    identity = quote_identity(source['native_event_id'], bookmaker,
                              source['native_outcome_id'], source['native_line'])
    witness = references.get(identity)
    if (display_venue(bookmaker) != quote['venue'] or witness is None
            or witness['facts']['price_american'] != quote['original']['value']
            or witness['facts']['source_at'] != quote['times']['source_at']
            or witness['facts']['available'] != (quote['state'] == 'available')
            or quote['original']['units'] != 'american_odds'):
        raise ValueError('sgo_offer_source_quote_mismatch')
    return identity, witness['revision']


def archive_revisions(db, kind, rows):
    """Best-effort prior witnesses, bounded independently of current facts.

    The caller holds LOCK and supplies only replaced revisions. Rotate the
    oldest witnesses at the logical cap and skip writes near the database cap.
    """
    rows = [row for row in rows if sgo_pregame(row['facts'])]
    if not rows:
        return 0
    from app.collection.current_storage_policy import SQL_BYTE_CAP, sql_usage
    runway = max(0, (SQL_BYTE_CAP - HISTORY_RUNWAY - sql_usage(db)) // 2)
    used = db.execute('SELECT COALESCE(sum(payload_bytes),0) n FROM current_sgo_history').fetchone()['n']
    existing = {(r['identity'], r['revision']) for r in db.execute(
        'SELECT identity,revision FROM current_sgo_history WHERE kind=%s AND identity=ANY(%s)',
        (kind, [r['id'] if kind == 'reference' else r['event_id'] for r in rows])).fetchall()}
    candidates = []
    requested = skipped_capacity = skipped_runway = 0
    for row in rows:
        facts = row['facts']
        size = len(encoded(facts))
        identity = row['id'] if kind == 'reference' else row['event_id']
        revision = row['revision'] if kind == 'reference' else hashed(facts)
        if (identity, revision) in existing:
            continue
        existing.add((identity, revision))
        if requested + size > HISTORY_BYTES:
            skipped_capacity += 1
            continue
        if requested + size > runway:
            skipped_runway += 1
            continue
        candidates.append(dict(identity=identity, revision=revision, event_id=row['event_id'],
                               payload_bytes=size, facts=facts))
        requested += size
    # Rotate only the oldest unpinned audit witnesses. Their independent table
    # is not a source of current, customer, or pinned-original authority.
    evicted = 0
    needed = max(0, used + requested - HISTORY_BYTES) if requested else 0
    while needed:
        removed = db.execute('''WITH oldest AS MATERIALIZED (
            SELECT kind,identity,revision,archived_at,payload_bytes FROM current_sgo_history
            ORDER BY archived_at,kind,identity,revision LIMIT 512), ranked AS (
            SELECT kind,identity,revision,COALESCE(sum(payload_bytes) OVER
              (ORDER BY archived_at,kind,identity,revision ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) before
            FROM oldest), chosen AS (
            SELECT kind,identity,revision FROM ranked WHERE before < %s
            ORDER BY before,kind,identity,revision)
            DELETE FROM current_sgo_history h USING chosen c
            WHERE (h.kind,h.identity,h.revision)=(c.kind,c.identity,c.revision)
            RETURNING h.payload_bytes''', (needed,)).fetchall()
        if not removed:
            break
        needed = max(0, needed - sum(r['payload_bytes'] for r in removed))
        evicted += len(removed)
    saved = 0
    if needed:
        skipped_capacity += len(candidates)
    elif candidates:
        saved = db.execute('''INSERT INTO current_sgo_history
            (kind,identity,revision,event_id,payload_bytes,facts)
            SELECT %s,identity,revision,event_id,payload_bytes,facts
            FROM jsonb_to_recordset(%s) AS prior(identity text,revision text,event_id text,payload_bytes integer,facts jsonb)
            WHERE true
            ON CONFLICT DO NOTHING''', (kind, Jsonb(candidates))).rowcount
    db.execute('''UPDATE sgo_event_evidence SET recorded=recorded+%s,
        skipped_capacity=skipped_capacity+%s,skipped_runway=skipped_runway+%s,
        evicted_capacity=evicted_capacity+%s
        WHERE kind='history_state' AND event_id='' ''', (saved, skipped_capacity, skipped_runway, evicted))
    return saved


def prune_history(db, *, at, limit=PRUNE_BATCH):
    """Expire pregame diagnostics in seven days and legacy in-game data in one."""
    if type(limit) is not int or not 1 <= limit <= PRUNE_BATCH:
        raise ValueError('sgo history prune capacity')
    stamp(at)
    db.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
    return db.execute('''DELETE FROM current_sgo_history WHERE (kind,identity,revision) IN
        (SELECT kind,identity,revision FROM current_sgo_history
         WHERE archived_at < %s::timestamptz - interval '7 days'
            OR (archived_at < %s::timestamptz - interval '1 day'
                AND COALESCE(facts#>>'{event_context,phase}',facts->>'phase') IN ('live','started'))
         ORDER BY archived_at,kind,identity,revision LIMIT %s)''', (at, at, limit)).rowcount


def read_history(db, event_id, *, limit=1000):
    """Read retained witnesses for audit; missing rows do not prove absence."""
    if not isinstance(event_id, str) or not event_id or len(event_id) > 256:
        raise ValueError('sgo event identity')
    if type(limit) is not int or not 1 <= limit <= MAX_ROWS:
        raise ValueError('sgo history read capacity')
    return db.execute('''SELECT kind,identity,revision,archived_at,facts
        FROM current_sgo_history WHERE event_id=%s
        ORDER BY archived_at,kind,identity,revision LIMIT %s''', (event_id, limit)).fetchall()


def prepare_page(page):
    """Capture all bookmaker originals, including books not executable in Predict."""
    if not isinstance(page.receipt_sha256, str) or not re.fullmatch('[0-9a-f]{64}', page.receipt_sha256):
        raise ValueError('sgo reference receipt identity')
    events = {event['event_id']: event for event in page.events}
    if len(page.quotes) > MAX_ROWS or len(events) != len(page.events):
        raise ValueError('sgo reference page capacity or identity')
    rows, ids = [], set()
    for quote in page.quotes:
        event = events[quote['event_id']]
        row_id = quote_identity(quote['event_id'], quote['venue'], quote['odd_id'], quote['line'])
        if row_id in ids:
            raise ValueError('ambiguous repeated SGO book/side/line')
        ids.add(row_id)
        facts = dict(provider='sportsgameodds', event_id=quote['event_id'],
                     aliases=event['aliases'], league=quote['league'], teams=event['teams'],
                     starts_at=event['starts_at'], phase=quote['phase'], event_status=event['status'],
                     period=quote['period'], market=quote['market'], side=quote['side'],
                     odd_id=quote['odd_id'], opposing_odd_id=quote['opposing_odd_id'],
                     venue=quote['venue'], line=quote['line'], price_american=quote['price_american'],
                     available=quote['available'], provider_available=quote['provider_available'],
                     unavailable_reason=quote['unavailable_reason'], source_at=quote['source_at'],
                     source_at_original=quote['source_at_original'], received_at=quote['received_at'],
                     receipt_sha256=page.receipt_sha256, fair=quote['fair'], settlement='unverified')
        for field in ('consensus', 'bookmaker_market_link', 'alternate', 'partition'):
            if field in quote:
                facts[field] = quote[field]
        revision = hashed({k: v for k, v in facts.items() if k not in ('received_at', 'receipt_sha256')})
        rows.append(dict(id=row_id, event_id=quote['event_id'], bookmaker_id=quote['venue'],
                         source_order=str(exact_time(quote['source_at'])) if quote['source_at'] else None,
                         received_order=str(exact_time(quote['received_at'])),
                         expires_at=sgo_working_expiry(event['starts_at'], quote['received_at']).isoformat(),
                         revision=revision, facts=facts))
    if len(encoded(rows)) > MAX_BYTES:
        raise ValueError('sgo reference page byte capacity')
    return rows


def upsert_rows(db, rows):
    """Order and write rows in the caller's transaction, without any withdrawal."""
    if not isinstance(rows, list) or len(rows) > MAX_ROWS or len(encoded(rows)) > MAX_BYTES:
        raise ValueError('sgo reference page capacity')
    if not rows:
        return 0
    identities = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'event_id', 'bookmaker_id', 'source_order', 'received_order', 'expires_at', 'revision', 'facts'}:
            raise ValueError('sgo reference row shape')
        facts = row['facts']
        if not isinstance(facts, dict) or facts.get('provider') != 'sportsgameodds' or facts.get('settlement') != 'unverified':
            raise ValueError('sgo reference provenance')
        if facts.get('event_id') != row['event_id'] or facts.get('venue') != row['bookmaker_id']:
            raise ValueError('sgo reference identity')
        if type(facts.get('available')) is not bool or type(facts.get('provider_available')) is not bool:
            raise ValueError('sgo reference availability')
        if not isinstance(facts.get('receipt_sha256'), str) or not re.fullmatch('[0-9a-f]{64}', facts['receipt_sha256']):
            raise ValueError('sgo reference receipt')
        if row['id'] != quote_identity(row['event_id'], row['bookmaker_id'], facts['odd_id'], facts['line']):
            raise ValueError('sgo reference identity')
        if row['id'] in identities:
            raise ValueError('sgo duplicate reference')
        identities.add(row['id'])
        if row['revision'] != hashed({k: v for k, v in facts.items() if k not in ('received_at', 'receipt_sha256')}):
            raise ValueError('sgo reference revision')
        if row['source_order'] != (str(exact_time(facts['source_at'])) if facts['source_at'] else None) or row['received_order'] != str(exact_time(facts['received_at'])):
            raise ValueError('sgo reference clocks')
        expected_expiry = sgo_working_expiry(facts['starts_at'], facts['received_at'])
        if stamp(row['expires_at']) != expected_expiry:
            raise ValueError('sgo reference retention')
    db.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
    # Visibility can suppress a superseded/omitted line while its canonical
    # revision remains current. Reappearance must replace that physical head,
    # not insert a second current revision for the same identity.
    previous = {r['id']: r for r in db.execute(
        'SELECT id,event_id,revision,facts FROM sgo_quote_revision WHERE is_current AND id=ANY(%s)', (list(identities),)).fetchall()}
    growth = len(rows) - len(previous)
    # The writer lock protects membership. Replacing known identities cannot
    # increase the bounded population; only growth needs a global count.
    if growth:
        total = db.execute('SELECT count(*) AS n FROM sgo_quote_revision WHERE is_current').fetchone()['n']
        if total + growth > MAX_CURRENT_ROWS:
            raise ValueError('sgo reference storage capacity')
    return advance_quotes(db, rows, previous)


QUOTE_COLUMNS = 'id,event_id,bookmaker_id,source_order,received_order,expires_at,revision,facts'
QUOTE_INPUT = '''jsonb_to_recordset(%s) AS i(id text,event_id text,bookmaker_id text,
    source_order numeric,received_order numeric,expires_at timestamptz,revision text,facts jsonb)'''


def retain_repeated_closure_receipts(db, rows):
    """Record later closures without replacing the original quote receipt."""
    from app.collection.sportsgameodds_current_rows import CURRENT_VENUES

    closures = [dict(id=row['id'], revision=row['revision'], received_order=row['received_order'])
                for row in rows if row['bookmaker_id'] in CURRENT_VENUES and row['source_order'] is not None
                and not row['facts']['available']
                and (not row['facts']['provider_available'] or row['facts']['price_american'] is not None)]
    if closures:
        db.execute('''UPDATE sgo_quote_revision q SET closure_received_order=i.received_order
            FROM jsonb_to_recordset(%s) AS i(id text,revision text,received_order numeric)
            WHERE (q.id,q.revision)=(i.id,i.revision) AND q.is_current
              AND q.source_order<=i.received_order
              AND i.received_order>COALESCE(q.closure_received_order,q.received_order)''', (Jsonb(closures),))


def advance_quotes(db, rows, previous):
    """Advance the existing reference winner without rewriting its source body."""
    from app.collection.sportsgameodds_current_rows import CURRENT_VENUES

    retain_repeated_closure_receipts(db, rows)
    # Preserve the old comparison rules, including availability closing at the
    # same source clock. Offer ordering remains a separate consumer of this data.
    eligible = db.execute(f'''SELECT i.id,i.revision
        FROM {QUOTE_INPUT}
        LEFT JOIN sgo_quote_revision q ON q.id=i.id AND q.is_current
        WHERE q.id IS NULL OR (q.revision<>i.revision AND (
              (i.source_order IS NOT NULL AND q.source_order IS NULL)
              OR i.source_order>q.source_order
              OR (i.source_order IS NULL AND q.source_order IS NULL AND i.received_order>q.received_order)
              OR (i.source_order=q.source_order AND i.received_order>=q.received_order
                  AND i.facts->>'available'='false' AND q.facts->>'available'='true')
        )) OR (q.revision=i.revision AND i.received_order>=q.received_order
              AND ((i.expires_at>q.expires_at AND q.expires_at<to_timestamp(i.received_order)+interval '2 days')
                   OR i.expires_at<q.expires_at-interval '1 day'))''',
        (Jsonb(rows),)).fetchall()
    if not eligible:
        return 0
    selected_ids = {r['id'] for r in eligible}
    selected = [row for row in rows if row['id'] in selected_ids]
    replaced = [previous[row['id']] for row in selected
                if row['id'] in previous and previous[row['id']]['revision'] != row['revision']]
    if replaced:
        db.execute('UPDATE sgo_quote_revision SET is_current=false WHERE id=ANY(%s) AND is_current',
                   ([r['id'] for r in replaced],))
    # A previously staged losing revision may now win a new receipt. Keep the
    # incoming head receipt exactly as the old writer did, without changing the
    # revision's source price. Offer receipts are stored with their own links.
    db.execute(f'''INSERT INTO sgo_quote_revision AS q ({QUOTE_COLUMNS},is_current)
        SELECT i.*,true FROM {QUOTE_INPUT}
        ON CONFLICT(id,revision) DO UPDATE SET is_current=true,
            source_order=CASE WHEN q.is_current THEN q.source_order ELSE excluded.source_order END,
            received_order=CASE WHEN q.is_current THEN q.received_order ELSE excluded.received_order END,
            closure_received_order=CASE
                WHEN q.is_current THEN q.closure_received_order
                WHEN q.bookmaker_id=ANY(%s) AND q.facts->'available'='false'::jsonb
                    AND (q.facts->'provider_available'='false'::jsonb OR q.facts->>'price_american' IS NOT NULL)
                    AND q.source_order<=COALESCE(q.closure_received_order,q.received_order)
                    AND excluded.received_order<COALESCE(q.closure_received_order,q.received_order)
                THEN COALESCE(q.closure_received_order,q.received_order)
                END,
            expires_at=excluded.expires_at,
            facts=CASE WHEN q.is_current THEN q.facts ELSE excluded.facts END''', (Jsonb(selected), sorted(CURRENT_VENUES)))
    archive_revisions(db, 'reference', replaced)
    if odds_archive.enabled():
        with odds_archive.capture(db) as archive:
            archive.extend(('sportsgameodds', odds_archive.sgo_quote, (row,previous.get(row['id'])), {})
                           for row in selected)
    return len(selected)


def stage_offer_quotes(db, rows, links):
    """Persist offer-selected revisions that are not the reference winner."""
    if not links:
        return
    ids = {identity for identity, _ in links.values()}
    selected = [row for row in rows if row['id'] in ids]
    db.execute(f'''INSERT INTO sgo_quote_revision({QUOTE_COLUMNS},is_current)
        SELECT i.*,false FROM {QUOTE_INPUT}
        ON CONFLICT(id,revision) DO NOTHING''', (Jsonb(selected),))


def withdraw_current_offers(db, rows, links):
    """Apply accepted, exact closures even when the page supplied no price."""
    from app.collection.sportsgameodds_current_rows import CURRENT_VENUES

    ids = {row['id'] for row in rows if row['bookmaker_id'] in CURRENT_VENUES and not row['facts']['available']}
    ids.update(identity for identity, _ in links.values())
    if not ids:
        return 0
    return db.execute('''UPDATE current_offer_storage o
        SET facts=jsonb_set(o.facts,'{state}','"unavailable"'::jsonb),
            revision=encode(sha256(convert_to(o.revision||closure.revision,'UTF8')),'hex')
        FROM sgo_quote_revision closure
        WHERE closure.id=ANY(%s) AND closure.is_current AND o.sgo_quote_id=closure.id
          AND o.facts->>'state'='available' AND closure.facts->'available'='false'::jsonb
          AND (closure.facts->'provider_available'='false'::jsonb
               OR closure.facts->>'price_american' IS NOT NULL)
          AND closure.source_order<=COALESCE(closure.closure_received_order,closure.received_order)
          AND (closure.source_order>o.source_order OR
               (closure.source_order=o.source_order
                AND COALESCE(closure.closure_received_order,closure.received_order)>=o.received_order))''',
        (sorted(ids),)).rowcount


def apply_event_lifecycle(db, frames, references, records):
    """Apply sporting status before admitting execution prices under the writer lock."""
    from app.collection.sportsgameodds_current_rows import event_record
    from app.comparison.game_phase import PREGAME_SPORTSBOOK_SECONDS, sgo_event_status, sporting_phase
    from app.normalization.college_registry import sgo_registry
    from .current_rows import event_id
    from .schedule_metadata import choose, witness

    terminal_states = {'cancelled', 'final', 'suspended'}
    candidates = {frame['event_id']: frame['facts'] for frame in frames}
    terminal = {key for key, frame in candidates.items() if sporting_phase({
        'status': sgo_event_status((frame.get('event_context') or {}).get('status') or {})
    })['state'] in terminal_states}
    if not candidates:
        return 0, records

    previous = db.execute("""SELECT e.id,e.facts, f.event_id, f.facts->>'receipt_sha256' AS receipt
            FROM current_sgo_event_frame f LEFT JOIN current_event e
              ON e.native_event_id=f.event_id AND e.provider='sportsgameodds'
            WHERE f.event_id=ANY(%s) AND (f.event_id=ANY(%s) OR e.facts ? 'sgo_closed_at'
              OR e.facts#>>'{status,status}' IN ('cancelled','suspended','delayed') OR e.facts#>>'{status,ended}'='true'
              OR e.scheduled_start::timestamptz <> (f.facts->>'starts_at')::timestamptz
              OR (f.facts#>>'{event_context,status,live}'='true' AND e.facts#>>'{status,live}' IS DISTINCT FROM 'true'))""",
            (sorted(candidates), sorted(terminal))).fetchall()
    if not previous:
        return 0, records

    # A receipt can repeat an old price. Reopening requires a fresh offered
    # price whose provider clock is strictly later than the closure witness.
    blocked = set(terminal)
    cutoffs = {}
    sources = {}
    affected = {row['event_id'] for row in previous}
    for row in references:
        fact = row['facts']
        if (row['event_id'] in affected and fact.get('available') and fact.get('source_at')
                and fact.get('period') == 'game'):
            source_at = stamp(fact['source_at'])
            age = (stamp(fact['received_at']) - source_at).total_seconds()
            if 0 <= age < PREGAME_SPORTSBOOK_SECONDS:
                sources[row['event_id']] = max(sources.get(row['event_id'], source_at), source_at)

    changed = 0
    for row in previous:
        key = row['event_id']
        frame = candidates[key]
        prior = row['facts']
        context = frame.get('event_context') or {}
        changed_schedule = bool(prior and stamp(frame['starts_at']) != stamp(prior['scheduled_start']))
        started = sgo_event_status(context.get('status') or {})
        left_pregame = started['live'] or started['status'] == 'started'
        closed = bool(prior and sporting_phase(prior)['state'] in terminal_states)
        metadata = witness(prior) if closed else None
        cutoff = (prior or {}).get('sgo_closed_at') or (metadata or {}).get('received_at')
        if cutoff:
            cutoffs[key] = cutoff
        if closed:
            blocked.add(key)
        if row['receipt'] != frame['receipt_sha256'] or not frame.get('event_context'):
            continue
        reopening = closed and cutoff and key in sources and sources[key] > stamp(cutoff)
        if key not in terminal and not (reopening or not closed and (changed_schedule or left_pregame)):
            continue
        observation = event_record(dict(frame['event_context'], event_id=key, starts_at=frame['starts_at']),
                                   frame['receipt_sha256'], frame['received_at'], sgo_registry())
        if prior and any(observation[field] != prior[field] for field in ('competition', 'home', 'away')):
            continue
        if choose(prior, observation, observed_at=frame['received_at']) is not observation:
            continue
        if key in terminal:
            cutoff = frame['received_at']
        else:
            blocked.discard(key)
        if cutoff:
            observation['sgo_closed_at'] = cutoff
            cutoffs[key] = cutoff
        eid = row['id'] or event_id('sportsgameodds', key)
        if prior:
            start = observation['scheduled_start']
            new_end = stamp(start) + (timedelta(hours=24) if key in terminal or left_pregame else timedelta(0))
            db.execute('''UPDATE current_event SET facts=%s,revision=%s,scheduled_start=%s,
                          expires_order=CASE WHEN scheduled_start=%s THEN greatest(expires_order,%s) ELSE %s END
                          WHERE id=%s''',
                       (Jsonb(observation), hashed(observation), start, start, exact_time(new_end.isoformat()), exact_time(new_end.isoformat()), eid))
        else:
            start = observation['scheduled_start']
            db.execute("""INSERT INTO current_event VALUES (%s,'sportsgameodds',%s,%s,%s,%s,%s,%s)""",
                       (eid, key, observation['competition'], start, exact_time((stamp(start) + timedelta(hours=24)).isoformat()),
                        Jsonb(observation), hashed(observation)))
        changed += 1
        if key in terminal:
            changed += db.execute("""UPDATE current_offer_storage o
                SET facts=jsonb_set(o.facts,'{state}','"unavailable"'::jsonb),
                    revision=encode(sha256(convert_to(o.revision||%s,'UTF8')),'hex')
                FROM current_contract c WHERE c.id=o.contract_id AND c.event_id=%s
                  AND o.received_order<=%s AND o.facts->>'state'='available'""",
                (frame['receipt_sha256'], eid, exact_time(cutoff))).rowcount

    admitted = []
    for record in records:
        quote = record['quote']
        key = quote['source']['native_event_id']
        if key in blocked:
            continue
        if cutoff := cutoffs.get(key):
            clocks = quote['times']
            at = clocks['source_at']
            if not at or not stamp(cutoff) < stamp(at) <= stamp(clocks['received_at']):
                continue
            record = dict(record, event=dict(record['event'], sgo_closed_at=cutoff))
        admitted.append(record)
    return changed, admitted


def read_event(db, event_id, *, limit=MAX_ROWS, bookmakers=None, source_since=None):
    """Read one bounded event within the caller's coherent snapshot transaction."""
    if not isinstance(event_id, str) or not event_id or len(event_id) > 256:
        raise ValueError('sgo event identity')
    if type(limit) is not int or not 1 <= limit <= MAX_ROWS:
        raise ValueError('sgo read capacity')
    params = (event_id,) if bookmakers is None else (event_id, list(bookmakers))
    book_filter = '' if bookmakers is None else ' AND bookmaker_id=ANY(%s)'
    source_filter = '' if source_since is None else ' AND source_order >= %s'
    if source_since is not None:
        params += (exact_time(source_since.isoformat()),)
    rows = db.execute('SELECT id,revision,facts FROM current_sgo_reference WHERE event_id=%s'
                      + book_filter + source_filter + ' ORDER BY id LIMIT %s', (*params, limit + 1)).fetchall()
    if len(rows) > limit:
        raise ValueError('sgo event exceeds read capacity')
    return rows


class EventInputs:
    """Batch exact sportsbook evidence within one repeatable-read snapshot."""

    def __init__(self, db):
        self.db = db
        self.schedule = None
        self.retained_schedule = {}
        self.event_frames = {}
        self.quote_reads = {}

    def occurrences(self, at, *, starts=()):
        """Find SGO schedules in this read even for games with sportsbook prices alone."""
        starts = set(starts)
        if not starts:
            if self.schedule is None:
                self.schedule = self._read_schedule(
                    "scheduled_start::timestamptz BETWEEN %s AND %s",
                    "(facts->>'starts_at')::timestamptz BETWEEN %s AND %s AND received_order <= %s",
                    (at - timedelta(hours=24), at + timedelta(hours=72), at, at + timedelta(hours=72),
                     exact_time(at.isoformat())),
                )
            return self.schedule
        missing = sorted(starts - self.retained_schedule.keys())
        if missing:
            self.retained_schedule.update((start, {}) for start in missing)
            matching = self._read_schedule(
                "scheduled_start::timestamptz=ANY(%s)",
                "expires_at >= %s AND (facts->>'starts_at')::timestamptz=ANY(%s)",
                (missing, missing[0] + timedelta(days=1), missing),
            )
            for occurrence, candidates in matching.items():
                if occurrence[1] in self.retained_schedule:
                    self.retained_schedule[occurrence[1]][occurrence] = candidates
        return {occurrence: candidates for start in starts
                for occurrence, candidates in self.retained_schedule[start].items()}

    def _read_schedule(self, event_filter, frame_filter, params):
        # Seed from scoped schedules or indexed receipt/expiry clocks, then
        # include the exact counterpart even when its kickoff conflicts.
        rows = self.db.execute('''WITH events AS (
                SELECT native_event_id AS event_id FROM current_event WHERE provider='sportsgameodds' AND '''
            + event_filter + ''' UNION SELECT event_id FROM current_sgo_event_frame WHERE ''' + frame_filter + '''
            )
            SELECT events.event_id, e.competition, e.scheduled_start,
                   e.facts->>'home' AS home, e.facts->>'away' AS away,
                   (e.facts->'schedule_conflict' NOT IN ('null','false','{}')
                    OR e.facts->'occurrence_conflict' NOT IN ('null','false','{}')
                    OR e.facts->'conflicting_duplicate' NOT IN ('null','false','{}')
                    OR e.facts->>'replacement_game_id' IS NOT NULL) AS conflicted,
                   f.facts->>'starts_at' AS starts_at, f.facts->>'receipt_sha256' AS frame, f.received_order,
                   f.facts#>>'{event_context,league}' AS league, f.facts#>'{event_context,teams}' AS teams,
                   f.facts#>>'{event_context,phase}' AS phase, f.facts#>'{event_context,status}' AS status
            FROM events LEFT JOIN current_event e
                ON e.provider='sportsgameodds' AND e.native_event_id=events.event_id
            LEFT JOIN current_sgo_event_frame f USING(event_id)''', params).fetchall()
        schedule = schedule_occurrences(rows)
        starts = sorted({key[1] for key, candidates in schedule.items()
                         if key[0] == 'MLB' and any(row['valid'] for row in candidates.values())})
        if starts:
            # SGO frames do not carry a reviewed game number. One frame
            # cannot identify which leg of a same-start doubleheader it prices.
            collisions = self.db.execute('''SELECT scheduled_start::timestamptz AS start,
                       facts->>'home' AS home, facts->>'away' AS away
                FROM current_event WHERE provider IN ('kalshi','polymarket_us') AND competition='MLB'
                  AND scheduled_start::timestamptz=ANY(%s) AND facts->>'game_number' IN ('1','2')
                GROUP BY 1,2,3 HAVING count(DISTINCT facts->>'game_number') > 1''', (starts,)).fetchall()
            for row in collisions:
                for candidate in schedule.get(('MLB', row['start'], row['home'], row['away']), {}).values():
                    candidate['valid'] = False
        return schedule

    def frames(self, event_ids):
        ids = sorted(set(event_ids))
        missing = [event_id for event_id in ids if event_id not in self.event_frames]
        if missing:
            self.event_frames.update(dict.fromkeys(missing))
            for row in self.db.execute(
                'SELECT event_id,facts FROM current_sgo_event_frame WHERE event_id=ANY(%s)',
                (missing,),
            ):
                self.event_frames[row['event_id']] = row
        return {event_id: self.event_frames[event_id] for event_id in ids
                if self.event_frames[event_id] is not None}

    def quotes(self, event_ids, *, bookmakers=None, source_since=None, game_markets=False, limit=MAX_ROWS):
        if type(limit) is not int or not 1 <= limit <= MAX_ROWS:
            raise ValueError('sgo read capacity')
        ids = sorted(set(event_ids))
        books = None if bookmakers is None else tuple(sorted(set(bookmakers)))
        since = None if source_since is None else exact_time(source_since.isoformat())
        cached = self.quote_reads.setdefault((books, since, game_markets, limit), {})
        missing = [event_id for event_id in ids if event_id not in cached]
        for offset in range(0, len(missing), 16):
            batch = missing[offset:offset + 16]
            books_sql = '' if books is None else ' AND bookmaker_id=ANY(%s)'
            clock_sql = '' if since is None else ' AND source_order >= %s'
            market_sql = (""" AND facts->>'period'='game'
                            AND facts->>'market' IN ('moneyline','spread','total')
                            AND source_order IS NOT NULL""" if game_markets else '')
            params = [batch]
            if books is not None:
                params.append(list(books))
            if since is not None:
                params.append(since)
            params.append(limit + 1)
            results = {event_id: [] for event_id in batch}
            for row in self.db.execute(
                '''SELECT events.event_id,q.id,q.revision,q.facts
                   FROM unnest(%s::text[]) AS events(event_id)
                   CROSS JOIN LATERAL (
                       SELECT id,revision,facts FROM current_sgo_reference
                       WHERE event_id=events.event_id'''
                + books_sql + clock_sql + market_sql + ' ORDER BY id LIMIT %s) q',
                params,
            ):
                results[row['event_id']].append(row)
            cached.update((event_id, rows if len(rows) <= limit else None)
                          for event_id, rows in results.items())
        return {event_id: cached[event_id] for event_id in ids if cached[event_id] is not None}


def schedule_occurrences(rows):
    """Index exact schedule occurrences while retaining blockers for ambiguous joins."""
    from app.collection.sportsgameodds_current_rows import participant_ids
    from app.normalization.college_registry import sgo_registry
    from .sgo_schedule_review import frame_start

    registry = sgo_registry()
    schedule = {}
    for row in rows:
        event = row['event_id']
        projected = ((row['competition'], stamp(row['scheduled_start']), row['home'], row['away'])
                     if row['competition'] and row['scheduled_start'] and row['home'] and row['away'] else None)
        observed = None
        if row['teams'] and row['league'] and row['starts_at'] and row['frame']:
            try:
                teams = participant_ids(row['teams'], row['league'], event, registry)
                if teams['home'] != teams['away']:
                    start = frame_start(event, row['league'], row['teams'], row['starts_at'], row['frame'], at=now())
                    observed = (row['league'], stamp(start), teams['home'], teams['away'])
            except (KeyError, TypeError, ValueError):
                pass
        # A new scoped alias can canonicalize a prior provider-local ID. An
        # existing different canonical team or kickoff is a conflicting witness.
        compatible = not projected or bool(observed and projected[:2] == observed[:2] and all(
            old in (new, f'sportsgameodds:{row["league"]}:{event}:{role}')
            for role, old, new in zip(('home', 'away'), projected[2:], observed[2:], strict=True)))
        legacy = (projected and row['frame'] and not row['league'] and row['starts_at']
                  and projected[1] == stamp(row['starts_at']))
        candidate = dict(row, valid=bool(not row['conflicted'] and (observed and compatible or legacy)),
                         occurrence=observed)
        for occurrence in {projected, observed} - {None}:
            schedule.setdefault(occurrence, {})[event] = candidate
    return schedule


def expiry_filter(at, include_legacy):
    if not include_legacy:
        return 'expires_at < %s', (at,)
    # Previously written heads have a 14-day schedule anchor. Use its existing
    # expiry index to bound the candidate scan, and confirm both original clocks.
    return '''expires_at < %s OR (expires_at < %s::timestamptz + interval '13 days'
              AND (facts->>'starts_at')::timestamptz < %s::timestamptz - interval '1 day'
              AND received_order < %s)''', (at, at, at, exact_time(at)-21600)


def prune(db, *, at, limit=PRUNE_BATCH, include_legacy=False):
    """Remove only expired current reference facts; never touches audit or controls."""
    if type(limit) is not int or not 1 <= limit <= PRUNE_BATCH:
        raise ValueError('sgo prune capacity')
    stamp(at)
    db.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
    expiry, bounds = expiry_filter(at, include_legacy)
    expired = db.execute(f'''SELECT id,event_id,revision,facts FROM current_sgo_reference
        WHERE ({expiry}) AND NOT EXISTS (
            SELECT 1 FROM current_event e WHERE e.provider='sportsgameodds'
                AND e.native_event_id=current_sgo_reference.event_id AND e.scheduled_start::timestamptz > %s)
        ORDER BY expires_at,id LIMIT %s''', (*bounds, at, limit)).fetchall()
    archive_revisions(db, 'reference', expired)
    retired = db.execute('UPDATE sgo_quote_revision SET is_current=false WHERE id=ANY(%s) AND is_current',
                         ([row['id'] for row in expired],)).rowcount
    db.execute('''DELETE FROM sgo_quote_revision q USING (
        SELECT r.id,r.revision FROM sgo_quote_revision r WHERE NOT r.is_current AND NOT EXISTS (
            SELECT 1 FROM current_offer_storage o WHERE o.sgo_quote_id=r.id AND o.sgo_quote_revision=r.revision)
        LIMIT %s
    ) stale WHERE q.id=stale.id AND q.revision=stale.revision''', (limit,))
    return retired


MAX_FRAMES = 25000
MAX_FRAME_TOTAL_BYTES = 128 * 1024 * 1024


def prepare_frames(page, rows):
    """Bind row revisions co-observed in each event's actual received page."""
    if not isinstance(rows, list) or len(rows) > MAX_ROWS or len(encoded(rows)) > MAX_BYTES:
        raise ValueError('sgo frame page capacity')
    expected_rows = prepare_page(page)
    if {(r['id'], r['revision']) for r in rows} != {(r['id'], r['revision']) for r in expected_rows} or len(rows) != len(expected_rows):
        raise ValueError('sgo frame observations incomplete')
    events = {event['event_id']: event for event in page.events}
    if len(events) != len(page.events) or len(events) > 100:
        raise ValueError('sgo frame event scope')
    members = {event_id: [] for event_id in events}
    seen = set()
    for row in rows:
        if row['event_id'] not in events or row['facts']['receipt_sha256'] != page.receipt_sha256 or row['id'] in seen:
            raise ValueError('sgo frame input identity')
        seen.add(row['id'])
        members[row['event_id']].append([row['id'], row['revision']])
    frames = []
    for event_id, event in events.items():
        facts = dict(provider='sportsgameodds', event_id=event_id,
                     receipt_sha256=page.receipt_sha256, received_at=event['received_at'],
                     starts_at=event['starts_at'], members=sorted(members[event_id]),
                     event_context=dict(league=event['league'], phase=event['phase'], teams=event['teams'],
                                        status=event['status'], scores=event.get('scores', {}),
                                        game_results=event.get('game_results', {})))
        for field in ('bookmaker_event_links', 'previous_starts_at', 'starts_at_original'):
            if event.get(field):
                facts['event_context'][field] = event[field]
        frames.append(dict(event_id=event_id, received_order=str(exact_time(event['received_at'])),
                           expires_at=sgo_working_expiry(event['starts_at'], event['received_at']).isoformat(),
                           facts=facts))
    if len(encoded(frames)) > MAX_BYTES:
        raise ValueError('sgo frame page byte capacity')
    return frames


def upsert_frames(db, frames):
    """Write only newer page witnesses under the source-ingress transaction."""
    if not isinstance(frames, list) or len(frames) > 100 or len(encoded(frames)) > MAX_BYTES:
        raise ValueError('sgo frame page capacity')
    ids = set()
    for frame in frames:
        if not isinstance(frame, dict) or set(frame) != {'event_id', 'received_order', 'expires_at', 'facts'}:
            raise ValueError('sgo frame shape')
        facts = frame['facts']
        required = {'provider', 'event_id', 'receipt_sha256', 'received_at', 'starts_at', 'members'}
        if not isinstance(facts, dict) or not required <= set(facts) or set(facts) - required - {'event_context'}:
            raise ValueError('sgo frame facts')
        context = facts.get('event_context')
        context_required = {'league', 'phase', 'teams', 'status', 'scores', 'game_results'}
        if context is not None and (not isinstance(context, dict) or not context_required <= set(context)
                or set(context) - context_required - {'bookmaker_event_links', 'previous_starts_at', 'starts_at_original'}
                or len(encoded(context)) > 8192):
            raise ValueError('sgo event context invalid')
        if (facts['provider'] != 'sportsgameodds' or facts['event_id'] != frame['event_id']
                or not isinstance(frame['event_id'], str) or not frame['event_id'] or len(frame['event_id']) > 256
                or frame['event_id'] in ids):
            raise ValueError('sgo frame identity')
        ids.add(frame['event_id'])
        if not isinstance(facts['receipt_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', facts['receipt_sha256']):
            raise ValueError('sgo frame receipt')
        if not isinstance(facts['members'], list) or len(facts['members']) > MAX_ROWS:
            raise ValueError('sgo frame members')
        if any(not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(x, str) or not re.fullmatch('[0-9a-f]{64}', x) for x in pair) for pair in facts['members']):
            raise ValueError('sgo frame members')
        if len({pair[0] for pair in facts['members']}) != len(facts['members']):
            raise ValueError('sgo duplicate frame member')
        if frame['received_order'] != str(exact_time(facts['received_at'])):
            raise ValueError('sgo frame clock')
        expiry = sgo_working_expiry(facts['starts_at'], facts['received_at'])
        if stamp(frame['expires_at']) != expiry:
            raise ValueError('sgo frame retention')
    db.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
    existing = db.execute('SELECT count(*) AS n,COALESCE(sum(payload_bytes),0) AS bytes FROM current_sgo_event_frame WHERE event_id=ANY(%s)', (list(ids),)).fetchone()
    total = db.execute('SELECT count(*) AS n,COALESCE(sum(payload_bytes),0) AS bytes FROM current_sgo_event_frame').fetchone()
    incoming_bytes = sum(len(encoded(frame['facts'])) for frame in frames)
    if total['n'] + len(frames) - existing['n'] > MAX_FRAMES or total['bytes'] + incoming_bytes - existing['bytes'] > MAX_FRAME_TOTAL_BYTES:
        raise ValueError('sgo frame storage capacity')
    previous = {r['event_id']: r for r in db.execute(
        'SELECT event_id,facts FROM current_sgo_event_frame WHERE event_id=ANY(%s)', (list(ids),)).fetchall()}
    replaced = []
    changed = 0
    for frame in frames:
        result = db.execute('''INSERT INTO sgo_event_evidence (kind,event_id,received_order,expires_at,payload_bytes,facts)
            VALUES ('frame',%s,%s,%s,%s,%s) ON CONFLICT (kind,event_id) DO UPDATE
            SET received_order=EXCLUDED.received_order,expires_at=EXCLUDED.expires_at,payload_bytes=EXCLUDED.payload_bytes,facts=EXCLUDED.facts
            WHERE EXCLUDED.received_order > sgo_event_evidence.received_order''',
            (frame['event_id'], frame['received_order'], frame['expires_at'], len(encoded(frame['facts'])), Jsonb(frame['facts'])))
        changed += result.rowcount
        if result.rowcount and frame['event_id'] in previous:
            replaced.append(previous[frame['event_id']])
    archive_revisions(db, 'frame', replaced)
    return changed


def read_event_frame(db, event_id):
    """Read latest frame in the caller's repeatable-read reference snapshot."""
    if not isinstance(event_id, str) or not event_id or len(event_id) > 256:
        raise ValueError('sgo event identity')
    return db.execute('SELECT facts FROM current_sgo_event_frame WHERE event_id=%s', (event_id,)).fetchone()


def backfill_prophetx(db, *, at):
    """Project retained ProphetX prices from exact SGO frames using original clocks."""
    from collections import defaultdict
    from app.collection.current_policy import aggregate_scope
    from app.collection.runtime_status import AUTHORITY_LOCK, read_runtime
    from app.collection.current_policy import aggregate_provider
    from app.collection.sportsgameodds_adapter import PROPHETX_BOOKMAKER_ID, Page
    from app.collection.sportsgameodds_current_rows import current_rows
    from .current_rows import CurrentRowStore, contract_id

    moment = stamp(at)
    with db.transaction():
        db.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
        db.execute('SELECT pg_advisory_xact_lock_shared(%s)', (AUTHORITY_LOCK,))
        owner = read_runtime(db)
        config = owner['config']
        if (not owner['active'] or owner.get('global_stopped')
                or {'sportsgameodds', 'prophetx'} & set(owner.get('paused_sources', ()))
                or aggregate_provider(config) != 'sportsgameodds' or not config.get('aggregate_enabled')):
            return 0
        rows = db.execute('''SELECT f.event_id,f.facts AS frame,q.id,q.revision,q.facts
            FROM current_sgo_event_frame f
            CROSS JOIN LATERAL jsonb_array_elements(f.facts->'members') AS m
            JOIN current_sgo_reference q ON (q.id,q.revision,q.event_id)=(m->>0,m->>1,f.event_id)
            WHERE q.bookmaker_id=%s AND q.facts->>'receipt_sha256'=f.facts->>'receipt_sha256'
              AND q.received_order=f.received_order AND q.facts->>'price_american' IS NOT NULL
              AND f.received_order<=%s
              AND f.expires_at>%s AND (f.facts->>'starts_at')::timestamptz BETWEEN %s AND %s
              AND q.facts->>'league'=ANY(%s) AND q.facts->>'market'=ANY(%s)
            ORDER BY f.event_id,q.id LIMIT %s''',
            (PROPHETX_BOOKMAKER_ID, exact_time(at), moment, moment-timedelta(hours=24), moment+timedelta(hours=72),
             aggregate_scope(config), config['families'], MAX_ROWS+1)).fetchall()
        if len(rows) > MAX_ROWS:
            raise ValueError('sgo ProphetX backfill capacity')
        by_event = defaultdict(list)
        for row in rows:
            by_event[row['event_id']].append(row)
        records, links, frames = [], {}, []
        for event_id, members in by_event.items():
            frame = members[0]['frame']
            context = frame.get('event_context')
            if not context or any(context['status'].get(key) for key in ('ended', 'completed', 'cancelled')):
                continue
            event = dict(context, event_id=event_id, starts_at=frame['starts_at'], received_at=frame['received_at'],
                         aliases=members[0]['facts']['aliases'])
            page = Page((event,), tuple(row['facts'] for row in members), None, frame['receipt_sha256'])
            projected, _ = current_rows(page, page.receipt_sha256)
            refs = {row['id']: row for row in members}
            links.update((contract_id(record), offer_quote_link(record, refs)) for record in projected)
            records.extend(projected)
            frames.append(dict(event_id=event_id, facts=frame))
        changed, admitted = apply_event_lifecycle(db, frames, rows, records)
        return changed + CurrentRowStore(db).upsert_records(admitted, now=at, quote_links=links)


def prune_frames(db, *, at, limit=PRUNE_BATCH, include_legacy=False):
    if type(limit) is not int or not 1 <= limit <= PRUNE_BATCH:
        raise ValueError('sgo frame prune capacity')
    stamp(at)
    db.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK,))
    expiry, bounds = expiry_filter(at, include_legacy)
    expired = db.execute(f'''SELECT event_id,facts FROM current_sgo_event_frame
        WHERE ({expiry}) AND NOT EXISTS (
            SELECT 1 FROM current_event e WHERE e.provider='sportsgameodds'
                AND e.native_event_id=current_sgo_event_frame.event_id AND e.scheduled_start::timestamptz > %s)
        ORDER BY expires_at,event_id LIMIT %s''', (*bounds, at, limit)).fetchall()
    archive_revisions(db, 'frame', expired)
    return db.execute("DELETE FROM sgo_event_evidence WHERE kind='frame' AND event_id=ANY(%s)",
                      ([row['event_id'] for row in expired],)).rowcount
