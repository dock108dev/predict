"""Exact catalog dependencies and ownership-preserving normalization."""
from copy import deepcopy
from app.collection.current_catalog_delta import changes
from app.comparison.combined_native import normalize
from tests.test_current_service import native_fixture


def test_catalog_delta_separates_capture_refresh_context_and_native_terms():
    catalog,book=native_fixture()
    old={'kalshi':catalog};key=('kalshi',catalog['events'][0]['id'],catalog['markets'][0]['id'])
    new=deepcopy(old)
    new['kalshi']['markets'][0]['provenance']=[{'received_at':'new capture'}]
    assert changes(old,new)==dict(retained={key},withdraw=set(),refresh=set())
    new['kalshi']['events'][0]['stage']='changed-stage'
    assert changes(old,new)==dict(retained={key},withdraw=set(),refresh={key})
    new['kalshi']['markets'][0].setdefault('terms',{})['new_rule']='changed settlement'
    assert changes(old,new)==dict(retained=set(),withdraw={key},refresh=set())


def test_catalog_delta_does_not_ignore_unknown_native_fields_or_withdrawal():
    catalog,_=native_fixture();old={'kalshi':catalog};new=deepcopy(old)
    key=('kalshi',catalog['events'][0]['id'],catalog['markets'][0]['id'])
    new['kalshi']['markets'][0].setdefault('_native',{})['unknown_future_field']='new'
    assert key in changes(old,new)['withdraw']
    assert changes(old,{})['withdraw']=={key}


def test_catalog_delta_preserves_retirement_with_new_unrelated_markets():
    catalog, _ = native_fixture()
    old = {'kalshi': catalog}
    new = deepcopy(old)
    original = catalog['markets'][0]
    key = ('kalshi', original['event_id'], original['id'])
    new['kalshi']['markets'][0]['id'] += '-new'
    assert changes({}, new) == dict(retained=set(), withdraw=set(), refresh=set())
    assert changes(old, new) == dict(retained=set(), withdraw={key}, refresh=set())


def test_owned_normalization_matches_detached_path_without_mutating_inputs():
    cat,book=native_fixture()
    from app.storage.store import hashed
    binding=cat['markets'][0]['v1_raw_binding']
    binding['sha256']=hashed({k:v for k,v in binding.items() if k!='sha256'})
    catalog=dict(id='catalog',record=dict(source='kalshi',value=dict(inventory=cat)))
    observation=dict(type='prediction_book',source='kalshi',book=book,observed_at=book['raw']['received_at'],packets=[])
    books=[dict(id='book',record=dict(retained_at=book['raw']['received_at'],value=dict(observations=[observation])))]
    original=deepcopy((catalog,books))
    expected=normalize(catalog,books,at=book['raw']['received_at'],include_missing=True)
    actual=normalize(catalog,books,at=book['raw']['received_at'],include_missing=True,owned=True)
    assert actual==expected and actual[0]
    assert (catalog,books)==original


def test_book_dependencies_ignore_only_observation_and_display_values():
    from app.collection.current_native_catalog import native_material
    from app.collection.native_review_contract import project
    raw=dict(id='event',chatChannel=dict(chatMemberCount=12,channelId='same'),
             marketCounts=dict(numMarkets=100,numSpreadsAndTotalsMarkets=20),combos=dict(numMarkets=2,numSpreadsAndTotalsMarkets=1),
             eventState=dict(updatedAt='2026-10-27T20:00:00Z',mainSpreadLine='3.5',
                             marketGroupStats=[dict(line=3.5,period='full_game')],period='NS'))
    newer=deepcopy(raw)
    newer['chatChannel']['chatMemberCount']=99
    newer['eventState'].update(updatedAt='2026-10-27T21:00:00Z',mainSpreadLine='4.5')
    newer['eventState']['marketGroupStats'][0]['line']=4.5
    newer['marketCounts']['numMarkets']=101
    newer['marketCounts']['numSpreadsAndTotalsMarkets']=24
    newer['combos']['numSpreadsAndTotalsMarkets']=3
    before=native_material('polymarket_us',dict(_native=raw),event=True)
    assert native_material('polymarket_us',dict(_native=newer),event=True)==before
    # A physical image exemption never modifies historical financial review.
    assert project('polymarket_us',raw,event=True)!=project('polymarket_us',newer,event=True)
    for path,value in [('period','live'),('unknownFutureField','anything')]:
        changed=deepcopy(newer);changed['eventState'][path]=value
        assert native_material('polymarket_us',dict(_native=changed),event=True)!=before
    changed=deepcopy(newer);changed['chatChannel']['chatMemberCount']='malformed'
    assert native_material('polymarket_us',dict(_native=changed),event=True)!=before
    market=dict(id='same',bestBidQuote={'currency':'USD','value':'0.4'},marketSides=[dict(id='side',price='0.4',quote={})],rules='same')
    updated=deepcopy(market);updated.pop('bestBidQuote');updated['marketSides'][0]['price']=None
    assert native_material('polymarket_us',dict(_native=market))==native_material('polymarket_us',dict(_native=updated))
    updated['rules']='changed'
    assert native_material('polymarket_us',dict(_native=market))!=native_material('polymarket_us',dict(_native=updated))


