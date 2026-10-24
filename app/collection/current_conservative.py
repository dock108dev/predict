"""Exact, durable authority for conservative same-account recovery.

Balance evidence never becomes a missing request's charge evidence. Legacy
ledgers have no coverage. All helpers are inert and share the quota transaction.
"""
from copy import deepcopy
from hashlib import sha256
import re
from app.dashboard.current_contract import packed, stamp

POLICY = 'predict-conservative-recovery-1'
AUTHORITY = 'owner-approved-conservative-accounting-20261013'
CAP = 64


def digest(value):
    return sha256(packed(value)).hexdigest()


def validate_audits(v):
    audits = v.get('conservative_recoveries', [])
    if not isinstance(audits, list) or len(audits) > CAP:
        raise ValueError('recovery audit capacity')
    seen = set()
    for a in audits:
        if (a['schema'] != POLICY or a['authority'] != AUTHORITY
                or a['id'] in seen or not isinstance(a['id'], str)
                or len(packed(a)) > 128 * 1024 or not 1 <= len(a['covered']) <= 32
                or a['record_sha256'] != digest({k: x for k, x in a.items() if k != 'record_sha256'})):
            raise ValueError('recovery audit integrity')
        seen.add(a['id'])
        stamp(a['at']); stamp(a['balance']['at'])
        if a['balance']['used'] + a['balance']['remaining'] != a['ceiling']:
            raise ValueError('recovery balance integrity')
        for aid, row in a['covered'].items():
            if row['sha256'] != digest(row['original']) or row['original']['id'] != aid:
                raise ValueError('covered identity integrity')


def applicable(v, audit):
    return (audit['account_id'] == v.get('account_id') and audit['window'] == v['window']
            and audit['ceiling'] == v['ceiling']
            and audit['account_history_sha256'] == digest(v.get('account_transitions', [])))


def covering(v, attempt, *, exact=True):
    for audit in reversed(v.get('conservative_recoveries', [])):
        row = audit['covered'].get(attempt['id'])
        if row and applicable(v, audit):
            if exact and row['sha256'] != digest(attempt):
                continue
            if not exact and any(attempt.get(k) != row['original'].get(k) for k in
                    ('id', 'runtime_id', 'candidate_digest', 'request', 'cost', 'baseline', 'window_id', 'at', 'dispatch_at', 'consumed')):
                continue
            return audit
    return None


def pending_reason(v, *, own_reservation=None):
    """Only dispatch's own reservation is exempt; never another active request."""
    for a in v['attempts'].values():
        if a['state'] not in ('reserved', 'uncertain') or a['id'] == own_reservation:
            continue
        if a['state'] == 'uncertain' and covering(v, a):
            continue
        return 'ambiguous_dispatch_unresolved'
    return None


def exposure(v):
    return sum(a['cost'] if a['state'] in ('reserved', 'uncertain') else a.get('budget_exposure', 0)
               for a in v['attempts'].values())


