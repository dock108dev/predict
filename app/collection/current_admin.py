"""Read-only operator projection and locally generated, bounded issue vocabulary."""
from copy import deepcopy
import re
import time
from app.dashboard.current_contract import packed, stamp
from .current_sink import utc

VENUES = ('kalshi','polymarket_us','novig','prophetx')
SITES = {'kalshi':'https://docs.kalshi.com','polymarket_us':'https://docs.polymarket.us','the_odds_api':'https://the-odds-api.com','service':'local'}
# Only developer-owned codes enter persistence. Unknown exception/provider text
# is suppressed even when it consists entirely of letters and numbers.
CODES = {'issue_retention_invalid','native_identity_exclusion'} | set('''sanitized_failure ValueError OSError RuntimeError TimeoutError ConnectionError ClientError InvalidStatus KeyError TypeError BudgetStop rss_cap ownership_or_authority_unavailable worker_cleanup_timeout source_cleanup_unresolved cleanup_safety_unresolved attended_runtime_deadline retry_after_outside_operational_envelope current_discovery_retained_cap provider_backoff_pending native_source_inventory_cap current_connection_cap websocket_retry_after_outside_envelope dedicated_credential_missing_or_invalid aggregate_offering_unobserved aggregate_credentials_unavailable aggregate_transport_closed aggregate_response_byte_cap aggregate_encoding_unsupported aggregate_secret_echo_suppressed aggregate_dispatch_revoked aggregate_idle clock_jump aggregate_runtime_envelope_consumed aggregate_transport_uncertain aggregate_rate_limit aggregate_authentication aggregate_http_failure aggregate_bootstrap_schema reset_window_unknown aggregate_common_sport_unobserved aggregate_admission_failed bootstrap_budget_delayed aggregate_budget_delayed reset_window_evidence_invalid reset_window_evidence_unverified quota_missing_duplicate_or_malformed quota_ceiling_or_headers_contradictory quota_ledger_missing quota_ledger_corrupt_or_oversize quota_record_capacity clock_continuity_unknown clock_regression quota_persistence_failed quota_ledger_unavailable reset_window_not_current reset_transition_unresolved acquisition_ownership_required invalid_reservation qualification_envelope_invalid qualification_envelope_expired qualification_envelope_consumed qualification_scope_invalid reset_window_expired quota_unknown ambiguous_dispatch_unresolved quota_reserve_or_exhausted dispatch_not_reserved response_without_dispatch quota_counter_or_charge_contradictory bootstrap_unexpected_charge'''.split())
CATEGORIES = set('authentication entitlement offering_unobserved malformed_source connection local_defect cleanup resource discovery ownership rate_limit quota_or_source identity_exclusion'.split())
CODES.update('restart_identity_unknown restart_clock_evidence_contradictory restart_not_established restart_accounting_refresh_required reservation_owner_conflict'.split())

def code(value):
    value=str(value)
    return value if value in CODES or re.fullmatch(r'(http|websocket)_[1-5][0-9]{2}',value) else 'sanitized_failure'


def advice(category, failure):
    if category in ('authentication','entitlement') or failure in ('aggregate_authentication','aggregate_credentials_unavailable'):
        return 'authentication_entitlement', 'Affected feed cannot acquire prices.', 'Check the dedicated credential and provider entitlement, then recover with a fresh runtime.'
    if category=='offering_unobserved':
        return 'query_offering_gap', 'No offering observed in this exact query; other sources remain useful.', 'Wait for the normally due affordable slot; investigate this offering without repeated coverage searches.'
    if category=='identity_exclusion':
        return 'identity_predicate', 'Identity or predicate is unverified; affected comparisons are withheld.', 'Inspect the exact exclusion and binding evidence; preserve source-local prices.'
    if category=='cleanup':
        return 'local_cleanup', 'Ownership remains held; recovery is blocked.', 'Resolve client/task cleanup before reopening; preserve reservations.'
    if category=='quota_or_source' and any(x in failure for x in ('quota','clock','reset','budget','ambiguous','reservation')):
        return 'budget_accounting', 'Metered acquisition waits for safe accounting or its scheduled slot.', 'Inspect dated usage, unresolved charges, reset evidence and next due; preserve spend.'
    if category in ('connection','rate_limit') or failure in ('aggregate_transport_uncertain','aggregate_http_failure','aggregate_rate_limit'):
        return 'transport_uncertainty', 'Affected source transport is unavailable; freshness is separate.', 'Respect backoff; inspect cleanup and any uncertain charge before recovery.'
    if category=='malformed_source' or failure in ('aggregate_admission_failed','aggregate_bootstrap_schema'):
        return 'malformed_source', 'Rejected data cannot replace valid admitted inputs.', 'Inspect the bounded admission reason; repair or wait for a complete valid image.'
    return 'local_admission_resource', 'Affected source is unavailable or unqualified; independent paths continue.', 'Inspect exclusions and resource limits; fix the smallest local defect before recovery.'


