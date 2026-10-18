"""Background-only bounded metric publication; ordinary reads fetch one row."""
from copy import deepcopy
from contextlib import ExitStack
from psycopg.types.json import Jsonb
from app.comparison.broad_coverage import build, select, merge_queries, VERSION
from .store import encoded, hashed, stamp
from .current_games import utc

MAX_BYTES = 8 * 1024 * 1024
LOCK = 903019


# Projection is deliberately performed by PostgreSQL before JSON decoding. Long
# native wording, financial boards, depth ladders and full peer-input copies never
# enter this worker's Python heap.
MAX_CAPTURE_BYTES = 8 * 1024 * 1024
MAX_WORK_BYTES = 128 * 1024 * 1024


def _pick(expression, fields):
    names=','.join("'"+key+"'" for key in fields)
    return "(SELECT COALESCE(jsonb_object_agg(key,value),'{}'::jsonb) FROM jsonb_each(COALESCE("+expression+",'{}'::jsonb)) WHERE key IN ("+names+"))"


_EVENT_FIELDS=('id','competition','season','stage','home','away','participants','title','scheduled_start','original_start',
    'shared_provider_ids','observed_identity_facts','neutral_venue','identity','schedule_conflict',
    'sport','game_number','replacement_game_id','source_participant_roles','schedule_metadata')
_META_FIELDS=('same_outcome','comparison_admission','native_market_type','series_id','schedule_binding')
_CONTRACT="jsonb_build_object('market_identity',c.facts->'market_identity','selection',c.facts->'selection','verified',c.facts->'verified','orientation_evidence','[]'::jsonb,'comparison_scope',COALESCE(c.facts->'comparison_scope','{}'::jsonb),'comparison_source_metadata',"+_pick("c.facts->'comparison_source_metadata'",_META_FIELDS)+" || jsonb_build_object('scoring_scope',"+_pick("c.facts#>'{comparison_source_metadata,scoring_scope}'",('status','reason','missing_fields','scoring'))+"))"
_QUOTE_FIELDS=('source','original','times','state','freshness_policy','binding','book_confirmation','provenance')
_PRICE_FIELDS=('quote_id','quote_revision','source','venue','original','times','same_outcome','occurrence_match',
    'occurrence_link','captured_source_state','captured_source_health','source_state','source_health',
    'observation_display','freshness_policy','inputs_identity','event','selection','book_confirmation')
_INPUT_FIELDS=('quote_id','quote_revision','source','venue','original','times','source_state','source_health',
    'captured_source_state','captured_source_health','freshness_policy','event','selection','book_confirmation')


def _comparison(name):
    expression="q->'"+name+"'"
    fields=('available','display_status','reason_code','reason_codes','missing_fields','selection_valid_until','input_refs','comparison_quote_id')
    return _pick(expression,fields)+" || jsonb_build_object('inputs',COALESCE((SELECT jsonb_agg("+_pick('i',_INPUT_FIELDS)+") FROM jsonb_array_elements(COALESCE("+expression+"->'inputs','[]'::jsonb)) i),'[]'::jsonb))"


_PRICE=_pick('q',_PRICE_FIELDS)+" || jsonb_build_object('gross_comparison',"+_comparison('gross_comparison')+",'current_comparison',"+_comparison('current_comparison')+")"
_PUBLICATION_SQL="SELECT game_key,"+_pick('facts',('publication_dependencies','observation_binding'))+" AS metadata,(SELECT COALESCE(jsonb_agg("+_PRICE+"),'[]'::jsonb) FROM jsonb_array_elements(facts#>'{boards,odds,prices}') q) AS prices FROM latest_board"
_EVENT_SQL='SELECT id,provider,native_event_id,revision,'+_pick('facts',_EVENT_FIELDS)+' AS facts FROM current_event'
_OFFER_SQL='''SELECT c.id,c.event_id,c.venue,c.native_market_id,c.native_outcome_id,c.native_side,c.revision AS contract_revision,
    encode(sha256(convert_to((c.facts #- '{comparison_source_metadata,observed_at}')::text,'UTF8')),'hex') AS contract_dependency,
    '''+_CONTRACT+''' AS contract,o.revision AS offer_revision,o.source_at,o.received_at,'''+_pick('o.facts',_QUOTE_FIELDS)+''' AS quote,e.expires_order
    FROM current_contract c JOIN current_offer o ON o.contract_id=c.id JOIN current_event e ON e.id=c.event_id'''
_STATUS=_pick('facts',('version','epoch','runtime','observation_binding','catalog_errors'))


