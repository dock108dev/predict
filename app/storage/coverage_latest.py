"""Background-only bounded metric publication; ordinary reads fetch one row."""
from copy import deepcopy
from contextlib import ExitStack
from app.collection.runtime_status import runtime_identity
from . import ordinary_evidence as evidence
from .ordinary_projection import price_reasons
from psycopg.types.json import Jsonb
from app.comparison.broad_coverage import build, select, merge_queries, VERSION
from app.comparison.display_identity import published_key
from .store import encoded, hashed, stamp
from .current_games import utc

MAX_BYTES = 8 * 1024 * 1024
LOCK = 903019


# Source facts are projected in SQL before decoding. The display proof is read
# one immutable member at a time from the ordinary head, under the same MVCC.
MAX_CAPTURE_BYTES = 8 * 1024 * 1024
MAX_WORK_BYTES = 1024 * 1024 * 1024


class _CaptureDeferred(Exception):
    def __init__(self, value):
        self.value = value


def _pick(expression, fields):
    names=','.join("'"+key+"'" for key in fields)
    return "(SELECT COALESCE(jsonb_object_agg(key,value),'{}'::jsonb) FROM jsonb_each(COALESCE("+expression+",'{}'::jsonb)) WHERE key IN ("+names+"))"


_EVENT_FIELDS=('id','competition','season','stage','home','away','participants','title','scheduled_start','original_start',
    'shared_provider_ids','observed_identity_facts','neutral_venue','identity','schedule_conflict',
    'sport','game_number','replacement_game_id','source_participant_roles','schedule_metadata',
    'status','state','occurrence_conflict','conflicting_duplicate','related_game_event_id')
_META_FIELDS=('same_outcome','comparison_admission','native_market_type','series_id')
_CONTRACT="jsonb_build_object('market_identity',c.facts->'market_identity','selection',c.facts->'selection','verified',c.facts->'verified','orientation_evidence','[]'::jsonb,'comparison_scope',COALESCE(c.facts->'comparison_scope','{}'::jsonb),'comparison_source_metadata',"+_pick("c.facts->'comparison_source_metadata'",_META_FIELDS)+" || CASE WHEN c.facts#>>'{market_identity,scheduled_start}' IS DISTINCT FROM e.facts->>'scheduled_start' THEN "+_pick("c.facts->'comparison_source_metadata'",('schedule_binding',))+" ELSE '{}'::jsonb END || jsonb_build_object('scoring_scope',"+_pick("c.facts#>'{comparison_source_metadata,scoring_scope}'",('status','reason','missing_fields','scoring'))+"))"
_QUOTE_FIELDS=('source','original','times','state','freshness_policy','binding','book_confirmation','provenance')
_NATIVE_EVENT_FIELDS=('sportradarGameId','originalStartTime','replacementGameId','rescheduledFromGameId','gameNumber')
_NATIVE_EVENT="CASE WHEN jsonb_typeof(facts->'_native')='object' AND facts->'_native'<>'{}'::jsonb THEN facts->'_native' ELSE facts->'native_metadata' END"
_EVENT_SQL='SELECT id,provider,native_event_id,revision,'+_pick('facts',_EVENT_FIELDS)+" || jsonb_build_object('_native',"+_pick(_NATIVE_EVENT,_NATIVE_EVENT_FIELDS)+") AS facts FROM current_event"
_OFFER_SQL = """SELECT c.id,c.event_id,c.venue,c.revision AS contract_revision,
    """ + _CONTRACT + """ AS contract,o.revision AS offer_revision,o.source_at,o.received_at,
    """ + _pick('o.facts', _QUOTE_FIELDS) + """ AS quote
    FROM current_contract c JOIN current_offer o ON o.contract_id=c.id
    JOIN current_event e ON e.id=c.event_id
    WHERE c.event_id=ANY(%s) AND e.expires_order >= %s"""


def _stream_capture_totals(db, event_ids, expires_order):
    return db.execute(
        'SELECT COALESCE(sum(octet_length(to_jsonb(r)::text)),0) total, '
        'COALESCE(max(octet_length(to_jsonb(r)::text)),0) largest FROM ('
        'SELECT to_jsonb(o) AS facts FROM (' + _OFFER_SQL + ') o UNION ALL '
        'SELECT to_jsonb(e) FROM (' + _EVENT_SQL + ' WHERE id=ANY(%s)) e) r',
        (event_ids, expires_order, event_ids)).fetchone()


