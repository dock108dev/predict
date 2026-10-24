"""Background-only bounded metric publication; ordinary reads fetch one row."""
from copy import deepcopy
from contextlib import ExitStack
from decimal import Decimal
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
_META_FIELDS=('same_outcome','comparison_admission','native_market_type','series_id')
_CONTRACT="jsonb_build_object('market_identity',c.facts->'market_identity','selection',c.facts->'selection','verified',c.facts->'verified','orientation_evidence','[]'::jsonb,'comparison_scope',COALESCE(c.facts->'comparison_scope','{}'::jsonb),'comparison_source_metadata',"+_pick("c.facts->'comparison_source_metadata'",_META_FIELDS)+" || CASE WHEN c.facts#>>'{market_identity,scheduled_start}' IS DISTINCT FROM e.facts->>'scheduled_start' THEN "+_pick("c.facts->'comparison_source_metadata'",('schedule_binding',))+" ELSE '{}'::jsonb END || jsonb_build_object('scoring_scope',"+_pick("c.facts#>'{comparison_source_metadata,scoring_scope}'",('status','reason','missing_fields','scoring'))+"))"
_QUOTE_FIELDS=('source','original','times','state','freshness_policy','binding','book_confirmation','provenance')
_PRICE_FIELDS=('quote_id','quote_revision','source','venue','original','times','same_outcome',
    'occurrence_link','captured_source_state','captured_source_health','source_state','source_health',
    'freshness_policy','inputs_identity','book_confirmation')
_INPUT_FIELDS=('quote_id','quote_revision','source','venue','original','times','source_state','source_health',
    'captured_source_state','captured_source_health','freshness_policy','book_confirmation')


def _clock_frame(expression, fields):
    # Display selection prose and prior read-time age calculations have no part
    # in re-aging a frozen price. Preserve the complete sealed book proof.
    return (_pick(expression,fields)+" || CASE WHEN "+expression+" ? 'event' THEN jsonb_build_object('event',"+
        _pick(expression+"->'event'",('start_at',))+") ELSE '{}'::jsonb END")


def _comparison(name):
    expression="q->'"+name+"'"
    fields=('available','display_status','reason_code','reason_codes','missing_fields','selection_valid_until','input_refs','comparison_quote_id')
    return _pick(expression,fields)+" || jsonb_build_object('inputs',COALESCE((SELECT jsonb_agg("+_clock_frame('i',_INPUT_FIELDS)+") FROM jsonb_array_elements(COALESCE("+expression+"->'inputs','[]'::jsonb)) i),'[]'::jsonb))"


_PRICE=_clock_frame('q',_PRICE_FIELDS)+" || jsonb_build_object('occurrence_match',"+_pick("q->'occurrence_match'",('status','occurrence_id'))+")"+" || jsonb_build_object('gross_comparison',"+_comparison('gross_comparison')+",'current_comparison',"+_comparison('current_comparison')+")"
def _object_names(expression):
    # Stored dictionaries are validated before projection; malformed names must
    # never collapse two source fields into one SQL JSON object.
    invalid="to_jsonb((("+expression+")::text || ' invalid object dictionary')::integer)"
    return ("CASE WHEN "+expression+" IS NULL THEN NULL WHEN jsonb_typeof("+expression+")='array' THEN "
        "CASE WHEN NOT EXISTS (SELECT 1 FROM jsonb_array_elements("+expression+") n "
        "WHERE jsonb_typeof(n)<>'string' OR n#>>'{}' IN ('__proto__','constructor','prototype')) "
        "AND (SELECT count(*)=count(DISTINCT n) FROM jsonb_array_elements("+expression+") n) "
        "THEN "+expression+" ELSE "+invalid+" END ELSE "+invalid+" END")


