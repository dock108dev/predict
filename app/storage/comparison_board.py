"""Coherent current-row captures; ordinary reads never retain sports reports."""
from copy import deepcopy
from app.storage.store import hashed, encoded, stamp
from app.storage.current_games import engine_binding, utc
from app.comparison.combined_inputs import build
from app.comparison.occurrence_matching import OccurrenceResolver

LOCK = 901091
MAX_GAMES = 500
MAX_ASSOCIATIONS = 16384
MAX_CAPTURE_BYTES = 96 * 1024 * 1024


def _records(records, at):
    """Private edited shells; the resolver fully detaches every output record."""
    out=[]
    for item in records:
        if item['event'].get('competition')!='NFL' or item['market_identity'].get('family')!='moneyline' or item['market_identity'].get('period')!='full_game':continue
        if stamp(item['event']['scheduled_start'])<=stamp(at):continue
        # Only these containers change before OccurrenceResolver's final copy.
        # Other nested facts, including unknown fields, remain untouched here.
        r=dict(item);r['quote']=dict(item['quote'])
        for key in ('_instrument','_fingerprint'):r.pop(key,None)
        meta=dict(r.get('comparison_source_metadata',{}));r['comparison_source_metadata']=meta
        meta.pop('combined_envelope_id',None)
        if 'combined_native_binding' in meta:
            native=dict(meta['combined_native_binding']);meta['combined_native_binding']=native
            for key in ('catalog_envelope_id','book_envelope_id'):native.pop(key,None)
        if r['quote']['source']['provider']=='the_odds_api':
            r['comparison_scope']=dict(overtime='included')
            meta.update(phase='pregame',overtime='included',scope_basis='declared aggregate NFL full-game decisive benchmark; exceptional execution rules retained')
        out.append(r)
    return out