def recovery_preflight(v, at, covered, *, owner_runtime, recovery_id):
    from .current_quota import QuotaStop
    if v['pause'] not in (None, 'ambiguous_dispatch_unresolved'):
        lost=[a for a in v['attempts'].values() if a['state'] in ('reserved','uncertain')]
        transport=v['pause']=='aggregate_transport_uncertain' and lost and all(covering(v,a) or a.get('interruption')==v['pause'] and a.get('response_receipt') is None and a.get('quota_failure') is None for a in lost)
        # A server error without charge headers is still an unknown charge, not
        # an authentication failure or contradictory balance. Independent balance
        # recovery may cover its exact inactive record while keeping its full hold.
        missing=v['pause']=='quota_missing_duplicate_or_malformed' and lost and all(
            covering(v,a) or (a.get('quota_failure')==v['pause']
                and type((a.get('response_receipt') or {}).get('status')) is int
                and 500 <= a['response_receipt']['status'] <= 599
                and a['response_receipt'].get('headers')==[]
                and a.get('quota_headers')==[])
            for a in lost)
        related=transport or missing
        if not related:raise QuotaStop(v['pause'])
    if not isinstance(recovery_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', recovery_id):
        raise QuotaStop('recovery_identity_invalid')
    if len(v.get('conservative_recoveries', [])) >= CAP:
        raise QuotaStop('quota_record_capacity')
    if any(a['id'] == recovery_id for a in v.get('conservative_recoveries', [])):
        raise QuotaStop('recovery_already_activated')
    if not v['window']:raise QuotaStop('reset_window_unknown')
    pending = {aid: a for aid, a in v['attempts'].items() if a['state'] in ('reserved', 'uncertain')}
    if not isinstance(covered, dict) or not covered or set(covered) != set(pending) or len(covered) > 32:
        raise QuotaStop('recovery_coverage_mismatch')
    for aid, a in pending.items():
        if a['state'] != 'uncertain' or (a['runtime_id'] == owner_runtime and not a.get('interruption')):
            raise QuotaStop('recovery_active_transport')
        if ((stamp(at) - stamp(a['dispatch_at'])).total_seconds() < 120
                or a['window_id'] != v['window']['id'] or covered[aid] != digest(a)):
            raise QuotaStop('recovery_coverage_mismatch')
        if any(stamp(t['at']) >= stamp(a['at']) for t in v.get('account_transitions', [])):
            raise QuotaStop('recovery_context_mismatch')
    return pending


def import_balance(v, evidence, at, covered, *, owner_runtime, candidate, recovery_id):
    from .current_quota import QuotaStop, headers
    pending = recovery_preflight(v, at, covered, owner_runtime=owner_runtime, recovery_id=recovery_id)
    e = evidence
    if len(packed(e))>8192:raise QuotaStop('recovery_evidence_invalid')
    if e.get('active_sports') is not None:
        from app.reference.product import SPORT_KEYS
        if not isinstance(e['active_sports'],list) or len(e['active_sports'])>6 or set(e['active_sports'])-set(SPORT_KEYS.values()):raise QuotaStop('recovery_evidence_invalid')
    if (e.get('schema') != 'predict-independent-balance-1' or e.get('status') != 200
            or e.get('purpose') != POLICY or e.get('account_id') != v.get('account_id')
            or not v.get('account_id') or e.get('window') != v['window']
            or e.get('endpoint') != 'https://api.the-odds-api.com/v4/sports'
            or e.get('method') != 'GET' or e.get('params') != {} or e.get('retries') != 0
            or e.get('documented_cost') != 0 or e.get('credential_reference') != '.env'
            or e.get('credential_unchanged_since_snapshot') is not True
            or e.get('runtime_id') != owner_runtime or e.get('candidate_digest') != candidate
            or e.get('recovery_id') != recovery_id or not e.get('credential_binding')):
        raise QuotaStop('recovery_context_mismatch')
    if (not stamp(v['window']['starts_at']) <= stamp(e['received_at']) <= stamp(at) < stamp(v['window']['ends_at'])
            or not 0 <= (stamp(at) - stamp(e['received_at'])).total_seconds() <= 300
            or any(stamp(e['received_at']) < stamp(a['dispatch_at']) for a in pending.values())):
        raise QuotaStop('recovery_evidence_expired')
    q = headers(e['headers'], v['ceiling'])
    if any(k.lower() not in ('x-requests-used','x-requests-remaining','x-requests-last') for k,val in e['headers']):raise QuotaStop('recovery_evidence_invalid')
    old = v['observation']
    if q['last'] != 0 or not old or q['used'] < old['used'] or q['remaining'] > old['remaining'] or stamp(e['received_at']) < stamp(old['at']):
        raise QuotaStop('quota_counter_or_charge_contradictory')
    balance = dict(q, at=e['received_at'], evidence_sha256=digest(e), recovery_id=recovery_id,
                   kind='independent_authenticated_balance')
    audit = dict(schema=POLICY, authority=AUTHORITY, owner_policy='Owner approved retaining exact unresolved holds and importing independent same-account balance for ordinary scheduled collection', id=recovery_id, at=at,
        runtime_id=owner_runtime, candidate_digest=candidate, account_id=v['account_id'],
        ceiling=v['ceiling'], window=deepcopy(v['window']), account_history_sha256=digest(v.get('account_transitions', [])),
        covered={aid: dict(sha256=digest(a), original=deepcopy(a)) for aid, a in pending.items()},
        evidence=deepcopy(e), evidence_sha256=digest(e), balance=balance,
        prior=dict(pause=v['pause'], observation=deepcopy(old), available=max(0, old['remaining']-exposure(v)-v['engineering_reserve']),
                   next_due_at=v['next_due_at'], bootstrap_due_at=v['bootstrap_due_at']))
    audit['record_sha256'] = digest(audit)
    v.setdefault('conservative_recoveries', []).append(audit)
    v['observation'] = deepcopy(balance)
    v['pause'] = None
    from .current_schedule import schedule
    due=schedule(at)['next_due_at']
    v['next_due_at']=max(stamp(v['next_due_at']),stamp(due)).isoformat() if v['next_due_at'] else due
    if 'active_sports' in e:v['sports_inventory']=dict(active=deepcopy(e['active_sports']),at=e['received_at'],account_id=v['account_id'])
    return audit['id']
