"""Coherent, bounded saved occurrence capture without provider acquisition."""
import json
from copy import deepcopy
from app.storage.store import hashed, encoded
from app.storage.current_games import engine_binding, utc
from app.comparison.combined_inputs import build, prepare

LOCK = 901091
MAX_GAMES = 200
MAX_ASSOCIATIONS = 8192


class ReadContext:
    """One exact SQL read frame; membership and originals never outlive it.

    Create inside the caller's repeatable-read transaction (or capture lock).
    Immutable normalization may be reused, but current associations, matching
    and source guards are freshly captured for every context.
    """
    def __init__(self, store, *, at=None):
        self.store=store;self.at=at or utc();self.engine=engine_binding()
        self.envelopes,self.associations,rows=store.combined_read_capture()
        self.rows=[dict(r,value=json.loads(r['payload'])) for r in rows]
        admitted=[r for r in self.rows if r['source']=='the_odds_api' and r['kind']=='quote'
            and r['value']['event']['competition']=='NFL'
            and r['value']['market_identity']['family']=='moneyline'
            and r['value']['market_identity']['period']=='full_game']
        self.prepared=prepare(self.envelopes,at=self.at,associations=self.associations,admitted_records=admitted)
        self._guards={};self._bundles={};self._catalog_bundles=None

    def guard(self, members):
        key=tuple(map(tuple,members))
        if key in self._guards:return self._guards[key]
        resolved=[]
        if members:
            matches=[rows for rows in self.prepared['groups'] if tuple(members[0]) in
                {(r['quote']['source']['provider'],r['quote']['source']['native_event_id']) for r in rows}]
            if len(matches)==1:
                resolved=[list(v) for v in sorted({(r['quote']['source']['provider'],r['quote']['source']['native_event_id']) for r in matches[0]})]
        selected=set(key)|set(map(tuple,resolved));facts=[]
        winner_markets=set()
        for row in self.rows:
            if row['kind']=='catalog':
                value=row['value'];source=row['source']
                events={e['id'] for e in value['events'] if e.get('competition')=='NFL'}
                winner_markets.update((source,m['event_id'],m['id']) for m in value['markets']
                    if m['event_id'] in events and
                    ((m.get('market_type')=='moneyline' and m.get('period')=='full_game') or
                     ((m.get('v1_raw_binding') or {}).get('identity',{}).get('family')=='moneyline'
                      and (m.get('v1_raw_binding') or {}).get('identity',{}).get('period')=='full_game')))
        for row in self.rows:
            v=row['value'];source=row['source'];kind=row['kind']
            if kind=='quote':
                if ((source,v['quote']['source']['native_event_id']) in selected
                        and v['event'].get('competition')=='NFL'
                        and v['market_identity'].get('family')=='moneyline'
                        and v['market_identity'].get('period')=='full_game'):
                    facts.append([source,kind,row['native_id'],row['envelope_id'],v])
            elif kind=='book':
                ref=v['book']['raw']['ref']
                if (source,ref['event_id']) in selected and (source,ref['event_id'],ref['market_id']) in winner_markets:
                    facts.append([source,kind,row['native_id'],row['envelope_id'],v])
            elif kind=='catalog':
                ids={native for provider,native in selected if provider==source}
                if ids:facts.append([source,kind,dict(events=[e for e in v['events'] if e['id'] in ids],
                    markets=[m for m in v['markets'] if m['event_id'] in ids and (source,m['event_id'],m['id']) in winner_markets])])
        value=hashed(dict(facts=facts,resolved_members=resolved));self._guards[key]=value
        return value

    def catalog_bundles(self):
        if self._catalog_bundles is None:
            from app.dashboard.current_normalized import catalog_from_normalized
            from app.dashboard.current_state import unavailable
            out=[]
            for rows in self.prepared['groups']:
                executions=[r for r in rows if r['quote']['venue']!='pinnacle']
                if not executions:continue
                raw=unavailable();raw.update(clock_at=self.at,projected_at=self.at,state='available',runtime_id='retained-combined-input')
                state=catalog_from_normalized(raw,executions,include_profiles=False)
                members=[list(v) for v in sorted({(r['quote']['source']['provider'],r['quote']['source']['native_event_id']) for r in rows})]
                out.append(dict(game_key='combined:'+state['events'][0]['id'],members=members,
                    input_version=hashed(dict(source_guard=self.guard(members),matches=[r['quote']['occurrence_match']['revision'] for r in rows])),
                    records=rows,state_inputs=state))
            if len(out)>MAX_GAMES:raise ValueError('board_catalog_capacity')
            self._catalog_bundles=sorted(out,key=lambda b:b['game_key'])
        return self._catalog_bundles

    def catalog(self):
        return catalog(self.catalog_bundles())

    def bundles(self, *, benchmark_venue='pinnacle', selected=None, game=None, cache=True):
        groups=self.prepared['groups']
        if game is not None:
            member=choose(self.catalog_bundles(),game)['members'][0]
            selected=tuple(member)
        if selected is not None:
            groups=[rows for rows in groups if tuple(selected) in
                {(r['quote']['source']['provider'],r['quote']['source']['native_event_id']) for r in rows}]
        out=[]
        for rows in groups:
            key=(benchmark_venue,encoded(rows[0]['market_identity']['event']))
            values=self._bundles.get(key) if cache else None
            if values is None:
                values=build(self.envelopes,at=self.at,benchmark_venue=benchmark_venue,
                    prepared=dict(self.prepared,groups=[rows]))
                if cache:self._bundles[key]=values
            out.extend(values)
        if len(out)>MAX_GAMES:raise ValueError('board_catalog_capacity')
        return sorted(out,key=lambda b:b['game_key'])