class ReadContext:
    """One caller-owned repeatable SQL snapshot and bounded transient game data."""
    def __init__(self, store, *, at=None, frame=None):
        from .current_rows import CurrentRowStore
        self.store=store;self.at=at or utc();self.engine=engine_binding()
        frame=frame if frame is not None else CurrentRowStore(store.db).capture(include_depth=False)
        self.epoch=str(frame['epoch']);self.revision=frame['revision']
        self.dependency_revisions=frame.get('dependency_revisions',{})
        self.native_dependency_revisions=frame.get('native_dependency_revisions',{})
        records=_records(frame['records'],self.at)
        statuses=frame.get('source_status',{})
        for record in records:
            q=record['quote'];status=statuses.get(q['venue'],statuses.get(q['source']['provider'],{}))
            if status.get('state') not in (None,'available','budget_delayed'):q['state']=status['state']
        if len(records)>MAX_ASSOCIATIONS or len(encoded(records))>MAX_CAPTURE_BYTES:raise ValueError('board_current_input_capacity')
        resolved=OccurrenceResolver().resolve(records,clock=self.at)
        grouped={}
        for r in resolved:grouped.setdefault(encoded(r['market_identity']['event']),[]).append(r)
        self.prepared=dict(at=self.at,originals={},groups=list(grouped.values()),excluded=[])
        self.source_status=frame.get('source_status',{})
        instant=stamp(self.at)
        clocks=[(r['quote']['source']['native_event_id'],r['quote']['times'].get('source_at') is None or (instant-stamp(r['quote']['times']['source_at'])).total_seconds()>1800) for r in records]
        receipts=[(r['quote']['source'],r['quote']['times'].get('received_at'),r['quote'].get('provenance')) for r in records]
        self.read_revision=hashed(dict(epoch=self.epoch,revision=self.revision,engine=self.engine,availability=clocks,receipts=receipts,source_states={k:v.get('state') for k,v in statuses.items()}))
        self._catalog_bundles=None
        self._normalization_registries=None

    def normalization_registries(self):
        """Share immutable fact registries only within this SQL read context."""
        if self._normalization_registries is None:
            from app.dashboard.current_normalized import NormalizationRegistries
            self._normalization_registries=NormalizationRegistries.load()
        return self._normalization_registries

    def guard(self,members):
        selected=set(map(tuple,members))
        rows=[r for group in self.prepared['groups'] for r in group if (r['quote']['source']['provider'],r['quote']['source']['native_event_id']) in selected]
        from .current_rows import contract_id, _clockless
        revisions=[(contract_id(r),self.dependency_revisions[contract_id(r)] if contract_id(r) in self.dependency_revisions else hashed(_clockless(r))) for r in rows]
        native_keys={hashed([r['quote']['source']['provider'],r['quote']['source']['native_event_id'],r['quote']['source']['native_market_id']]) for r in rows}
        native=[(key,self.native_dependency_revisions[key]) for key in sorted(native_keys) if key in self.native_dependency_revisions]
        matches=[_clockless(r['quote'].get('occurrence_match')) for r in rows]
        receipts=[(r['quote']['source'],r['quote']['times'].get('received_at'),r['quote'].get('provenance')) for r in rows]
        return hashed(dict(epoch=self.epoch,revisions=sorted(revisions),native=native,matches=matches,receipts=receipts,states=[r['quote'].get('state') for r in rows]))

    def catalog_bundles(self):
        if self._catalog_bundles is None:
            from app.dashboard.current_normalized import catalog_from_normalized
            from app.dashboard.current_state import unavailable
            out=[]
            for rows in self.prepared['groups']:
                executions=[r for r in rows if r['quote']['venue']!='pinnacle']
                if not executions:continue
                raw=unavailable();raw.update(clock_at=self.at,projected_at=self.at,state='available',runtime_id='current-rows:'+self.epoch)
                state=catalog_from_normalized(raw,executions,include_profiles=False,
                    registries=self.normalization_registries())
                members=[list(v) for v in sorted({(r['quote']['source']['provider'],r['quote']['source']['native_event_id']) for r in rows})]
                event=state['events'][0]
                summary={k:event[k] for k in ('id','title','start_at','participants')}
                summary['native_alternatives']=sum(sum(len(qs) for qs in o.get('alternatives',{}).values()) for g in event['groups'] for o in g['outcomes'])
                out.append(dict(game_key='combined:'+event['id'],members=members,input_version=self.guard(members),records=rows,catalog_event=summary))
            if len(out)>MAX_GAMES:raise ValueError('board_catalog_capacity')
            self._catalog_bundles=sorted(out,key=lambda b:b['game_key'])
        return self._catalog_bundles

    def catalog(self):
        return dict(catalog(self.catalog_bundles()),read_revision=self.read_revision,epoch=self.epoch)

    def bundles(self, *, benchmark_venue='pinnacle', selected=None, game=None, cache=True, occurrence_rows=None, _readiness_only=False):
        if _readiness_only and occurrence_rows is None:
            raise ValueError('board_readiness_occurrence_required')
        groups=self.prepared['groups']
        if occurrence_rows is not None:
            if not any(occurrence_rows is rows for rows in groups):raise ValueError('board_read_context_occurrence_conflict')
            groups=[occurrence_rows]
        if game is not None:selected=tuple(choose(self.catalog_bundles(),game)['members'][0])
        if selected is not None:groups=[rows for rows in groups if tuple(selected) in {(r['quote']['source']['provider'],r['quote']['source']['native_event_id']) for r in rows}]
        out=[]
        for rows in groups:
            if self.store.db is not None and any('depth' not in r['quote'] for r in rows):
                from .current_rows import CurrentRowStore
                rows=CurrentRowStore(self.store.db).hydrate_records(rows)
            values=build([],at=self.at,benchmark_venue=benchmark_venue,prepared=dict(self.prepared,groups=[rows]),
                registries=self.normalization_registries(),_current_guard=self.guard,_readiness_only=_readiness_only)
            for value in values:
                value['epoch']=self.epoch
                value['representation']='current typed event, exact native contracts, offers, depth and shared definitions; original source clocks retained'
                value['envelope_ids']=[];value['envelopes']=[]
            out.extend(values)
        if len(out)>MAX_GAMES:raise ValueError('board_catalog_capacity')
        return sorted(out,key=lambda b:b['game_key'])


