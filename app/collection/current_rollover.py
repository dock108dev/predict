"""Evidenced same-account rollover, retaining every historical charge hold.

Account-window evidence is private owner/provider evidence, not inferred from
calendar dates or response counters. A fresh owned sports observation supplies
current capacity; neither source settles historical unknown charges.
"""
from copy import deepcopy
import json
import re
from pathlib import Path
from .current_conservative import AUTHORITY, POLICY, CAP, digest, covering, exposure
from .current_quota import QuotaStop, headers, window
from app.dashboard.current_contract import stamp


def preflight(v, at, covered, *, owner_runtime, recovery_id, new_window, binding):
    w = window(new_window)
    if not w or not v['window'] or not v.get('account_id'):
        raise QuotaStop('rollover_account_evidence_required')
    if not isinstance(recovery_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', recovery_id):
        raise QuotaStop('recovery_identity_invalid')
    audits = v.get('conservative_recoveries', [])
    if any(a['id'] == recovery_id or a.get('rollover', {}).get('window_evidence_sha256') == w['evidence_sha256'] for a in audits):
        raise QuotaStop('recovery_already_activated')
    if len(audits) >= CAP or len(v['windows']) >= 12:
        raise QuotaStop('quota_record_capacity')
    if (w['id'] == v['window']['id'] or stamp(w['starts_at']) < stamp(v['window']['ends_at'])
            or not stamp(w['starts_at']) <= stamp(at) < stamp(w['ends_at'])):
        raise QuotaStop('rollover_window_unsupported')
    if not v['observation'] or stamp(v['observation']['at']) >= stamp(w['starts_at']):
        raise QuotaStop('rollover_unexplained_counter_change')
    try:
        p = Path(w['evidence'])
        if not p.is_absolute() or p.is_symlink() or p.stat().st_size > 8192:
            raise ValueError()
        raw = p.read_bytes()
        from hashlib import sha256
        if sha256(raw).hexdigest() != w['evidence_sha256']:
            raise ValueError()
        e = json.loads(raw)
        if (e.get('provider') != 'the_odds_api'
                or e.get('evidence_kind') not in ('provider_account', 'owner_account_configuration')
                or e.get('account_id') != v['account_id']
                or e.get('monthly_credits') != v['ceiling']
                or e.get('credential_binding') != binding
                or e.get('same_account_confirmed') is not True
                or not isinstance(e.get('provenance'), str) or not e['provenance'].strip()
                or any(e.get(k) != w[k] for k in ('starts_at', 'ends_at'))):
            raise ValueError()
    except (OSError, ValueError, TypeError, KeyError):
        raise QuotaStop('rollover_account_evidence_required') from None
    if not (stamp(w['starts_at']) <= stamp(e['observed_at']) <= stamp(at)
            and 0 <= (stamp(at) - stamp(e['observed_at'])).total_seconds() <= 86400):
        raise QuotaStop('recovery_evidence_expired')
    if not audits or audits[-1]['evidence']['credential_binding'] != binding:
        raise QuotaStop('recovery_credential_changed')
    if v['pause'] not in (None, 'ambiguous_dispatch_unresolved', 'quota_counter_or_charge_contradictory'):
        raise QuotaStop(v['pause'])
    pending = {aid:a for aid,a in v['attempts'].items() if a['state'] in ('reserved','uncertain')}
    if not pending or len(pending) > 32 or covered != {aid:digest(a) for aid,a in pending.items()}:
        raise QuotaStop('recovery_coverage_mismatch')
    unexplained = []
    for a in pending.values():
        if (a['state'] != 'uncertain' or a['runtime_id'] == owner_runtime
                or (stamp(at)-stamp(a['dispatch_at'])).total_seconds() < 120):
            raise QuotaStop('recovery_active_transport')
        if covering(v, a):
            if stamp(a['dispatch_at']) >= stamp(w['starts_at']):
                raise QuotaStop('rollover_unexplained_counter_change')
            continue
        # Only the retained, zero-cost, post-expiry bootstrap can explain this
        # pause. No general exemption for counter decreases or unknown requests.
        r = a.get('response_receipt') or {}
        q = headers(r.get('headers'), v['ceiling'])
        if (not a.get('bootstrap') or a['cost'] != 0
                or a['request'] != dict(path='/v4/sports', params={})
                or a.get('quota_failure') != 'quota_counter_or_charge_contradictory'
                or r.get('status') != 200 or q['last'] != 0
                or not stamp(w['starts_at']) <= stamp(a['dispatch_at']) <= stamp(r['received_at']) <= stamp(at)
                or not stamp(r['received_at']) < stamp(w['ends_at'])
                or a['window_id'] != v['window']['id']):
            raise QuotaStop('rollover_unexplained_counter_change')
        unexplained.append((r, q))
    if v['pause'] == 'quota_counter_or_charge_contradictory' and not unexplained:
        raise QuotaStop('rollover_unexplained_counter_change')
    if any(p.get('state') == 'observing' and p['id'] != recovery_id for p in v.get('recovery_probes', [])):
        raise QuotaStop('recovery_active_transport')
    return pending, e, unexplained


def import_rollover(v, e, at, covered, *, owner_runtime, candidate, recovery_id, new_window, binding):
    pending, account, prior_receipts = preflight(v, at, covered, owner_runtime=owner_runtime,
        recovery_id=recovery_id, new_window=new_window, binding=binding)
    if (e.get('schema') != 'predict-independent-balance-1' or e.get('purpose') != POLICY
            or e.get('account_id') != v['account_id'] or e.get('window') != new_window
            or e.get('runtime_id') != owner_runtime or e.get('candidate_digest') != candidate
            or e.get('recovery_id') != recovery_id or e.get('credential_binding') != binding
            or e.get('credential_unchanged_since_snapshot') is not True
            or e.get('credential_reference') != '.env' or e.get('status') != 200
            or e.get('endpoint') != 'https://api.the-odds-api.com/v4/sports'
            or e.get('method') != 'GET' or e.get('params') != {} or e.get('retries') != 0
            or e.get('documented_cost') != 0):
        raise QuotaStop('recovery_context_mismatch')
    if not (stamp(new_window['starts_at']) <= stamp(e['received_at']) <= stamp(at) < stamp(new_window['ends_at'])
            and 0 <= (stamp(at)-stamp(e['received_at'])).total_seconds() <= 300):
        raise QuotaStop('recovery_evidence_expired')
    q = headers(e['headers'], v['ceiling'])
    if q['last'] != 0 or any(stamp(e['received_at']) < stamp(r['received_at']) or q['used'] < old['used'] for r,old in prior_receipts):
        raise QuotaStop('quota_counter_or_charge_contradictory')
    if any(stamp(e['received_at']) < stamp(a['dispatch_at']) for a in pending.values()):
        raise QuotaStop('recovery_evidence_expired')
    balance = dict(q, at=e['received_at'], evidence_sha256=digest(e), recovery_id=recovery_id,
                   kind='independent_authenticated_balance')
    old = dict(window=deepcopy(v['window']), observation=deepcopy(v['observation']))
    audit = dict(schema=POLICY, authority=AUTHORITY, id=recovery_id, at=at,
        runtime_id=owner_runtime, candidate_digest=candidate, account_id=v['account_id'],
        ceiling=v['ceiling'], window=deepcopy(new_window),
        account_history_sha256=digest(v.get('account_transitions', [])),
        covered={aid:dict(sha256=digest(a), original=deepcopy(a)) for aid,a in pending.items()},
        evidence=deepcopy(e), evidence_sha256=digest(e), balance=balance,
        prior=dict(old, pause=v['pause'], next_due_at=v['next_due_at'], bootstrap_due_at=v['bootstrap_due_at']),
        rollover=dict(window_evidence_sha256=new_window['evidence_sha256'], account_evidence=account,
                      retained_exposure=exposure(v), historical_charges_resolved=False))
    audit['record_sha256'] = digest(audit)
    v.setdefault('conservative_recoveries', []).append(audit)
    v['windows'].append(old)
    v.update(window=deepcopy(new_window), observation=deepcopy(balance), pause=None)
    # Existing due times are lower bounds; never force overdue catch-up work.
    from .current_schedule import schedule
    due = schedule(at)['next_due_at']
    v['next_due_at'] = max(stamp(v['next_due_at']), stamp(due)).isoformat() if v['next_due_at'] else due
    # A clock-recovery epoch remains untouched; its own bootstrap is still due.
    return audit['id']
