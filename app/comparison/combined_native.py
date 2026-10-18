"""Retained native sporting adapter without acquisition.

Original catalogs/books are retained by the caller. Explicit source roles,
active pregame facts and sealed predicates establish source-local applicability.
Cross-source identity remains the occurrence resolver's responsibility."""
from copy import deepcopy
from app.storage.store import hashed, stamp
from app.dashboard.session_projection import SessionProjection
from app.dashboard.current_state import unavailable
from app.collection.current_sink import normalized_records

VERSION = 'predict-combined-native-1'


def normalize(catalog, books, *, at, associations=None, include_missing=False):
    source = catalog['record']['source']
    inventory = deepcopy(catalog['record']['value']['inventory'])
    # Catalogs may gain season/stage after their initial display-only binding.
    # Re-run the same strict owner against retained original metadata; never
    # carry a refusal from an earlier incomplete event into a complete one.
    from app.collection.v1_comparison import annotate
    pending=[m for m in inventory['markets'] if m.get('comparison_admission',{}).get('reason')=='comparison_context_missing']
    if pending:annotate(dict(inventory,markets=pending),source,policy='manual-comparison-2')
    reducer = SessionProjection(); reducer.inventory = {source: inventory}
    projected=associations
    associations = {}
    for envelope in sorted(books, key=lambda x: stamp(x['record']['retained_at'])):
        for obs in envelope['record']['value']['observations']:
            ref = obs['book']['raw']['ref']; key = (source, ref['event_id'], ref['market_id'])
            if projected is not None and projected.get((source,'book',ref['event_id']+':'+ref['market_id']))!=envelope['id']:continue
            reducer.reduce_observation(deepcopy(obs)); associations[key] = envelope['id']
    states = unavailable()['source_status']
    states[source]['state'] = 'available'
    records, excluded = normalized_records(reducer, states, {}, dated_annotations=False, clock=at, include_missing=include_missing)
    markets = {m['id']: m for m in inventory['markets']}
    result = []
    for row in records:
        from .sporting_scope import supported
        if not supported(row['event'].get('competition'),row['market_identity']['family'],row['market_identity']['period']):continue
        q = row['quote']; event = row['event']; market = markets[q['source']['native_market_id']]
        binding = market['v1_raw_binding']
        if binding['sha256'] != hashed({k:v for k,v in binding.items() if k != 'sha256'}):
            excluded.append(dict(source=source, market_id=market['id'], reason='native_predicate_hash_conflict'));continue
        roles = event.get('source_participant_roles', {})
        role_ok = roles == {r:event[r] for r in ('home','away')} and len(set(roles.values())) == 2
        native = event.get('_native') or event.get('native_metadata') or {}
        phase = 'unknown'; evidence = []
        if source == 'kalshi':
            facts = [f for f in event.get('observed_identity_facts', [])
                     if f.get('main_game_event_ticker') == event['id']]
            if len(facts) == 1 and facts[0].get('status') == 'scheduled' and stamp(facts[0]['start_date']) == stamp(event['scheduled_start']):
                phase = 'pregame'; evidence = facts
        elif (native.get('period') == 'NS' and native.get('active') is True and native.get('closed') is False
              and str(native.get('id')) == event['id'] and stamp(native['startTime']) == stamp(event['scheduled_start'])):
            phase = 'pregame'; evidence = [{k:native.get(k) for k in ('id','period','active','closed','startTime','sportradarGameId')}]
        if stamp(at) >= stamp(event['scheduled_start']):phase = 'unknown'
        metadata = row['comparison_source_metadata']; metadata['phase'] = phase
        if source == 'kalshi':metadata.pop('selected_reference_data',None)
        terms = market.get('terms', {})
        overtime = (market.get('native_scope_binding') or {}).get('overtime','unknown')
        row['comparison_scope'] = dict(overtime=overtime); metadata['overtime'] = overtime
        book_id = associations[(source,event['id'],market['id'])]
        metadata['combined_native_binding'] = dict(version=VERSION, catalog_envelope_id=catalog['id'],
            book_envelope_id=book_id, original_roles=deepcopy(roles), phase_facts=deepcopy(evidence),
            original_terms=deepcopy(terms), predicate_sha256=binding['sha256'],
            unit_basis='existing admitted purchase_book USD per $1 contract; original depth contracts',
            original_quantity_units=q['original']['quantity_units'], actual_fills=None,
            completion='native original terms retained; no common completion condition asserted')
        from .native_scoring_scope import attach
        row = attach(row, at=at)
        admitted = metadata.get('comparison_admission',{}).get('supported') is not False
        if role_ok and admitted and not event.get('conflicting_duplicate') and not event.get('occurrence_conflict'):
            row['verified'] = True
            if row.get('event_scope'):
                row['event_scope']['policy'] = 'native-provider-event-1'
            row['orientation_evidence'].append(VERSION+':'+hashed(metadata['combined_native_binding']))
        elif not role_ok or event.get('conflicting_duplicate') or event.get('occurrence_conflict'):
            row['verified'] = False
            event['occurrence_conflict'] = True
        for name in ('_instrument','_fingerprint'):row.pop(name,None)
        result.append(row)
    return result, excluded