def _records(db, event_ids, expires_order):
    from .current_rows import project_contract

    offers = db.execute(_OFFER_SQL + ' ORDER BY c.id', (event_ids, expires_order)).fetchall()
    if len(offers) > 32768:
        raise ValueError('coverage_record_capacity')
    events = {row['id']: row['facts'] for row in db.execute(
        _EVENT_SQL + ' WHERE id=ANY(%s)', (event_ids,))}
    records = []
    for offer in offers:
        quote = offer['quote']
        quote['venue'] = offer['venue']
        quote.setdefault('times', {}).update(source_at=offer['source_at'], received_at=offer['received_at'])
        event = events[offer['event_id']]
        contract = offer['contract']
        if contract['market_identity'].get('scheduled_start') != event.get('scheduled_start'):
            contract = project_contract(event, contract, quote['times']['received_at'])
        records.append(dict(contract, event=event, quote=quote))
    revisions = [[r['id'], r['contract_revision'], r['offer_revision']] for r in offers]
    return records, revisions


def _displayed(member, event_ids, dependencies, owner, states, *, instant, epoch, policy):
    """Report the same rows and price authority as the ordinary Odds desk."""
    from app.dashboard.trade_desk import direct_venue_offer

    publication = member['publication']
    common = []
    if publication['epoch'] != epoch:
        common.append('input_epoch_replaced')
    if not owner.get('healthy'):
        common.append('data_runtime_unhealthy')
    if not owner.get('active') or owner.get('global_stopped'):
        common.append('updates_stopped')
    for row in member['rows']:
        if not direct_venue_offer(row) or evidence.event_id(row['source']) not in event_ids:
            continue
        reasons = price_reasons(row, dependencies, owner, states, at=instant,
                                epoch=epoch, publication_epoch=publication['epoch'], common=common)
        invalid = {'input_epoch_replaced', 'input_replaced_or_removed', 'aggregate_provider_replaced'}
        authority = sorted(invalid.intersection(reasons))
        if publication['policy'] != policy:
            authority.append('matching_binding_changed')
        if not owner.get('healthy'):
            authority.append('data_runtime_unhealthy')
        if not owner.get('active') or owner.get('global_stopped'):
            authority.append('updates_stopped')
        # Keep only the fields consumed by the independent Coverage census.
        # No legacy before-fee price-difference result is emitted by Browse Odds.
        projected = {name: row[name] for name in (
            'quote_id', 'quote_revision', 'source', 'venue', 'original', 'times',
            'same_outcome', 'occurrence_link', 'occurrence_match', 'book_confirmation',
            'freshness_policy') if name in row}
        projected['display_outcome_key'] = published_key(row)
        projected['captured_source_state'] = row.get('source_state', 'unknown')
        projected['price_current'] = not reasons
        projected['observation_display'] = dict(publication_reason_codes=authority)
        yield projected