def test_kalshi_metadata_modification_time_is_not_contract_time():
    from app.collection.current_native_catalog import native_material
    old=dict(last_updated_ts='2026-10-27T20:00:00Z',close_time='2026-10-28T20:00:00Z')
    new=dict(old,last_updated_ts='2026-10-27T21:00:00Z')
    expected=native_material('kalshi',dict(_native=old),event=True)
    assert native_material('kalshi',dict(_native=new),event=True)==expected
    new['close_time']='2026-10-29T20:00:00Z'
    assert native_material('kalshi',dict(_native=new),event=True)!=expected


def test_derived_participant_enrichment_does_not_rebuild_native_stream():
    from types import SimpleNamespace
    from app.comparison.lifecycle import worker_selections
    cat,book=native_fixture();mid=cat['markets'][0]['id'];eid=cat['events'][0]['id']
    parsed={mid:SimpleNamespace(raw=SimpleNamespace(ref=SimpleNamespace(event_id=eid)))}
    old=worker_selections('kalshi',parsed,cat)
    updated=deepcopy(cat);updated['markets'][0]['v1_raw_binding']['identity']['participants']=['away','home']
    assert worker_selections('kalshi',parsed,updated)[0]['material_revision']==old[0]['material_revision']
    assert ('kalshi',eid,mid) in changes({'kalshi':cat},{'kalshi':updated})['refresh']
    updated['markets'][0].setdefault('terms',{})['settlement']='changed'
    assert worker_selections('kalshi',parsed,updated)[0]['material_revision']!=old[0]['material_revision']


def test_new_valid_schedule_receipt_keeps_inputs_but_changed_authority_recalculates():
    from app.storage.store import hashed
    from app.storage.schedule_metadata import VERSION
    cat,_=native_fixture();event=cat['events'][0]
    proof=dict(version=VERSION,native_event_id=event['id'],start=event['scheduled_start'],
               authority=['kalshi','milestone','same'],received_at='2026-10-27T20:00:00Z',
               proofs=[dict(path='/events',body_sha256='old',received_at='2026-10-27T20:00:00Z')])
    proof['revision']=hashed(proof);event['schedule_metadata']=proof
    revised=deepcopy(cat);new=revised['events'][0]['schedule_metadata']
    new.update(received_at='2026-10-27T21:00:00Z',proofs=[dict(path='/events',body_sha256='new',received_at='2026-10-27T21:00:00Z')])
    new['revision']=hashed({k:v for k,v in new.items() if k!='revision'})
    assert not changes({'kalshi':cat},{'kalshi':revised})['refresh']
    new['authority']=['kalshi','milestone','different']
    new['revision']=hashed({k:v for k,v in new.items() if k!='revision'})
    assert changes({'kalshi':cat},{'kalshi':revised})['refresh']

    new['revision']='invalid'
    assert changes({'kalshi':cat},{'kalshi':revised})['refresh']


def test_subscription_plan_keeps_unaffected_groups_and_covers_entire_moving_roster():
    from app.collection.native_subscriptions import plan
    old={str(i):None for i in range(350)}
    groups=plan({}, {}, old,set())['groups']
    assert len(groups)==4 and max(map(len,groups.values()))==100
    new=dict(old);new.pop('5');new['new']=None
    changed={'150'}
    delta=plan(groups,old,new,changed)
    affected={rid for rid,ids in groups.items() if set(ids)&{'150','5'}}
    assert delta['retired']==affected
    for rid in set(groups)-affected:assert delta['groups'][rid] is groups[rid]
    all_ids=[mid for ids in delta['groups'].values() for mid in ids]
    assert len(all_ids)==len(set(all_ids)) and set(all_ids)==set(new)
    assert '150' in delta['invalidated'] and 'new' in delta['invalidated']
    same=plan(delta['groups'],new,new,set())
    assert not same['added'] and not same['retired'] and not same['invalidated']