def source_guard(store, members, *, context=None):
    """Original selected source associations, including disappearance/removal.

    Ingress and final publication take the same transaction advisory lock. An
    unrelated book/game does not enter this fingerprint. Catalog facts retain
    only this member's original event/market records; envelopes remain immutable.
    """
    context=context or ReadContext(store)
    if context.store is not store:raise ValueError('board_read_context_conflict')
    return context.guard(members)


def storage_key(game, policy):
    return game+':benchmark:'+policy.benchmark_venue


def discover(store, *, at=None, benchmark_venue='pinnacle', selected=None, game=None, context=None, cache=True):
    context=context or ReadContext(store,at=at)
    if context.store is not store or at is not None and context.at!=at:raise ValueError('board_read_context_conflict')
    return context.bundles(benchmark_venue=benchmark_venue,selected=selected,game=game,cache=cache)


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
        context=ReadContext(store,at=at)
        bundle=choose(discover(store,benchmark_venue=policy.benchmark_venue,selected=selected,game=game,context=context),game)
        key=storage_key(bundle['game_key'],policy)
        guard=source_guard(store,bundle['members'],context=context)
        row=store.db.execute('SELECT payload FROM current_game_projection WHERE game_key=%s',(key,)).fetchone()
        # Aging alone never renews an input, engine or original applicability.
        if row:
            prior=json.loads(row['payload'])
            if prior.get('source_guard')==guard and prior.get('capture_engine')==context.engine:
                return store.snapshot(key,policy)
        store.retain_combined(bundle,storage_key=key,source_guard=guard)
        return store.snapshot(key,policy)


def saved(store, game, policy, *, result_id=None, context=None):
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
    context=context or ReadContext(store)
    value['superseded']=value['source_guard']!=source_guard(store,value['guard_members'],context=context) or value['engine_binding']!=context.engine
    return value


def view_bundle(store, bundle, policy, *, context=None):
    row=store.db.execute('SELECT payload FROM current_game_projection WHERE game_key=%s',(storage_key(bundle['game_key'],policy),)).fetchone()
    if row:
        v=json.loads(row['payload'])
        context=context or ReadContext(store)
        if v.get('source_guard')==source_guard(store,bundle['members'],context=context) and v.get('capture_engine')==context.engine:
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