def _capture_size(db):
    # Count projected bodies, including committed runtime diagnostics, before any
    # Python JSON object graph is materialized. Publication and raw facts share
    # the same repeatable-read snapshot as this preflight.
    query='''SELECT COALESCE(sum(n),0) n FROM (
        SELECT octet_length(to_jsonb(p)::text) n FROM ('''+_PUBLICATION_SQL+''') p
        UNION ALL SELECT octet_length(to_jsonb(e)::text) FROM ('''+_EVENT_SQL+''') e
        UNION ALL SELECT octet_length(to_jsonb(o)::text) FROM ('''+_OFFER_SQL+''') o
        UNION ALL SELECT octet_length(status::text) FROM data_runtime
        UNION ALL SELECT octet_length(('''+_STATUS+''')::text) FROM latest_board_status
        UNION ALL SELECT octet_length((facts->'query_observations')::text) FROM coverage_latest
    ) projected'''
    return int(db.execute(query).fetchone()['n'])


def _publication_frame(db, states):
    """Compact structural adapter to the existing exact publication predicates.

    Original row revisions remain authoritative. Fields omitted here cannot
    weaken revocation: a change to any such field still changes its row revision.
    Candidate identity uses the shared owner, never a second matching algorithm.
    """
    from app.normalization.registry import Registry
    from app.comparison.native_scoring_scope import publication_dependencies
    from app.comparison.calculation_control import checkpoint
    events=db.execute(_EVENT_SQL+' ORDER BY id').fetchall()
    offers=db.execute(_OFFER_SQL+' ORDER BY c.id').fetchall()
    books=db.execute('SELECT venue,event_id,native_market_id,revision,received_at FROM current_native_book').fetchall()
    if len(events)>4096 or len(offers)>32768 or len(books)>32768:raise ValueError('coverage_record_capacity')
    registry=Registry.current()
    for event in events:
        checkpoint()
        facts=event['facts'];roles=[]
        for role in ('home','away'):
            participant=facts.get(role)
            for name,cid in facts.get('participants',{}).items():
                if cid==participant:
                    resolved=registry.resolve('team',name,league=facts.get('competition'),venue=event['provider'])
                    if resolved.status=='resolved':participant=resolved.canonical_id
            roles.append(participant)
        event['pair']=[facts.get('competition'),sorted(roles,key=str)]
        event['start']=facts.get('original_start') or facts.get('scheduled_start')
        event['participants']={facts.get(role):value for role,value in zip(('home','away'),roles)}
        shared=dict(facts.get('shared_provider_ids',{}))
        for fact in facts.get('observed_identity_facts',[]):
            if fact.get('source_provider')=='sportradar' and fact.get('source_id'):shared['sportradar']=str(fact['source_id'])
        event['shared']=[[name,str(value)] for name,value in sorted(shared.items())]
    event_index={e['id']:e for e in events};by_event={}
    native=[r for r in offers if r['venue'] in ('kalshi','polymarket_us')]
    keys=[(event_index[r['event_id']]['provider'],event_index[r['event_id']]['native_event_id'],r['native_market_id'],r['native_outcome_id'],r['native_side']) for r in native]
    contexts=[dict(league=event_index[r['event_id']]['facts'].get('competition'),
        family=r['contract'].get('market_identity',{}).get('family'),period=r['contract'].get('market_identity',{}).get('period'),
        native_market_type=r['contract'].get('comparison_source_metadata',{}).get('native_market_type'),
        series_id=r['contract'].get('comparison_source_metadata',{}).get('series_id')) for r in native]
    for row in offers:
        row['scoring_dependency']=None
        by_event.setdefault(row['event_id'],[]).append(row)
    for row,dependency in zip(native,publication_dependencies(keys,contexts=contexts)):row['scoring_dependency']=dependency
    epoch=db.execute('SELECT epoch FROM current_row_epoch WHERE singleton=true').fetchone()['epoch']
    frame=dict(epoch=str(epoch),events=event_index,offers={r['id']:r for r in offers},by_event=by_event,
        books={(r['venue'],r['event_id'],r['native_market_id']):r for r in books},states=states,
        neighborhoods={},candidate_sets={},active_events={r['event_id'] for r in offers})
    # Retain only the shared projection fields needed by metrics and examples.
    from .current_rows import utc as current_clock
    from .schedule_metadata import project
    from .store import exact_time
    now=exact_time(current_clock());records=[]
    for row in offers:
        if row['expires_order']<now:continue
        q=row['quote'];q['venue']=row['venue']
        q.setdefault('times',{}).update(source_at=row['source_at'],received_at=row['received_at'])
        event=event_index[row['event_id']]['facts']
        records.append(dict(project(event,row['contract']),event=event,quote=q))
    return frame,records