def issue(service, venue, category, failure):
    venue=venue if venue in (*VENUES,'the_odds_api','service') else 'service'
    category=category if category in CATEGORIES else 'local_defect'
    failure=code(failure)
    provider='the_odds_api' if venue in ('novig','prophetx') else venue
    affected=[venue] if venue in VENUES else ['novig','prophetx'] if venue=='the_odds_api' else list(VENUES)
    kind,impact,action=advice(category,failure)
    worker=service.workers.get(provider)
    q=worker.ledger.snapshot() if worker and hasattr(worker,'ledger') else None
    context=getattr(worker,'issue_context',{})
    at=utc()
    return dict(schema='predict-site-issue-2',provider=provider,site=SITES[provider],affected_venues=affected,
        endpoint_class=context.get('endpoint_class', 'discovery_or_book' if venue in ('kalshi','polymarket_us') else 'service_or_quota'),
        runtime_id=service.runtime_id,attempt_id=context.get('attempt_id',service.runtime_id),candidate_digest=service.digest,
        first_at=at,last_at=at,occurrences=1,category=category,kind=kind,code=failure,
        scope=dict(sports=[context['sport']] if context.get('sport') else service.config['sports'],families=service.config['families']),
        impact=impact,healthy_independent_paths=[v for v in VENUES if v not in affected and service.states[v]['state']=='available'],
        credits=0 if provider in ('kalshi','polymarket_us') else context.get('charged_credits'),
        reserved_credits=0 if provider in ('kalshi','polymarket_us') else None if q is None else q.get('reserved'),retry_count=getattr(worker,'metrics',{}).get('retries',0),
        backoff_seconds=service.config['backoff_seconds'] if venue in ('kalshi','polymarket_us') else [],next_action=action)


def age(at):
    if at is None:return None
    try:
        value=(stamp(utc())-stamp(at)).total_seconds()
        return value if value>=0 else None
    except (ValueError,TypeError):return None


def project(service, raw):
    store=service.store
    state=store.snapshot() if store else None
    index=store.index(state) if state else {}
    panels=[]
    for provider,venues in (('kalshi',['kalshi']),('polymarket_us',['polymarket_us']),('the_odds_api',['novig','prophetx'])):
        worker=service.workers.get(provider)
        metrics=deepcopy(getattr(worker,'metrics',{}))
        quotes=[x['quote'] for x in index.values() if x['quote']['venue'] in venues]
        source_times=[q['times']['source_at'] for q in quotes if q['times'].get('source_at')]
        receipt_times=[q['times']['received_at'] for q in quotes if q['times'].get('received_at')]
        # The latest source observation is not the age of every retained quote.
        latest=max(source_times,key=stamp) if source_times else None
        received=max(receipt_times,key=stamp) if receipt_times else None
        observed_sources=[service.states[v].get('source_at') for v in venues if service.states[v].get('source_at')]
        observed_receipts=[service.states[v].get('received_at') for v in venues if service.states[v].get('received_at')]
        summaries={v:deepcopy(service.states[v]) for v in venues}
        backoff=max(0,getattr(worker,'backoff_until',0)-time.monotonic())
        latest_issue=next((i for i in reversed(service.issues) if i['runtime_id']==service.runtime_id and any(v in i['affected_venues'] for v in venues)),None)
        panels.append(dict(next_action=None if latest_issue is None else latest_issue['next_action'],provider=provider,affected_venues=venues,status=summaries,
            source_at=latest,source_age_seconds=age(latest),received_at=received,receipt_age_seconds=age(received),
            last_book_observation_at=max(observed_sources,key=stamp) if observed_sources else None,last_book_receipt_at=max(observed_receipts,key=stamp) if observed_receipts else None,last_http_received_at=metrics.get('last_received_at'),socket_connected=bool(getattr(worker,'socket',None)) if provider!='the_odds_api' else None,
            timestamp_meanings=sorted({q['times']['source_time_kind'] for q in quotes}),
            quotes=len(quotes),identity_verified=sum(bool(q['binding']['verified']) for q in quotes),
            comparison_eligible=sum(bool(q['comparison']['eligible']) for q in quotes),
            calculation_eligible={k:sum(bool(q.get('calculations',{}).get(k,{}).get('eligible')) for q in quotes) for k in ('raw_difference','arbitrage','ev','sizing')},
            stale=sum(bool(q['stale']) for q in quotes),freshness_policies=list({packed(q['freshness_policy']):q['freshness_policy'] for q in quotes if q.get('freshness_policy')}.values()),
            backoff_remaining_seconds=backoff,worker_done=service.tasks[provider].done() if provider in service.tasks else None,
            active_sports=getattr(worker,'active_sports',None),metrics=metrics))
    raw.update(admin_schema='predict-admin-1',observed_at=utc(),sources=panels,
        service_state='running' if service.dispatch else 'stopped' if service.cleanup_complete else 'blocked',
        deadline_remaining_seconds=None if service.deadline is None else max(0,service.deadline-time.monotonic()),
        attendance=bool(store and store.subscribers),
        resources=dict(state_encoded_bytes=None if state is None else len(packed(state)),state_ceiling_bytes=64*1024*1024,
            sampled_rss_bytes=service.sampled_rss,sampled_highwater_rss_bytes=service.peak_rss,rss_ceiling_bytes=service.config['rss_bytes'],
            subscribers=0 if store is None else len(store.subscribers),pending_notices=0 if store is None else sum(q.qsize() for q in store.subscribers),notice_ceiling_per_stream=1,stream_ceiling=8,
            transport_queue_ceiling=1,transport_queue_sample=None,
            reviews=0 if store is None else len(store.leases),issue_records=len(service.issues),issue_encoded_bytes=len(packed(service.issues)),
            issue_record_ceiling=service.config['issue_records'],issue_byte_ceiling=service.config['issue_bytes']),
        recovery=dict(mode='fresh_service_runtime',expires_reviews=True,requires_attended_board=True,reason=service.recovery_reason()),
        historical_issues=[dict(provider='the_odds_api',affected_venues=['novig'],category='query_offering_gap',
            observed_at='2026-10-03T05:21:49.121844+00:00',scope='NCAAF winner / spread / total; Novig and ProphetX query',
            impact='No Novig rows in this exact retained response. ProphetX supplied 322 quotes across 53 events.',credits=3,
            candidate_digest='ad5ffbe226db5f7593c4918fd1a37babb0a4821334b2a636338e9a6e0e34bd23',
            attempt_id='08bb72c1-9396-4eb5-a177-6d25a3b3f72a',provenance='/api/admin/u4-issue',
            next_action='Investigate at a normally due affordable slot. No universal non-support conclusion.')])
    return raw