_PUBLICATION_SQL="""WITH boards AS MATERIALIZED (
    SELECT game_key,"""+_pick('facts',('publication_dependencies','observation_binding'))+""" AS metadata,
        facts#>'{boards,odds,prices}' prices,facts#>'{boards,odds,price_field_pool}' pool,
        facts#>'{boards,odds,price_key_pool}' names,
        """+_object_names("facts#>'{boards,odds,price_object_keys}'")+""" object_names FROM latest_board),
    named AS MATERIALIZED (SELECT game_key,pool,object_names,CASE WHEN names IS NULL THEN p ELSE
        (SELECT jsonb_object_agg(CASE WHEN key IN ('quote_id','quote_revision','field_refs') THEN key ELSE names->>(key::int) END,
            CASE WHEN key='field_refs' THEN (SELECT jsonb_object_agg(names->>(k::int),v) FROM jsonb_each(value) AS ref(k,v)) ELSE value END)
         FROM jsonb_each(p)) END raw_price FROM boards,jsonb_array_elements(prices) p),
    restored AS MATERIALIZED (SELECT game_key,object_names,(raw_price-'field_refs') || COALESCE(
        (SELECT jsonb_object_agg(key,pool->(value::text)::int) FROM jsonb_each(
            COALESCE(raw_price->'field_refs','{}'::jsonb))),'{}'::jsonb) AS q
        FROM named),
    objects AS MATERIALIZED (SELECT game_key,CASE WHEN object_names IS NULL THEN q ELSE
        (SELECT jsonb_object_agg(field,CASE WHEN jsonb_typeof(value)='object' THEN
            COALESCE((SELECT jsonb_object_agg(CASE WHEN k ~ '^(0|[1-9][0-9]*)$' AND length(k)<10 THEN object_names->>(k::int) END,v) FROM jsonb_each(value) obj(k,v)),'{}'::jsonb)
            ELSE value END) FROM jsonb_each(q) fields(field,value)) END q FROM restored),
    projected AS MATERIALIZED (SELECT game_key,"""+_PRICE+""" AS price FROM objects)
    SELECT b.game_key,b.metadata,COALESCE((SELECT jsonb_agg(price) FROM projected p
        WHERE p.game_key=b.game_key),'[]'::jsonb) prices FROM boards b"""

_EVENT_SQL='SELECT id,provider,native_event_id,revision,'+_pick('facts',_EVENT_FIELDS)+' AS facts FROM current_event'
_OFFER_SQL='''SELECT c.id,c.event_id,c.venue,c.native_market_id,c.native_outcome_id,c.native_side,c.revision AS contract_revision,
    encode(sha256(convert_to((c.facts #- '{comparison_source_metadata,observed_at}')::text,'UTF8')),'hex') AS contract_dependency,
    '''+_CONTRACT+''' AS contract,o.revision AS offer_revision,o.source_at,o.received_at,'''+_pick('o.facts',_QUOTE_FIELDS)+''' AS quote,e.expires_order
    FROM current_contract c JOIN current_offer o ON o.contract_id=c.id JOIN current_event e ON e.id=c.event_id'''
_BOOK_SQL='SELECT venue,event_id,native_market_id,revision,received_at FROM current_native_book'
_STATUS=_pick('facts',('version','epoch','runtime','observation_binding','catalog_errors','observation_errors'))


# Intern repeated frozen field values in SQL, across price frames and legacy
# self-contained comparison inputs. This is a lossless capture encoding only;
# references never reach the published Coverage API or borrow current ingress.
# Only repeated values large enough to pay for their reference enter the pool.
def _intern_object(expression):
    # Keep native objects separate from generated references: an arbitrary
    # native field must never be mistaken for a capture-encoding instruction.
    return ("(SELECT jsonb_build_object('f',COALESCE(jsonb_agg(jsonb_build_array(ki.ids->f.key,f.value)) "
        "FILTER (WHERE ref.id IS NULL),'[]'::jsonb),'r',COALESCE(jsonb_agg(jsonb_build_array(ki.ids->f.key,ref.id)) "
        "FILTER (WHERE ref.id IS NOT NULL),'[]'::jsonb)) FROM jsonb_each("+
        expression+") f CROSS JOIN pool_index pi CROSS JOIN key_index ki CROSS JOIN LATERAL "
        "(SELECT pi.ids->encode(sha256(convert_to(f.value::text,'UTF8')),'hex') AS id) ref)")