def _age_publication(row, status, owner, frame, at, source_binding):
    """Age compact scalar frames with the ordinary observation/comparison owner."""
    from . import observation_publication as publication
    from .latest_board import runtime_identity
    from .current_rows import contract_id
    from app.dashboard.comparison_board import age_observation,age_gross_comparison
    reasons=[]
    if str(status.get('epoch'))!=frame['epoch'] or status.get('version')!='predict-latest-board-3':reasons.append('current_dependencies_changed')
    current=runtime_identity(owner);prior=status.get('runtime',{})
    if any(prior.get(k)!=current.get(k) for k in ('runtime_id','active','healthy','config','paused_sources','global_stopped','service_state','observation_state')):
        reasons.append('runtime_authority_changed')
    if current['observation_state']!='running':reasons.append('background_observations_unavailable')
    if status.get('observation_binding')!=source_binding or row['metadata'].get('observation_binding')!=source_binding:reasons.append('matching_binding_changed')
    if not owner.get('active'):reasons.append('updates_stopped' if owner.get('healthy') else 'data_runtime_unhealthy')
    saved=row['metadata'].get('publication_dependencies')
    checks=publication.reasons(frame,saved) if saved else dict(all=['current_dependencies_changed'],observations={},comparisons={})
    common=sorted(set([*reasons,*checks['all']]))
    prices=row['prices']
    for q in prices:
        cid=contract_id(dict(quote=q));own=sorted(set([*common,*checks['observations'].get(cid,[])]))
        if not q.get('event',{}).get('start_at'):
            q.setdefault('observation_display',{})['publication_reason_codes']=['captured_event_metadata_unavailable']
            continue
        age_observation(q,q['event'],at,source_states=frame['states'],publication_reasons=own)
    for q in prices:
        cid=contract_id(dict(quote=q));peer=sorted(set([*common,*checks['observations'].get(cid,[]),*checks['comparisons'].get(cid,[])]))
        for name in ('gross_comparison','current_comparison'):
            if name in q:age_gross_comparison(q[name],at,source_states=frame['states'],publication_reasons=peer,captured_rows=prices)
    # Shared compact refs are detached only while aging. Discard them immediately;
    # metric examples retain originals once, never their repeated peer copies.
    for q in prices:
        for name in ('gross_comparison','current_comparison'):
            if name in q:
                q[name].pop('inputs',None);q[name].pop('input_refs',None)
    return prices



