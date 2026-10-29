"""Coherent current-row captures; ordinary reads never retain sports reports."""
from copy import deepcopy
from app.storage.store import hashed, encoded, stamp
from app.storage.current_games import engine_binding, utc
from app.comparison.combined_inputs import build
from app.comparison.occurrence_matching import OccurrenceResolver

LOCK = 901091
MAX_ASSOCIATIONS = 16384
MAX_CAPTURE_BYTES = 96 * 1024 * 1024


def _observation_records(records):
    """Price admission never parses optional model/reference attachments."""
    out=[]
    for record in records:
        if record['quote']['venue']=='pinnacle':continue
        value=dict(record,quote=dict(record['quote']))
        for field in ('sharp_reference','comparison_input_refs','comparison_input_status','engine_inputs'):
            value['quote'].pop(field,None)
        out.append(value)
    return out


def _records(records, at):
    """Private edited shells; the resolver fully detaches every output record."""
    from app.collection.current_policy import SPORTS
    out=[]
    for item in records:
        if item['event'].get('competition') not in SPORTS or item['market_identity'].get('family') not in ('moneyline','spread','total'):continue
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
        if (r['quote']['source']['provider']=='the_odds_api'
                and r['event'].get('competition')=='NFL'
                and r['market_identity'].get('family')=='moneyline'
                and r['market_identity'].get('period')=='full_game'):
            r['comparison_scope']=dict(overtime='included')
            meta.update(phase='pregame',overtime='included',scope_basis='declared aggregate NFL full-game decisive benchmark; exceptional execution rules retained')
        out.append(r)
    return out