def retained_issues(service):
    """Reopen only bounded sanitized operational records, never provider prose."""
    import json
    from .current_policy import SPORTS
    path=service.directory/'issues.json'
    if not path.exists():return []
    if path.is_symlink() or path.stat().st_size>service.config['issue_bytes']:raise ValueError('issue_retention_invalid')
    saved=json.loads(path.read_text())
    if not isinstance(saved,list) or len(saved)>service.config['issue_records']:raise ValueError('issue_retention_invalid')
    result=[]
    for prior in saved:
        if not isinstance(prior,dict) or prior.get('schema') not in ('predict-site-issue-1','predict-site-issue-2'):continue
        venue=prior.get('provider')
        if venue not in (*VENUES,'the_odds_api','service'):continue
        scope=prior.get('scope',{})
        if not isinstance(scope,dict) or set(scope)!= {'sports','families'}:continue
        if not isinstance(scope['sports'],list) or not isinstance(scope['families'],list):continue
        if not scope['sports'] or len(scope['sports'])>6 or any(s not in SPORTS for s in scope['sports']) or any(s not in ('moneyline','spread','total') for s in scope['families']):continue
        if any(not isinstance(prior.get(k),str) or not re.fullmatch(r'[a-f0-9-]{36}',prior[k]) for k in ('runtime_id','attempt_id','issue_id')):continue
        if not isinstance(prior.get('candidate_digest'),str) or not re.fullmatch(r'[a-f0-9]{64}',prior['candidate_digest']):continue
        try:
            if stamp(prior['first_at'])>stamp(prior['last_at']):continue
        except (KeyError,ValueError,TypeError):continue
        # Regenerate prose, site and actions from the local vocabulary. Values
        # from disk cannot introduce arbitrary provider text or endpoint URLs.
        row=issue(service,venue,prior.get('category'),prior.get('code'))
        for k in ('runtime_id','attempt_id','issue_id','candidate_digest','first_at','last_at'):row[k]=prior[k]
        row['scope']=deepcopy(scope)
        count=prior.get('occurrences',1);row['occurrences']=count if type(count) is int and 1<=count<=10**9 else 1
        for k in ('credits','reserved_credits','retry_count'):
            number=prior.get(k)
            row[k]=number if type(number) is int and 0<=number<=500 else None if k!='retry_count' else 0
        affected=prior.get('affected_venues',row['affected_venues'])
        if isinstance(affected,list) and affected and len(affected)<=4 and all(v in VENUES for v in affected):row['affected_venues']=affected
        paths=prior.get('healthy_independent_paths',[])
        row['healthy_independent_paths']=[v for v in paths if v in VENUES and v not in row['affected_venues']][:4] if isinstance(paths,list) else []
        result.append(row)
    while len(packed(result))>service.config['issue_bytes']:result.pop(0)
    return result
