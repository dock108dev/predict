"""Exact Scanner witness for a complete possible-peer neighborhood."""

from collections import defaultdict

from app.storage.store import hashed
from .observation_publication import identity_index, neighborhood


def capture(db, event_ids, *, index=None, contracts=None):
    index = identity_index(db) if index is None else index
    selectors = dict(events=sorted(event_ids), occurrences=[], shared=[])
    members = neighborhood(index, selectors)
    ids = [row[0] for row in members]
    if contracts is not None:
        if len(contracts)!=1:
            raise ValueError('scanner_native_witness_contract_required')
        return _native_contracts(db, index, members, contracts)[contracts[0]]
    offers = db.execute('''SELECT c.id,c.venue,c.revision AS contract,o.revision AS offer,
        o.native_book_id,o.source_at::text,o.received_at::text,o.facts->'book_confirmation' AS confirmation
        FROM current_contract c LEFT JOIN current_offer o ON o.contract_id=c.id
        WHERE c.event_id=ANY(%s) ORDER BY c.id''', (ids,)).fetchall()
    books = db.execute('''SELECT venue,event_id,native_market_id,id FROM native_book_revision
        WHERE is_current AND event_id=ANY(%s) ORDER BY venue,event_id,native_market_id''', (ids,)).fetchall()
    # Matching uses all current candidate event facts. Dependency-only event
    # hashes omit provenance fields which still belong to an exact ticket.
    events = [[key, index['events'][key]['revision'], active] for key, _, active in members]
    sources = sorted({'pinnacle'} | {index['events'][key]['provider'] for key, _, _ in members}
                     | {row['venue'] for row in offers})
    statuses = db.execute('SELECT venue,state FROM current_source_status WHERE venue=ANY(%s) ORDER BY venue',
                          (sources,)).fetchall()
    fee_schedules = db.execute('SELECT venue,state FROM public_fee_schedule WHERE venue=ANY(%s) ORDER BY venue',
        ([key for key, venue in (('kalshi:exchange','kalshi'), ('polymarket_us:standard_sports','polymarket_us')) if venue in sources],)).fetchall()
    from app.fees.product_schedules import revision
    fees = [(row['venue'], revision(row['state'], publication=True)) for row in fee_schedules]
    return hashed([index['epoch'], events, offers, books, statuses, fees])


def native_witnesses(db, event_ids, contracts, *, index):
    members = neighborhood(index, dict(events=sorted(event_ids),occurrences=[],shared=[]))
    return _native_contracts(db,index,members,contracts)


def _native_contracts(db, index, members, contracts):
    """Keep all occurrence witnesses and the selected contracts' exact economics."""
    ids = [row[0] for row in members]
    offers = db.execute('''SELECT c.id,c.venue,c.facts->'comparison_source_metadata'->>'material_sha256' AS terms,
        c.facts->'selection' AS selection,c.facts->'market_identity' AS market,o.price_dependency AS offer,
        b.ladder_refs#>>ARRAY[c.native_outcome_id,'asks'] AS ladder_id,b.state,b.sync,b.quantity_units,b.is_current
        FROM current_contract_storage c
        JOIN current_offer_storage o ON o.contract_id=c.id
        JOIN native_book_revision b ON b.id=o.native_book_id
        WHERE c.id=ANY(%s) AND c.event_id=ANY(%s) AND c.active ORDER BY c.id''', (contracts,ids)).fetchall()
    events = [[key,index['events'][key]['dependency_revision'],active] for key,_,active in members]
    statuses = {row['venue']:row for row in db.execute('''SELECT venue,state->'state' state,state->'reason_code' reason
        FROM current_source_status WHERE venue=ANY(%s) ORDER BY venue''',
        (sorted({row['venue'] for row in offers}),)).fetchall()}
    fee_schedules = db.execute('''SELECT venue,state FROM public_fee_schedule
        WHERE venue IN ('kalshi:exchange','polymarket_us:standard_sports') ORDER BY venue''').fetchall()
    from app.fees.product_schedules import revision
    fees = [(row['venue'],revision(row['state'],publication=True)) for row in fee_schedules]
    by_id = {row['id']:row for row in offers}
    return {contract:hashed([index['epoch'],events,by_id.get(contract),
                statuses.get(by_id[contract]['venue']) if contract in by_id else None,fees])
            for contract in contracts}


def changed(db, witnesses):
    if not witnesses:
        return set()
    index = identity_index(db)
    current = {}
    groups = defaultdict(dict)
    for key, proof in witnesses.items():
        if proof.get('contracts'):
            groups[tuple(proof['events'])][key] = proof['contracts'][0]
        else:
            current[key] = capture(db,proof['events'],index=index)
    for events, items in groups.items():
        revisions = native_witnesses(db,events,sorted(set(items.values())),index=index)
        current.update({key:revisions[contract] for key,contract in items.items()})
    return {key for key, proof in witnesses.items() if proof['revision'] != current[key]}
