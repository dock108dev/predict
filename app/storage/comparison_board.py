"""Coherent, bounded saved occurrence capture without provider acquisition."""
import json
from copy import deepcopy
from app.storage.store import hashed, encoded
from app.storage.current_games import engine_binding, utc
from app.comparison.combined_inputs import build

LOCK = 901091
MAX_GAMES = 200
MAX_ASSOCIATIONS = 8192


def source_guard(store, members):
    """Original selected source associations, including disappearance/removal.

    Ingress and final publication take the same transaction advisory lock. An
    unrelated book/game does not enter this fingerprint. Catalog facts retain
    only this member's original event/market records; envelopes remain immutable.
    """
    rows=store.db.execute('SELECT source,kind,native_id,envelope_id,payload FROM current_source_projection WHERE source IN (%s,%s,%s) ORDER BY source,kind,native_id LIMIT %s',
        ('the_odds_api','kalshi','polymarket_us',MAX_ASSOCIATIONS+1)).fetchall()
    if len(rows)>MAX_ASSOCIATIONS:raise ValueError('board_source_association_capacity')
    if sum(len(r['payload'].encode()) for r in rows)>24*1024*1024:raise ValueError('board_source_association_byte_capacity')
    resolved=[]
    if members:
        bundles=discover(store,selected=tuple(members[0]))
        matched=[b for b in bundles if list(members[0]) in b['members']]
        if len(matched)==1:resolved=matched[0]['members']
    selected=set(map(tuple,members))|set(map(tuple,resolved));facts=[]
    for row in rows:
        v=json.loads(row['payload']);source=row['source'];kind=row['kind']
        if kind=='quote':
            native=v['quote']['source']['native_event_id']
            if (source,native) in selected:facts.append([source,kind,row['native_id'],row['envelope_id'],v])
        elif kind=='book':
            native=v['book']['raw']['ref']['event_id']
            if (source,native) in selected:facts.append([source,kind,row['native_id'],row['envelope_id'],v])
        elif kind=='catalog':
            ids={native for provider,native in selected if provider==source}
            if ids:
                facts.append([source,kind,dict(events=[e for e in v['events'] if e['id'] in ids],
                    markets=[m for m in v['markets'] if m['event_id'] in ids])])
    return hashed(dict(facts=facts,resolved_members=resolved))


def storage_key(game, policy):
    return game+':benchmark:'+policy.benchmark_venue


def discover(store, *, at=None, benchmark_venue='pinnacle', selected=None):
    envelopes,associations=store.combined_capture()
    bundles=build(envelopes,at=at or utc(),benchmark_venue=benchmark_venue,associations=associations,selected=selected)
    if len(bundles)>MAX_GAMES:raise ValueError('board_catalog_capacity')
    return sorted(bundles,key=lambda b:b['game_key'])


def choose(bundles, game):
    if game.startswith('combined:'):
        found=[b for b in bundles if b['game_key']==game]
    else:
        provider,native=game.split(':',1)
        found=[b for b in bundles if [provider,native] in b['members']]
    if len(found)!=1:raise ValueError('board_occurrence_absent_or_ambiguous')
    return found[0]


def capture(store, game, policy, *, at=None):
    """Capture once, preserve as-of on unchanged sources, compute after commit."""
    with store.db.transaction():
        store.db.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
        selected=None
        if not game.startswith('combined:'):selected=tuple(game.split(':',1))
        else:
            old=store.db.execute('SELECT payload FROM current_game_projection WHERE game_key=%s',(storage_key(game,policy),)).fetchone()
            if old:selected=tuple(json.loads(old['payload'])['inputs']['members'][0])
        bundle=choose(discover(store,at=at,benchmark_venue=policy.benchmark_venue,selected=selected),game)
        key=storage_key(bundle['game_key'],policy)
        guard=source_guard(store,bundle['members'])
        row=store.db.execute('SELECT payload FROM current_game_projection WHERE game_key=%s',(key,)).fetchone()
        # Aging alone never renews an input, engine or original applicability.
        if row:
            prior=json.loads(row['payload'])
            if prior.get('source_guard')==guard and prior.get('capture_engine')==engine_binding():
                return store.snapshot(key,policy)
        store.retain_combined(bundle,storage_key=key,source_guard=guard)
        return store.snapshot(key,policy)


def saved(store, game, policy, *, result_id=None):
    if result_id:
        row=store.db.execute('SELECT payload FROM current_game_result WHERE id=%s',(result_id,)).fetchone()
        if not row:raise ValueError('saved_result_absent')
        value=json.loads(row['payload'])
        if value['game_key']!=storage_key(game,policy) or value['policy']['revision']!=policy.revision:
            raise ValueError('saved_result_game_or_policy_conflict')
    else:
        row=store.db.execute('SELECT r.id,r.payload FROM current_latest_result l JOIN current_game_result r ON r.id=l.result_id WHERE l.game_key=%s AND l.policy_version=%s',
            (storage_key(game,policy),policy.revision)).fetchone()
        if not row:return None
        result_id=row['id'];value=json.loads(row['payload'])
    value=deepcopy(value);value['result_id']=result_id
    snap=store.db.execute('SELECT payload FROM current_game_snapshot WHERE id=%s',(value['snapshot_id'],)).fetchone()
    snapshot=json.loads(snap['payload'])
    value['source_guard']=snapshot['projection'].get('source_guard')
    value['guard_members']=snapshot['projection']['inputs']['members']
    value['superseded']=value['source_guard']!=source_guard(store,value['guard_members']) or value['engine_binding']!=engine_binding()
    return value


def view_bundle(store, bundle, policy):
    row=store.db.execute('SELECT payload FROM current_game_projection WHERE game_key=%s',(storage_key(bundle['game_key'],policy),)).fetchone()
    if row:
        v=json.loads(row['payload'])
        if v.get('source_guard')==source_guard(store,bundle['members']) and v.get('capture_engine')==engine_binding():
            return deepcopy(v['inputs'])
    return bundle


def catalog(bundles):
    games=[]
    for b in bundles:
        e=b['state_inputs']['events'][0]
        games.append(dict(game_key=b['game_key'],input_version=b['input_version'],title=e['title'],start_at=e['start_at'],
            participants=e['participants'],members=b['members'],scope='NFL/full_game/winner',
            matches=list({r['quote']['occurrence_match']['revision']:{k:deepcopy(r['quote']['occurrence_match'].get(k)) for k in ('revision','status','method','conflicts','occurrence_id')} for r in b['records']}.values()),
            native_alternatives=sum(sum(len(qs) for qs in o.get('alternatives',{}).values()) for g in e['groups'] for o in g['outcomes'])))
    out=dict(version='predict-board-catalog-1',games=games,limits=dict(maximum_games=MAX_GAMES),provider_requests=0)
    if len(encoded(out))>512*1024:raise ValueError('board_catalog_byte_capacity')
    return out