class ReadContext:
    """One caller-owned repeatable SQL snapshot and bounded transient game data."""
    def __init__(self, store, *, at=None, frame=None, resource_guard=None, tolerate_invalid_catalog=False):
        from .current_rows import CurrentRowStore
        self.store=store;self.at=at or utc();self.engine=engine_binding();self.resource_guard=resource_guard
        self.tolerate_invalid_catalog=tolerate_invalid_catalog;self.catalog_errors=[]
        frame=frame if frame is not None else CurrentRowStore(store.db).capture(include_depth=False)
        self.epoch=str(frame['epoch']);self.revision=frame['revision']
        self.dependency_revisions=frame.get('dependency_revisions',{})
        self.native_dependency_revisions=frame.get('native_dependency_revisions',{})
        records=_records(frame['records'],self.at)
        # Bind exact line-local reference pairs from this same SQL capture.
        # Retained ingress attachments may predate reference or rule changes.
        from app.collection.current_benchmark import attach as attach_benchmark
        statuses=frame.get('source_status',{})
        for record in records:
            q=record['quote'];status=statuses.get(q['venue'],statuses.get(q['source']['provider'],{}))
            if status.get('state') not in (None,'available','budget_delayed'):q['state']=status['state']
            elif q['source']['provider']=='the_odds_api' and status.get('state') in ('available','budget_delayed') and q['state'] in ('stopped','error','connecting','resyncing'):
                q['state']=status['state']
        if len(encoded(records))>MAX_CAPTURE_BYTES:raise ValueError('board_current_input_capacity')
        resolved=OccurrenceResolver().resolve(records,clock=self.at)
        # Canonical team IDs can reverse the deterministic side ordering.
        # Rebind the complete original pair after identity projection so its
        # selected index still names the exact participant, line and outcome.
        attach_benchmark([r for r in resolved if r['quote']['source']['provider']=='the_odds_api' and r['quote']['venue']!='pinnacle'],
                         [r for r in resolved if r['quote']['venue']=='pinnacle'])
        grouped={}
        for r in resolved:grouped.setdefault(encoded(r['market_identity']['event']),[]).append(r)
        self.prepared=dict(at=self.at,originals={},groups=list(grouped.values()),excluded=[])
        self.source_status=frame.get('source_status',{})
        instant=stamp(self.at)
        clocks=[(r['quote']['source']['native_event_id'],r['quote']['times'].get('source_at') is None or (instant-stamp(r['quote']['times']['source_at'])).total_seconds()>1800) for r in records]
        receipts=[(r['quote']['source'],r['quote']['times'].get('received_at'),r['quote'].get('provenance')) for r in records]
        self.read_revision=hashed(dict(epoch=self.epoch,revision=self.revision,engine=self.engine,availability=clocks,receipts=receipts,source_states={k:v.get('state') for k,v in statuses.items()}))
        self._catalog_bundles=None
        self._observation_bundles={}
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
                executions=_observation_records(rows)
                if not executions:continue
                raw=unavailable();raw.update(clock_at=self.at,projected_at=self.at,state='available',runtime_id='current-rows:'+self.epoch)
                members=[list(v) for v in sorted({(r['quote']['source']['provider'],r['quote']['source']['native_event_id']) for r in rows})]
                try:
                    state=catalog_from_normalized(raw,executions,include_profiles=False,
                        source_rules={},selected_applicability={})
                except ValueError:
                    if not self.tolerate_invalid_catalog:raise
                    from .schedule_metadata import diagnostic
                    failures=[d for record in executions if (d:=diagnostic(record)) is not None]
                    self.catalog_errors.append(dict(members=members,reason=failures[0]['reason'] if failures else 'observation_invalid',
                        **(dict(schedule_conflicts=failures[:8],omitted=max(0,len(failures)-8)) if failures else {})))
                    continue
                event=state['events'][0]
                summary={k:event[k] for k in ('id','title','start_at','participants')}
                summary.update(league=rows[0]['event']['competition'],
                    sport=rows[0]['event'].get('sport'),
                    families=sorted({r['market_identity']['family'] for r in rows}),
                    periods=sorted({r['market_identity']['period'] for r in rows}))
                summary['native_alternatives']=sum(sum(len(qs) for qs in o.get('alternatives',{}).values()) for g in event['groups'] for o in g['outcomes'])
                out.append(dict(game_key='combined:'+event['id'],members=members,input_version=self.guard(members),records=rows,catalog_event=summary))
            self._catalog_bundles=sorted(out,key=lambda b:b['game_key'])
        return self._catalog_bundles

    def catalog(self):
        return dict(catalog(self.catalog_bundles()),read_revision=self.read_revision,epoch=self.epoch)

    def observation_bundles(self, *, benchmark_venue='pinnacle', selected=None, game=None):
        """Validated source frames without financial/profile admission.

        Only the selected occurrence's bounded asks are hydrated. Optional
        benchmark construction is decoration after original-price validation.
        It cannot remove an otherwise admitted source frame.
        """
        from app.dashboard.current_normalized import catalog_from_normalized
        from app.dashboard.current_state import unavailable
        from app.dashboard.current_contract import drain, serialize_steps
        from app.comparison.estimated_policy import DEFAULT_POLICY
        from app.comparison.combined_inputs import _benchmark
        found=self.catalog_bundles()
        if game is not None:found=[choose(found,game)]
        if selected is not None:found=[b for b in found if list(selected) in b['members']]
        out=[]
        for source in found:
            key=(source['game_key'],benchmark_venue)
            if key not in self._observation_bundles:
                rows=source['records']
                if self.store.db is not None and any('depth' not in r['quote'] for r in rows):
                    from .current_rows import CurrentRowStore
                    rows=CurrentRowStore(self.store.db).hydrate_records(rows,resource_guard=self.resource_guard)
                executions=_observation_records(rows)
                raw=unavailable();raw.update(clock_at=self.at,projected_at=self.at,state='available',runtime_id='current-rows:'+self.epoch)
                state=catalog_from_normalized(raw,executions,include_profiles=False,source_rules={},selected_applicability={})
                # Reuse the existing fact validator and supported native-price
                # conversions without invoking its financial owners.
                state=drain(serialize_steps(state,prices_only=True,estimate_policy=DEFAULT_POLICY))
                state['comparison_profiles']={}
                if self.store.db is not None:
                    from .current_rows import contract_id
                    from app.dashboard.comparison_board import entries
                    # A book receipt can advance with an unchanged price.
                    # Fetch its own clocks from this same selected SQL frame;
                    # never relabel the retained quote clocks as book clocks.
                    ids=[contract_id(record) for record in rows]
                    books=self.store.db.execute('''SELECT c.id AS contract_id,b.source_at,b.received_at,b.revision,
                        b.quantity_units,b.state,b.sync,b.sequence FROM current_contract c
                        JOIN current_native_book b ON b.venue=c.venue AND b.event_id=c.event_id
                            AND b.native_market_id=c.native_market_id WHERE c.id=ANY(%s)''',(ids,)).fetchall()
                    by_contract={book['contract_id']:{k:v for k,v in book.items() if k!='contract_id'} for book in books}
                    for _,_,q in entries(state):
                        book=by_contract.get(contract_id(dict(quote=q)))
                        if book is not None:q['observed_book']=book
                benchmark_value=None;benchmark_originals=None;reason=None
                try:benchmark_value,benchmark_originals=_benchmark(rows,state,benchmark_venue)
                except (ValueError,KeyError,TypeError,ArithmeticError) as exc:reason=str(exc)[:160] or 'optional_benchmark_unavailable'
                value=dict(source,as_of=self.at,state_inputs=state,records=rows,epoch=self.epoch,
                    source_status=deepcopy(self.source_status),
                    benchmark_venue=benchmark_venue,benchmark=benchmark_value,benchmark_reason=reason,
                    benchmark_originals=benchmark_originals,envelope_ids=[],envelopes=[],
                    representation='current typed source observations, exact native contracts and bounded asks; original source clocks retained')
                self._observation_bundles[key]=value
            out.append(self._observation_bundles[key])
        return out

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
                rows=CurrentRowStore(self.store.db).hydrate_records(rows,resource_guard=self.resource_guard)
            values=build([],at=self.at,benchmark_venue=benchmark_venue,prepared=dict(self.prepared,groups=[rows]),
                registries=self.normalization_registries(),_current_guard=self.guard,_readiness_only=_readiness_only)
            for value in values:
                value['epoch']=self.epoch
                value['representation']='current typed event, exact native contracts, offers, depth and shared definitions; original source clocks retained'
                value['envelope_ids']=[];value['envelopes']=[]
            out.extend(values)
        return sorted(out,key=lambda b:b['game_key'])