def _intern_nested(expression, name):
    return (_intern_object(expression+"-'"+name+"'")+" || jsonb_build_object('"+name+"',"+
        _intern_object("COALESCE("+expression+"->'"+name+"','{}'::jsonb)")+")")


def _intern_price():
    # Comparisons and selected-input identities are often identical across
    # views/legs. Intern their fields too; restore exact independent objects.
    return (_intern_object("q-'gross_comparison'-'current_comparison'-'inputs_identity'-'source'")+
        " || jsonb_build_object('source',"+_intern_object("q->'source'")+
        ",'inputs_identity',"+_intern_object("COALESCE(q->'inputs_identity','{}'::jsonb)")+
        ",'gross_comparison',"+_intern_object("q->'gross_comparison'")+
        ",'current_comparison',"+_intern_object("q->'current_comparison'")+")")


_OFFER_COLUMNS=('id','event_id','venue','native_market_id','native_outcome_id','native_side','contract_revision',
    'contract_dependency','offer_revision','source_at','received_at','expires_order','quote','contract')


_PUBLICATION_CAPTURE_SQL="""WITH raw AS MATERIALIZED ("""+_PUBLICATION_SQL+"""),
    offers AS MATERIALIZED ("""+_OFFER_SQL+"""),
    frames AS MATERIALIZED (
        SELECT q-'gross_comparison'-'current_comparison'-'inputs_identity'-'source' f FROM raw,jsonb_array_elements(prices) q
        UNION ALL SELECT q->'source' FROM raw,jsonb_array_elements(prices) q
        UNION ALL SELECT COALESCE(q->'inputs_identity','{}'::jsonb) FROM raw,jsonb_array_elements(prices) q
        UNION ALL SELECT q->'gross_comparison' FROM raw,jsonb_array_elements(prices) q
        UNION ALL SELECT q->'current_comparison' FROM raw,jsonb_array_elements(prices) q
        UNION ALL SELECT i FROM raw,jsonb_array_elements(prices) q,
            LATERAL (SELECT q#>'{gross_comparison,inputs}' a UNION ALL SELECT q#>'{current_comparison,inputs}') c,
            jsonb_array_elements(c.a) i
        UNION ALL SELECT quote-'source' FROM offers
        UNION ALL SELECT contract-'market_identity' FROM offers
        UNION ALL SELECT contract->'market_identity' FROM offers
        UNION ALL SELECT quote->'source' FROM offers),
    keys AS MATERIALIZED (SELECT key,row_number() OVER (ORDER BY key) id FROM frames,jsonb_each(f) GROUP BY key),
    key_index AS MATERIALIZED (SELECT jsonb_object_agg(key,id) ids FROM keys),
    pool AS MATERIALIZED (SELECT value,row_number() OVER (ORDER BY value) id FROM frames,jsonb_each(f)
        WHERE octet_length(value::text)>16 GROUP BY value HAVING count(*)>1),
    pool_index AS MATERIALIZED (SELECT COALESCE(jsonb_object_agg(encode(sha256(convert_to(value::text,'UTF8')),'hex'),id),'{}'::jsonb) ids FROM pool)
    SELECT jsonb_build_object('offers',(SELECT COALESCE(jsonb_agg(
        jsonb_build_array(o.id,o.event_id,o.venue,o.native_market_id,o.native_outcome_id,o.native_side,
            o.contract_revision,o.contract_dependency,o.offer_revision,o.source_at,o.received_at,o.expires_order::text,
            """+_intern_nested('o.quote','source')+""", """+_intern_nested('o.contract','market_identity')+""") ORDER BY o.id),'[]'::jsonb) FROM offers o),
        'keys',(SELECT jsonb_agg(key ORDER BY id) FROM keys),
        'pool',(SELECT COALESCE(jsonb_agg(value ORDER BY id),'[]'::jsonb) FROM pool),
        'rows',(SELECT COALESCE(jsonb_agg(jsonb_build_object('game_key',game_key,
            'prices',(SELECT COALESCE(jsonb_agg("""+_intern_price()+"""),'[]'::jsonb)
                FROM jsonb_array_elements(prices) q)) ORDER BY game_key),'[]'::jsonb) FROM raw)) AS capture"""