def reconcile(db, *, at=None):
    from .latest_board import source_states
    from .current_games import observation_binding
    from app.collection.runtime_status import read_runtime
    from app.collection.current_policy import DEFAULT
    from app.comparison.calculation_control import checkpoint
    from app.collection.background_work import BACKGROUND
    at=at or utc()
    with ExitStack() as reservations:
        with db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            size=_capture_size(db)
            if size>MAX_CAPTURE_BYTES:raise ValueError('coverage_capture_capacity')
            reservation=size*12+24*1024*1024
            if reservation>MAX_WORK_BYTES:raise ValueError('coverage_memory_capacity')
            lease=reservations.enter_context(BACKGROUND.claim('coverage',reservation))
            if not lease:return lease.deferred()
            owner=read_runtime(db,at=at)
            committed={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
            frame,records=_publication_frame(db,source_states(committed,owner))
            source_binding=observation_binding()
            saved=db.execute('SELECT '+_STATUS+' AS facts FROM latest_board_status WHERE singleton=true').fetchone()
            status=saved['facts'] if saved else {}
            raw=owner.get('status',{}).get('coverage',{})
            previous=db.execute("SELECT facts->'query_observations' AS queries FROM coverage_latest WHERE singleton=true").fetchone()
            queries=merge_queries(raw.get('cells',[]),(previous['queries'] or []) if previous else [])
            published=[]
            for row in db.execute(_PUBLICATION_SQL+' ORDER BY game_key').fetchall():
                checkpoint()
                try:published.extend(_age_publication(row,status,owner,frame,at,source_binding))
                except (KeyError,ValueError,TypeError):continue
            value=build(records,published,config=owner.get('config') or DEFAULT,owner=dict(owner,states=frame['states']),at=at,
                queries=queries,encountered=raw.get('encountered_types',[]),
                exclusions=[*owner.get('status',{}).get('exclusions',[]),*status.get('catalog_errors',[])],
                resolve_inputs=True)
            from .latest_board import runtime_identity
            authority=runtime_identity(owner);authority.pop('calculation_state',None)
            value.update(epoch=frame['epoch'],input_revision=hashed([[r['id'],r['contract_revision'],r['offer_revision']] for r in frame['offers'].values()]),
                runtime_revision=owner.get('revision'),runtime_authority=authority,
                source_authority={key:state.get('state') for key,state in frame['states'].items()},
                source_binding=source_binding,query_observations=queries,
                work_metrics=dict(projected_input_bytes=size,reserved_work_bytes=reservation,maximum_capture_bytes=MAX_CAPTURE_BYTES,
                    maximum_work_bytes=MAX_WORK_BYTES,expanded_boards=0,provider_requests=0))
        checkpoint()
        # Publication is a separate clock from the captured cohort and never a
        # quote receipt. Explicit authored future clocks stay internally ordered.
        value['publication_at']=max((at,utc()),key=stamp)
        body=encoded(value)
        if len(body)>MAX_BYTES:raise ValueError('coverage_publication_capacity')
        from app.collection.current_storage_policy import require_disk_space,sql_usage,SQL_BYTE_CAP
        from .store import ROOT
        require_disk_space(ROOT/'.local/postgres',append_bytes=len(body))
        if sql_usage(db)+len(body)>=SQL_BYTE_CAP:raise ValueError('current_database_storage_cap')
        revision=hashed(value)
        with db.transaction():
            db.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            # A later capture cannot be replaced by an older slow computation.
            row=db.execute('SELECT captured_at FROM coverage_latest WHERE singleton=true').fetchone()
            if row and stamp(row['captured_at'])>stamp(at):return dict(published=False,reason='newer_coverage_capture')
            db.execute('''INSERT INTO coverage_latest VALUES (true,%s,%s,%s)
                ON CONFLICT(singleton) DO UPDATE SET captured_at=excluded.captured_at,
                revision=excluded.revision,facts=excluded.facts''',(at,revision,Jsonb(value)))
        return dict(published=True,revision=revision,cells=len(value['cells']),retained_observations=value['global_totals']['retained_observations'],bytes=len(body),provider_requests=0)


def read(db, *, at=None, league=None, venue=None, market=None, period=None, resource_guard=None):
    """One compact cohort, with age/authority diagnostics; never recompute it."""
    from app.collection.runtime_status import read_runtime
    from app.collection.current_policy import DEFAULT
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if resource_guard is not None:
            size=db.execute('SELECT octet_length(facts::text) n FROM coverage_latest WHERE singleton=true').fetchone()
            resource_guard(16*1024*1024+(int(size['n'])*16 if size else 0))
        row=db.execute('SELECT facts,revision FROM coverage_latest WHERE singleton=true').fetchone()
        instant=at or utc()
        owner=read_runtime(db,at=instant)
        epoch=db.execute('SELECT epoch FROM current_row_epoch WHERE singleton=true').fetchone()['epoch']
        committed={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
    if row:
        value=row['facts'];reasons=[]
        age=max(0,(stamp(instant)-stamp(value['captured_at'])).total_seconds())
        if age>15:reasons.append('coverage_publication_delayed')
        if str(value.get('epoch'))!=str(epoch):reasons.append('retained_epoch_changed')
        from .latest_board import runtime_identity
        authority=runtime_identity(owner);authority.pop('calculation_state',None)
        if value.get('runtime_authority')!=authority:reasons.append('runtime_changed_since_capture')
        from .latest_board import source_states
        if value.get('source_authority')!={key:state.get('state') for key,state in source_states(committed,owner).items()}:
            reasons.append('source_state_changed_since_capture')
        if stamp(instant)<stamp(value['captured_at']):reasons.append('coverage_capture_future')
        if not owner.get('healthy'):reasons.append('data_runtime_unhealthy')
        value=deepcopy(value)
        value.update(publication_state='stale' if reasons else 'published',publication_age_seconds=max(0,(stamp(instant)-stamp(value['publication_at'])).total_seconds()),
            capture_age_seconds=age,capture_to_publication_seconds=(stamp(value['publication_at'])-stamp(value['captured_at'])).total_seconds(),
            publication_reasons=reasons,read_revision=row['revision'])
    else:
        # First read may disclose configured capabilities, never assert an empty
        # measurement. The absent cohort has null measured totals and N/A ratios.
        value=build([],[],config=owner.get('config') or DEFAULT,owner=owner,at=instant)
        value.update(publication_state='pending',publication_at=None,captured_at=None,
            publication_reasons=['waiting_for_publication'],read_revision=None)
        for cell in value['cells']:
            cell['measured']=False
    value=select(value,league=league,venue=venue,market=market,period=period)
    if row is None:
        value['hidden_by_filter_observations']=None
        for count in (value['global_totals'],value['filtered_totals']):
            for key in count:count[key]=None
        for key in ('ratios','filtered_ratios'):
            for ratio in value[key].values():ratio.update(numerator=None,denominator=None,value=None)
        for cell in value['cells']:
            for key in cell['counts']:cell['counts'][key]=None
            for ratio in cell['ratios'].values():ratio.update(numerator=None,denominator=None,value=None)
    value.update(version=VERSION,read_at=instant,provider_requests=0,acquisition_requests=0)
    return value
