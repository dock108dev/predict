"""Official candidates for the active pilot's independent shadow decision."""

from app.collection.native_trading_identity import link as link_game
from app.comparison.native_observation import adopt
from app.comparison.reference_scope import REQUEST_BOOKS
from app.storage import native_trading
from app.storage.sportsgameodds_reference import read_event
from app.storage.store import stamp

PREFIX = 'official:'
VENUES = ('novig', 'kalshi', 'polymarket_us', 'prophetx')


def plan(db, task, at, *, novig_event=None):
    """Start from the committed official catalog, including unresolved sides."""
    event, source = task['event'], task['source_event_id']
    starts = stamp(event['starts_at'])
    rows = db.execute('''SELECT id,record,book,game_link,published_at,snapshot_id
        FROM public.native_trading_offer
        WHERE league=%s AND published_at<=%s
          AND (game_link->>'sgo_event_id'=%s OR (starts_at=%s
               AND record#>>'{event,home}'=%s AND record#>>'{event,away}'=%s))
        ORDER BY venue, family, native_market_id, id''',
        (event['league'], at, source, starts, event['home'], event['away'])).fetchall()
    quotes = read_event(db, source, bookmakers=REQUEST_BOOKS)
    quotes = [row for row in quotes if stamp(row['facts']['received_at']) <= at
              and stamp(row['facts']['starts_at']) == starts]
    novig_events = {r['book']['event_id'] for r in rows if r['book']['venue'] == 'novig'}
    if novig_event:
        novig_events.add(novig_event)
    anchors = native_trading.anchors(db, at, novig_events=novig_events)
    return list(rows), anchors, quotes


def match(rows, discovered, anchors, quotes, task, at):
    event, source = task['event'], task['source_event_id']
    starts = stamp(event['starts_at'])
    records = {row['id']: dict(row, game_link=link_game(row['record']['event'], anchors, prior=row['game_link']))
               for row in rows}
    references = native_trading.reference_inputs(source, quotes, at)
    for cid, binding in discovered.items():
        record = binding['_record']
        prior = records.get(cid)
        linked = link_game(record['event'], anchors, prior=prior['game_link'] if prior else None)
        native_event = record['event']
        scoped = (stamp(native_event['scheduled_start']) == starts
                  and (native_event['home'], native_event['away']) == (event['home'], event['away']))
        if linked.get('sgo_event_id') != source and not scoped:
            continue
        fresh = {key: value for key, value in binding.items() if not key.startswith('_')}
        if prior:
            # Preserve the last admitted observation for ordering. Use its
            # original evidence if refreshed identity fails to acquire a book.
            records[cid] = dict(prior, terms=fresh, record=record, game_link=linked)
        else:
            records[cid] = dict(id=cid, record=record, game_link=linked, book=fresh,
                                published_at=None, snapshot_id=None)
    candidates = {}
    for row in records.values():
        record, link = row['record'], row['game_link']
        exact = (link['status'] == 'matched' and link['sgo_event_id'] == source
                 and stamp(link['sgo_start']) == starts)
        ref, valid_until, reason = None, None, None
        if exact:
            reference_record = dict(record, event=dict(record['event'], scheduled_start=event['starts_at']))
            ref, valid_until, reason = native_trading.reference(reference_record, link, references, at=at)
        candidates[PREFIX + row['id']] = dict(record=record, game_link=link, book=row['book'],
            reason=None if exact else link.get('reason') or 'sgo_schedule_revision_mismatch',
            reference=ref, reference_reason=reason, reference_valid_until=(valid_until.isoformat() if valid_until else None),
            catalog_snapshot_id=row['snapshot_id'],
            catalog_committed_at=(row['published_at'].isoformat() if row['published_at'] is not None else None),
            terms=row.get('terms', row['book']))
    return candidates


def prepare(candidates, *, cutoff, enabled):
    """Use the exact same market read and side validation as the frozen policy."""
    novig, exchanges, prophetx = {}, {}, set()
    for key, candidate in candidates.items():
        book = candidate['terms']
        venue = book['venue']
        if candidate['reason'] or not enabled(venue):
            continue
        if venue == 'prophetx':
            prophetx.add(book['event_id'])
        elif venue == 'novig':
            contract = book['contract']
            identity = {field: book[field] for field in ('event_id', 'market_id', 'outcome_id', 'opposite_outcome_id')}
            subjects = (candidate['record']['event'].get('native_role_evidence') or {}).get('subjects') or {}
            if set(subjects) != {'home', 'away'}:
                candidate['reason'] = 'novig_subject_roles_unverified'
                continue
            identity.update(available=True, phase='scheduled', phase_verified=True,
                starts_at=contract['starts_at'], league=contract['league'], family=contract['family'],
                selected_side=contract['selected_side'], signed_line=contract['signed_line'],
                subject_role_anchors=[dict(home_subject=subjects['home'], away_subject=subjects['away'])],
                identity_receipts=book['identity_receipts'], revision=book.get('binding_revision'),
                binding_method=book.get('binding_method'))
            novig[key] = identity, None
        elif book.get('route') and book.get('terms_valid_until') and stamp(book['terms_valid_until']) > cutoff:
            exchanges[key] = dict(book, reason=None, levels=[], receipts=[], complete=False)
            for field in ('received_at', 'source_at', 'sequence', 'valid_until', 'native_book'):
                exchanges[key].pop(field, None)
    return novig, exchanges, prophetx


def freeze(candidates, books, quotes, *, cutoff, gaps, enabled):
    """Keep the original observed book and clocks alongside its exact SGO audit."""
    output = {}
    for key, candidate in candidates.items():
        prior = candidate['book']
        venue = prior['venue']
        incoming = books.get(key)
        if incoming:
            incoming = {field: value for field, value in incoming.items() if not field.startswith('_')}
            if venue == 'novig':
                incoming.update(native_side=prior.get('native_side'), contract_id=key.removeprefix(PREFIX))
            book = adopt(prior, incoming) if prior.get('received_at') is not None else incoming
        else:
            book = prior
        reason = candidate['reason']
        if not enabled(venue):
            reason = 'source_paused'
        elif not reason and not book.get('reason') and not book.get('received_at'):
            reason = (incoming or {}).get('reason') or 'book_unobserved'
        elif not reason and not book.get('reason') and stamp(book['valid_until']) <= cutoff:
            reason = (incoming or {}).get('reason') or 'stale'
        elif not reason and incoming and book is prior and prior.get('reason') == 'book_unobserved':
            reason = incoming.get('reason')
        ref = candidate['reference']
        ref_reason = candidate['reference_reason']
        if ref and stamp(candidate['reference_valid_until']) <= cutoff:
            ref, ref_reason = None, 'reference_stale'
        output[key.removeprefix(PREFIX)] = dict({k: v for k, v in candidate.items() if k != 'terms'}, book=book, reason=reason,
            reference=ref, reference_reason=ref_reason,
            sgo_comparison=native_trading.audit(candidate['record'], book, quotes) if not candidate['reason'] else [],
            book_committed_at=candidate['catalog_committed_at'] if book is prior else None,
            attempted_book_reason=incoming.get('reason') if incoming else None)
    for venue in VENUES:
        if not enabled(venue):
            gaps[venue] = 'source_paused'
        elif not any(row['book']['venue'] == venue for row in output.values()):
            gaps.setdefault(venue, 'official_occurrence_unobserved')
    return dict(candidates=output, source_gaps=gaps)