def _restore(value, pool, keys):
    def keyed(items):
        out={}
        for key,item in items:
            if type(key) is not int or not 1<=key<=len(keys) or keys[key-1] in out:
                raise ValueError('coverage_capture_reference_invalid')
            out[keys[key-1]]=item
        return out
    fields=keyed(value.pop('f'));refs=keyed(value.pop('r'))
    if set(fields).intersection(refs) or set(value).intersection([*fields,*refs]):
        raise ValueError('coverage_capture_reference_invalid')
    for key,index in refs.items():
        if type(index) is not int or not 1<=index<=len(pool):
            raise ValueError('coverage_capture_reference_invalid')
        fields[key]=deepcopy(pool[index-1])
    value.update(fields)
    return value


def _captured_offers(capture):
    capture['offers']=[dict(zip(_OFFER_COLUMNS,row,strict=True)) for row in capture['offers']]
    for row in capture['offers']:
        row['expires_order']=Decimal(row['expires_order'])
        _restore(row['quote'],capture['pool'],capture['keys'])
        _restore(row['quote']['source'],capture['pool'],capture['keys'])
        _restore(row['contract'],capture['pool'],capture['keys'])
        _restore(row['contract']['market_identity'],capture['pool'],capture['keys'])
    return capture['offers']


def _publication_rows(capture, db):
    pool=capture['pool']
    for row in capture['rows']:
        # Validate one frozen dependency manifest at a time in the same MVCC
        # transaction. Do not retain the entire universe of duplicate proofs.
        metadata=db.execute('SELECT '+_pick('facts',('publication_dependencies','observation_binding'))+
            ' AS metadata FROM latest_board WHERE game_key=%s',(row['game_key'],)).fetchone()['metadata']
        for q in row['prices']:
            _restore(q,pool,capture['keys'])
            for name in ('source','inputs_identity','gross_comparison','current_comparison'):
                _restore(q[name],pool,capture['keys'])
        yield dict(row,metadata=metadata)


def _capture_size_query(capture_query=_PUBLICATION_CAPTURE_SQL):
    # Count projected bodies, including committed runtime diagnostics, before any
    # Python JSON object graph is materialized. Publication and raw facts share
    # the same repeatable-read snapshot as this preflight.
    query='''SELECT COALESCE(sum(n),0) n FROM (
        SELECT octet_length((capture-'rows')::text) + COALESCE((SELECT max(octet_length(r::text)) FROM jsonb_array_elements(capture->'rows') r),0) n FROM ('''+capture_query+''') p
        UNION ALL SELECT COALESCE(max(octet_length(('''+_pick('facts',('publication_dependencies','observation_binding'))+''')::text)),0) FROM latest_board
        UNION ALL SELECT octet_length(to_jsonb(e)::text) FROM ('''+_EVENT_SQL+''') e
        UNION ALL SELECT octet_length(to_jsonb(b)::text) FROM ('''+_BOOK_SQL+''') b
        UNION ALL SELECT octet_length(to_jsonb(r)::text) FROM data_runtime r
        UNION ALL SELECT octet_length(to_jsonb(s)::text) FROM (SELECT venue,state FROM current_source_status) s
        UNION ALL SELECT octet_length(('''+_STATUS+''')::text) FROM latest_board_status
        UNION ALL SELECT octet_length((facts->'query_observations')::text) FROM coverage_latest
    ) projected'''
    return query


def _capture_size(db):
    return int(db.execute(_capture_size_query()).fetchone()['n'])


def _capture_stream_sql():
    # PostgreSQL computes the frozen shared dictionaries once. The first cursor
    # record contains only admission bytes; no header or game enters Python
    # before its reservation. Subsequent records contain the header and complete
    # games, with deterministic ordering from this same repeatable-read capture.
    return ("WITH frozen AS MATERIALIZED ("+_PUBLICATION_CAPTURE_SQL+") "
        "SELECT 0 section,0 ordinal,jsonb_build_object('size',("+
        _capture_size_query('SELECT capture FROM frozen')+")) payload "
        "UNION ALL SELECT 1,0,capture-'rows' FROM frozen "
        "UNION ALL SELECT 2,r.ordinality,r.value FROM frozen,"
        "LATERAL jsonb_array_elements(capture->'rows') WITH ORDINALITY r "
        "ORDER BY 1,2")