def reconcile(db, *, at=None):
    from . import ordinary_publication as live
    from .board_capture import capture_batches
    from .store import exact_time
    from app.collection.current_policy import DEFAULT
    from app.comparison.calculation_control import checkpoint
    from app.collection.background_work import BACKGROUND
    at=at or utc()
    instant=stamp(at)
    expires_order=exact_time(at)
    with ExitStack() as reservations:
        with db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            # This bounded JSON projection can trigger hundreds of LLVM JIT
            # functions even for a small cohort. Compilation delays both first
            # rows and query cancellation past the worker cleanup allowance.
            # Keep the setting local to this capture, including on rollback.
            db.execute('SET LOCAL jit=off')
            owner, states = live.authority(db, at=instant)
            provider = live.aggregate_provider(owner=owner)
            policy = live.policy_identity(provider)
            head = live.status(db)
            display_result_id = head['result_id'] if head else None
            groups = capture_batches(db)
            legacy_components = {hashed(sorted(group)): group for group in groups}
            index = evidence.members(db, legacy_components=legacy_components)
            raw=owner.get('status',{}).get('coverage',{})
            previous=db.execute("SELECT facts->'query_observations' AS queries FROM comparison_publication WHERE kind='coverage' AND id=''").fetchone()
            queries=merge_queries(raw.get('cells',[]),(previous['queries'] or []) if previous else [])
            from .coverage_partitions import partitions,merge
            size=reservation=partition_count=0;revisions=[];memory=[];lease=None
            epoch=str(db.execute('SELECT epoch FROM current_row_epoch WHERE singleton=true').fetchone()['epoch'])
            def parts():
                nonlocal size,reservation,partition_count,lease
                for ids in partitions(db, groups=groups):
                    checkpoint()
                    member_rows = evidence.selected_members(index, ids)
                    totals = _stream_capture_totals(db, ids, expires_order)
                    largest_member = max((r['stored_bytes'] for r in member_rows), default=0)
                    local_size = max(int(totals['largest']), largest_member)
                    if local_size > MAX_CAPTURE_BYTES:
                        raise ValueError('coverage_capture_capacity')
                    required = int(totals['total']) * 6 + 24 * 1024 * 1024
                    if member_rows:
                        # One decoded member at a time. The bounded projection
                        # retained per source row is charged by cohort below.
                        required += MAX_CAPTURE_BYTES * 6 + sum(r['stored_bytes'] for r in member_rows) * 16
                    if required > MAX_WORK_BYTES:
                        raise ValueError('coverage_memory_capacity')
                    if lease is None:
                        lease = reservations.enter_context(BACKGROUND.claim('coverage', required))
                        if not lease:
                            raise _CaptureDeferred(lease.deferred())
                    else:
                        BACKGROUND.resize('coverage', required)
                    size = max(size, local_size)
                    reservation = max(reservation, required)
                    partition_count += 1
                    records, local_revisions = _records(db, ids, expires_order)
                    dependencies = live.dependencies(db, ids, provider=provider) if member_rows else {}
                    published = []
                    selected = set(ids)
                    for entry in member_rows:
                        member = evidence.read_member(db, entry, capacity=MAX_CAPTURE_BYTES)
                        published.extend(_displayed(member, selected, dependencies, owner, states,
                                                    instant=instant, epoch=epoch, policy=policy))
                        del member
                    revisions.extend(local_revisions)
                    part = build(records, published, config=owner.get('config') or DEFAULT,
                                 owner=dict(owner, states=states), at=at, queries=queries,
                                 encountered=raw.get('encountered_types', []),
                                 exclusions=owner.get('status', {}).get('exclusions', []),
                                 resolve_inputs=True, ordinary_publication=True)
                    from app.collection.background_work import resident_bytes
                    memory.append(resident_bytes())
                    del records, published
                    yield part
            try:value=merge(parts())
            except _CaptureDeferred as exc:return exc.value
            value['limits']['record_limit_scope']='complete_peer_partition'
            input_revision=hashed(sorted(revisions))
            authority=runtime_identity(owner);authority.pop('calculation_state',None)
            value.update(epoch=epoch,input_revision=input_revision,display_result_id=display_result_id,
                runtime_revision=owner.get('revision'),runtime_authority=authority,
                source_authority={key:state.get('state') for key,state in states.items()},
                source_binding=policy,query_observations=queries,
                work_metrics=dict(projected_input_bytes=size,reserved_work_bytes=reservation,maximum_capture_bytes=MAX_CAPTURE_BYTES,
                    maximum_work_bytes=MAX_WORK_BYTES,partitions=partition_count,partition_resident_bytes=memory,expanded_boards=0,provider_requests=0))
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
            row=db.execute("SELECT captured_at FROM comparison_publication WHERE kind='coverage' AND id=''").fetchone()
            if row and stamp(row['captured_at'])>stamp(at):return dict(published=False,reason='newer_coverage_capture')
            db.execute('''INSERT INTO comparison_publication (kind,id,captured_at,revision,facts) VALUES ('coverage','',%s,%s,%s)
                ON CONFLICT(kind,id) DO UPDATE SET captured_at=excluded.captured_at,
                revision=excluded.revision,facts=excluded.facts''',(at,revision,Jsonb(value)))
        return dict(published=True,revision=revision,cells=len(value['cells']),retained_observations=value['global_totals']['retained_observations'],bytes=len(body),provider_requests=0)


def read(db, *, at=None, league=None, venue=None, market=None, period=None, resource_guard=None):
    """One compact cohort, with age/authority diagnostics; never recompute it."""
    from . import ordinary_publication as live
    from app.collection.current_policy import DEFAULT
    with db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if resource_guard is not None:
            size=db.execute("SELECT octet_length(facts::text) n FROM comparison_publication WHERE kind='coverage' AND id=''").fetchone()
            resource_guard(16*1024*1024+(int(size['n'])*16 if size else 0))
        row=db.execute("SELECT facts,revision FROM comparison_publication WHERE kind='coverage' AND id=''").fetchone()
        instant=at or utc()
        owner, states = live.authority(db, at=instant)
        epoch=db.execute('SELECT epoch FROM current_row_epoch WHERE singleton=true').fetchone()['epoch']
    if row:
        value=row['facts'];reasons=[]
        age=max(0,(stamp(instant)-stamp(value['captured_at'])).total_seconds())
        if age>15:reasons.append('coverage_publication_delayed')
        if str(value.get('epoch'))!=str(epoch):reasons.append('retained_epoch_changed')
        authority=runtime_identity(owner);authority.pop('calculation_state',None)
        if value.get('runtime_authority')!=authority:reasons.append('runtime_changed_since_capture')
        if value.get('source_authority')!={key:state.get('state') for key,state in states.items()}:
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
    value.setdefault('display_result_id', None)
    value.update(version=VERSION,read_at=instant,provider_requests=0,acquisition_requests=0)
    return value