def context_identity(bundle, policy, context):
    value=dict(epoch=context.epoch,game_key=bundle['game_key'],dependency_revision=bundle['input_version'],policy_revision=policy.revision,engine_binding=context.engine)
    from app.dashboard.comparison_board import entries, freshness, quote_key
    applicability=[(quote_key(q),freshness(q,bundle['state_inputs']['comparison_profiles'],event,stamp(context.at))['reasons']) for event,_,q in entries(bundle['state_inputs'])]
    return dict(context_id=hashed(dict(value,applicability=applicability)),**{k:v for k,v in value.items() if k!='game_key'})


def calculate_current(bundle,policy, *, context, details=False, selected_quote=None, selected_pair=None):
    """Expand existing financial owners transiently, one selected game at a time."""
    from app.dashboard.current_contract import serialize
    from app.comparison.estimated_pair import assemble
    state=serialize(deepcopy(bundle['state_inputs']),estimate_policy=policy,details=details and not (selected_quote or selected_pair),supported=False,paired=False)
    for event in state['events']:
        if details and selected_quote:
            from app.dashboard.comparison_board import entries
            from app.comparison.estimated_ev import evaluate
            for e,group,q in entries(dict(events=[event])):
                if q['id']==selected_quote:q['calculations']['funded_estimate']=evaluate(q,state['comparison_profiles'],at=stamp(bundle['as_of']),event=e,group=group,policy=policy,details=True)
            event['funded_pairs']=[]
        else:event['funded_pairs'],event['funded_pair_search']=assemble(event,state['comparison_profiles'],stamp(bundle['as_of']),policy=policy,details=details,selected_pair_id=selected_pair)
    identity=context_identity(bundle,policy,context)
    return dict(version='predict-current-calculation-2',game_key=bundle['game_key'],input_version=bundle['input_version'],as_of=bundle['as_of'],calculated_at=utc(),state=state,policy=policy.to_dict(),engine_binding=context.engine,calculation_context=identity,representation=bundle['representation'],superseded=False)


def source_guard(store,members, *, context=None):return (context or ReadContext(store)).guard(members)
def storage_key(game,policy):return game+':benchmark:'+policy.benchmark_venue

def discover(store, *, at=None,benchmark_venue='pinnacle',selected=None,game=None,context=None,cache=True):
    context=context or ReadContext(store,at=at)
    if context.store is not store or at is not None and context.at!=at:raise ValueError('board_read_context_conflict')
    return context.bundles(benchmark_venue=benchmark_venue,selected=selected,game=game,cache=cache)

def choose(bundles,game):
    if game.startswith('combined:'):found=[b for b in bundles if b['game_key']==game]
    else:
        provider,native=game.split(':',1);found=[b for b in bundles if [provider,native] in b['members']]
    if len(found)!=1:raise ValueError('current_inputs_changed_or_removed')
    return found[0]


def capture(*args,**kwargs):raise ValueError('sports_snapshot_archive_retired')
def saved(*args,**kwargs):raise ValueError('sports_result_archive_retired')
def view_bundle(store,bundle,policy, *, context=None):return bundle


def catalog(bundles):
    games=[]
    for b in bundles:
        e=b['catalog_event'] if 'catalog_event' in b else b['state_inputs']['events'][0]
        games.append(dict(game_key=b['game_key'],input_version=b['input_version'],title=e['title'],start_at=e['start_at'],participants=e['participants'],members=b['members'],scope='NFL/full_game/winner',matches=list({r['quote']['occurrence_match']['revision']:{k:deepcopy(r['quote']['occurrence_match'].get(k)) for k in ('revision','status','method','conflicts','occurrence_id')} for r in b['records']}.values()),native_alternatives=e.get('native_alternatives',0) if 'catalog_event' in b else sum(sum(len(qs) for qs in o.get('alternatives',{}).values()) for g in e['groups'] for o in g['outcomes'])))
    out=dict(version='predict-board-catalog-2',games=games,limits=dict(maximum_games=MAX_GAMES),provider_requests=0)
    if len(encoded(out))>2*1024*1024:raise ValueError('board_catalog_byte_capacity')
    return out