def _expanded_size(db):
    # Sharing saves transport bytes, not the cost of detached Python copies.
    return int(db.execute("SELECT COALESCE(sum(n),0) n FROM ("
        "SELECT octet_length(to_jsonb(o)::text) n FROM ("+_OFFER_SQL+") o UNION ALL "
        "SELECT octet_length(prices::text) FROM ("+_PUBLICATION_SQL+") p) expanded").fetchone()['n'])


def _publication_frame(db, states, *, offers=None):
    """Compact structural adapter to the existing exact publication predicates.

    Original row revisions remain authoritative. Fields omitted here cannot
    weaken revocation: a change to any such field still changes its row revision.
    Candidate identity uses the shared owner, never a second matching algorithm.
    """
    from app.normalization.registry import Registry
    from app.comparison.native_scoring_scope import publication_dependencies
    from app.comparison.calculation_control import checkpoint
    events=db.execute(_EVENT_SQL+' ORDER BY id').fetchall()
    if offers is None:offers=db.execute(_OFFER_SQL+' ORDER BY c.id').fetchall()
    books=db.execute(_BOOK_SQL).fetchall()
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
        neighborhoods={},candidate_sets={},selection_identities={},active_events={r['event_id'] for r in offers})
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
    if any(error.get('game_key')==row['game_key'] for error in status.get('observation_errors',[])):
        return []
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
    from app.dashboard.comparison_board import expand_odds
    # Apply the ordinary exact-reference validator before any aging mutation.
    # Older self-contained inputs remain self-contained; no current row is used.
    expand_odds(dict(comparison_input_encoding='same-board-price-refs-1',prices=prices))
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
        with db.transaction(), ExitStack() as capture_resources:
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            # This bounded JSON projection can trigger hundreds of LLVM JIT
            # functions even for a small cohort. Compilation delays both first
            # rows and query cancellation past the worker cleanup allowance.
            # Keep the setting local to this capture, including on rollback.
            db.execute('SET LOCAL jit=off')
            cursor=capture_resources.enter_context(db.cursor(name='coverage_publication_rows'))
            cursor.itersize=1
            cursor.execute(_capture_stream_sql())
            size=next(cursor)['payload']['size']
            if size>MAX_CAPTURE_BYTES:raise ValueError('coverage_capture_capacity')
            reservation=max(size*12,_expanded_size(db)*4)+24*1024*1024
            if reservation>MAX_WORK_BYTES:raise ValueError('coverage_memory_capacity')
            lease=reservations.enter_context(BACKGROUND.claim('coverage',reservation))
            if not lease:return lease.deferred()
            owner=read_runtime(db,at=at)
            committed={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
            capture=next(cursor)['payload']
            frame,records=_publication_frame(db,source_states(committed,owner),offers=_captured_offers(capture))
            source_binding=observation_binding()
            saved=db.execute('SELECT '+_STATUS+' AS facts FROM latest_board_status WHERE singleton=true').fetchone()
            status=saved['facts'] if saved else {}
            raw=owner.get('status',{}).get('coverage',{})
            previous=db.execute("SELECT facts->'query_observations' AS queries FROM coverage_latest WHERE singleton=true").fetchone()
            queries=merge_queries(raw.get('cells',[]),(previous['queries'] or []) if previous else [])
            published=[]
            # Stream one complete frozen game; shared pools and all original offers
            # remain from the same MVCC snapshot. Never truncate the universe.
            capture['rows']=(item['payload'] for item in cursor)
            for row in _publication_rows(capture,db):
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
    value.update(publication_error=owner.get('calculations', {}).get('coverage_error'),
        publication_worker_state=owner.get('calculations', {}).get('coverage', 'unknown'))
    value.update(version=VERSION,read_at=instant,provider_requests=0,acquisition_requests=0)
    return value