def context_identity(bundle, policy, context):
    value=dict(epoch=context.epoch,game_key=bundle['game_key'],dependency_revision=bundle['input_version'],policy_revision=policy.revision,engine_binding=context.engine)
    from app.dashboard.comparison_board import entries, freshness, quote_key
    # Current SQL guards retain raw source identity. A local applicability
    # review can change the normalized native contract without new ingress or
    # different price/freshness; selected financial Details must bind it too.
    applicability=[(quote_key(q),q.get('native_contract',{}).get('id'),
        freshness(q,bundle['state_inputs']['comparison_profiles'],event,stamp(context.at))['reasons'])
        for event,_,q in entries(bundle['state_inputs'])]
    return dict(context_id=hashed(dict(value,applicability=applicability)),**{k:v for k,v in value.items() if k!='game_key'})


def observation_identity(bundle, context):
    """Bind source facts; elapsed age changes their display, not their identity."""
    from app.dashboard.comparison_board import entries, quote_key, price
    value=dict(epoch=context.epoch,game_key=bundle['game_key'],dependency_revision=bundle['input_version'],engine_binding=context.engine)
    availability=sorted((quote_key(q),price(q)['observation_revision'])
                        for _,_,q in entries(bundle['state_inputs']))
    return dict(context_id=hashed(dict(value,availability=availability)),**{k:v for k,v in value.items() if k!='game_key'})


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
    from app.comparison.bound_finance import pairs
    for event in state['events']:
        event['funded_pairs'].extend(pairs(event,state['comparison_profiles'],policy,existing=event['funded_pairs']))
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


def catalog(bundles):
    games=[]
    for b in bundles:
        e=b['catalog_event'] if 'catalog_event' in b else b['state_inputs']['events'][0]
        league=b['records'][0]['event']['competition']
        families=sorted({r['market_identity']['family'] for r in b['records']})
        periods=sorted({r['market_identity']['period'] for r in b['records']})
        games.append(dict(game_key=b['game_key'],input_version=b['input_version'],title=e['title'],start_at=e['start_at'],participants=e['participants'],members=b['members'],
            league=league,sport=e.get('sport') or b['records'][0]['event'].get('sport'),families=families,periods=periods,
            scope='/'.join([league,','.join(periods),','.join('winner' if f=='moneyline' else f for f in families)]),
            matches=list({r['quote']['occurrence_match']['revision']:{k:deepcopy(r['quote']['occurrence_match'].get(k)) for k in ('revision','status','method','conflicts','occurrence_id')} for r in b['records']}.values()),native_alternatives=e.get('native_alternatives',0) if 'catalog_event' in b else sum(sum(len(qs) for qs in o.get('alternatives',{}).values()) for g in e['groups'] for o in g['outcomes'])))
    out=dict(version='predict-board-catalog-2',games=games,limits=dict(maximum_games=len(games)),provider_requests=0)
    if len(encoded(out))>2*1024*1024:raise ValueError('board_catalog_byte_capacity')
    return out