def test_current_subscription_commands_debounce_every_initial_and_added_group():
    from app.collection.native_subscriptions import commands
    from unittest.mock import patch
    groups={'initial':['a','b'],'added':['c']}
    with patch('app.collection.native_subscriptions.market_slug',side_effect=lambda m:m):
        sent=commands(groups,{'a':'slug-a','b':'slug-b','c':'slug-c'})
    assert all(c['subscribe']['responsesDebounced'] is True for c in sent)
    assert [c['subscribe']['marketSlugs'] for c in sent]==[['slug-a','slug-b'],['slug-c']]


def test_spawned_catalog_preparation_matches_exact_path_and_releases_worker():
    import asyncio
    from app.collection.current_ingress import CatalogPreparation,prepare_catalog_change
    catalog,_=native_fixture();before=deepcopy(catalog)
    expected=prepare_catalog_change({},'kalshi',catalog)
    async def check():
        worker=CatalogPreparation()
        try:
            actual=await worker.prepare({},'kalshi',catalog)
            assert actual==expected
            next_value=await worker.prepare(actual[0],'kalshi',catalog)
            assert next_value==prepare_catalog_change(actual[0],'kalshi',catalog)
            assert catalog==before
        finally:await worker.close()
        assert worker.pool._shutdown_thread
    asyncio.run(check())


def test_owned_normalization_prepares_exact_sql_values_in_cpu_worker():
    from app.collection.current_database import normalize_storage_batch
    from app.storage.current_rows import prepare
    from app.storage.store import hashed
    cat,book=native_fixture()
    binding=cat['markets'][0]['v1_raw_binding'];binding['sha256']=hashed({k:v for k,v in binding.items() if k!='sha256'})
    catalog=dict(id='catalog',record=dict(source='kalshi',value=dict(inventory=cat)))
    observation=dict(type='prediction_book',source='kalshi',book=book,observed_at=book['raw']['received_at'],packets=[])
    images=[dict(id='book',record=dict(retained_at=book['raw']['received_at'],value=dict(observations=[observation])))]
    original=deepcopy((catalog,images))
    rows,errors=normalize_storage_batch(catalog,images,book['raw']['received_at'],False)
    actual=normalize_storage_batch(catalog,images,book['raw']['received_at'],True,detached=True)
    assert actual==([prepare(row) for row in rows],errors)
    assert actual[0] and (catalog,images)==original


def test_catalog_ipc_restores_unchanged_parent_metadata_sharing():
    import asyncio
    from app.collection.current_ingress import CatalogPreparation
    catalog,_=native_fixture()
    async def check():
        worker=CatalogPreparation()
        try:
            actual,_=await worker.prepare({},'kalshi',catalog)
            # Mutable row shells remain detached; source metadata is identical.
            for old,new in zip(catalog['markets'],actual['kalshi']['markets']):
                assert old is not new
                if '_native' in old:assert old['_native'] is new['_native']
            assert actual==prepare_catalog_change({},'kalshi',catalog)[0]
        finally:await worker.close()
    from app.collection.current_ingress import prepare_catalog_change
    asyncio.run(check())


def test_catalog_indexes_reuse_prices_but_replace_changed_authority():
    from app.collection.current_database import DatabaseIngressSink
    sink=DatabaseIngressSink(None,{})
    cat,_=native_fixture();inventory={'kalshi':cat}
    first=sink.catalog_indexes(inventory)
    assert sink.catalog_indexes(inventory) is first
    changed=deepcopy(inventory)
    changed['kalshi']['markets'][0]['title']='changed metadata'
    second=sink.catalog_indexes(changed)
    assert second is not first
    assert next(iter(first[0].values())).get('title')!='changed metadata'
    assert next(iter(second[0].values()))['title']=='changed metadata'


def test_group_move_preserves_display_only_for_unchanged_selected_members():
    from types import SimpleNamespace
    from app.collection.current_service import CurrentService
    source='polymarket_us'
    keys={mid:(source,'e',mid) for mid in ('moving','refresh','changed','removed','untouched')}
    group={mid for mid in keys if mid!='untouched'}
    transition=dict(invalidated=group,changed={'changed'},added={'new':sorted(group-{'removed'})})
    worker=SimpleNamespace(subscription_transition=transition)
    delta=dict(retained=set(keys.values())-{keys['removed']},refresh={keys['refresh']},withdraw={keys['removed']})
    service=SimpleNamespace(dispatch=True,database_mode=True,workers={source:worker},states={},
        sink=SimpleNamespace(reducer=SimpleNamespace(generation=1,books=set(keys.values()))),
        row=lambda kind,venue,**values:values)
    command=CurrentService.catalog.operation(service,source,{},prepared={},catalog_delta=delta)
    row,_=next(command)
    assert row['catalog_delta']['reimaging']=={keys['moving']}
    assert row['catalog_delta']['retained']=={keys['untouched']}
    assert row['catalog_delta']['withdraw']=={keys[mid] for mid in group}
    command.close()
