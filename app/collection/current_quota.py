"""Small fail-closed shared operational ledger; never a quote archive.

Every mutation locks/reloads/fsyncs/replaces/fsyncs the directory. Consumers also
hold the common acquisition lock for the entire request/client lifecycle.
"""
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
from uuid import uuid4
from app.dashboard.current_contract import packed, stamp
from .current_policy import ROOT
from .current_aggregate_policy import POLICY
from .current_clock import continuous, boot_evidence

SCHEMA = 'predict-shared-odds-quota-1'
DIRECTORY = ROOT / '.local/predict-odds'
WINDOW_PATH = ROOT / '.local/predict-odds-window.json'
# The historical bootstrap ceiling is retained until an evidenced account transition.
CEILING, RESERVE = 500, POLICY.engineering_reserve
ATTEMPT_CAP=32768


class QuotaStop(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def window(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'id', 'starts_at', 'ends_at', 'evidence', 'evidence_sha256'}:
        raise QuotaStop('reset_window_evidence_invalid')
    if not all(isinstance(value[k], str) and 0 < len(value[k]) <= 2048 for k in value):
        raise QuotaStop('reset_window_evidence_invalid')
    if not re.fullmatch('[a-f0-9]{64}', value['evidence_sha256']):
        raise QuotaStop('reset_window_evidence_invalid')
    duration = (stamp(value['ends_at']) - stamp(value['starts_at'])).total_seconds()
    if not 27*86400 <= duration <= 32*86400:
        raise QuotaStop('reset_window_evidence_invalid')
    return deepcopy(value)


def load_window():
    if not WINDOW_PATH.exists():
        return None
    if WINDOW_PATH.is_symlink() or WINDOW_PATH.stat().st_size > 8192:
        raise QuotaStop('reset_window_evidence_invalid')
    value=window(json.loads(WINDOW_PATH.read_text()))
    evidence=Path(value['evidence'])
    if not evidence.is_absolute() or evidence.is_symlink() or not evidence.is_file() or evidence.stat().st_size>8192 or sha256(evidence.read_bytes()).hexdigest()!=value['evidence_sha256']:
        raise QuotaStop('reset_window_evidence_unverified')
    observed=json.loads(evidence.read_text())
    if observed.get('provider')!='the_odds_api' or observed.get('evidence_kind') not in ('provider_account','owner_account_configuration') or any(observed.get(k)!=value[k] for k in ('starts_at','ends_at')):
        raise QuotaStop('reset_window_evidence_unverified')
    stamp(observed.get('observed_at'))
    return value


def headers(items, ceiling=CEILING):
    result = {}
    for key in ('x-requests-used', 'x-requests-remaining', 'x-requests-last'):
        found = [v for k, v in items if k.lower() == key]
        if len(found) != 1 or not isinstance(found[0], str) or not re.fullmatch(r'[0-9]{1,12}', found[0]):
            raise QuotaStop('quota_missing_duplicate_or_malformed')
        result[key] = int(found[0])
    used, remaining, last = (result[k] for k in ('x-requests-used', 'x-requests-remaining', 'x-requests-last'))
    if used + remaining != ceiling or last > used:
        raise QuotaStop('quota_ceiling_or_headers_contradictory')
    return dict(used=used, remaining=remaining, last=last)


class QuotaLedger:
    def __init__(self, directory=DIRECTORY, *, clock=now, monotonic=None, boot_loader=None):
        self.directory = Path(directory)
        self.clock = clock
        self.monotonic=monotonic if monotonic is not None else continuous if clock is now else None
        self.boot_loader=boot_loader if boot_loader is not None else boot_evidence if clock is now else lambda:None
        self.failed = None

    def _read(self):
        path = self.directory/'quota.json'
        if not path.exists():
            if (self.directory/'initialized').exists():raise QuotaStop('quota_ledger_missing')
            return dict(schema=SCHEMA, ceiling=CEILING, engineering_reserve=RESERVE,
                window=None, windows=[], observation=None, attempts={}, next_due_at=None,
                rotation=0, bootstrap_due_at=None, last_clock=None, clock_anchor=None, pause=None,
                clock_recoveries=[], accounting_epoch=None)
        if path.is_symlink() or path.stat().st_size > 32*1024*1024:
            raise QuotaStop('quota_ledger_corrupt_or_oversize')
        try:
            envelope = json.loads(path.read_text())
            if set(envelope)!={'value','sha256'} or sha256(packed(envelope['value'])).hexdigest()!=envelope['sha256']:raise ValueError()
            value=envelope['value']
            required = {'schema','ceiling','engineering_reserve','window','windows','observation','attempts','next_due_at','rotation','bootstrap_due_at','last_clock','clock_anchor','pause'}
            optional={'clock_recoveries','accounting_epoch','account_transitions','account_id','cycle','sports_inventory','manual_cycle'}
            if required-set(value) or set(value)-required-optional or value['schema'] != SCHEMA or value['ceiling'] not in (CEILING,POLICY.monthly_ceiling) or value['engineering_reserve'] != RESERVE:
                raise ValueError()
            value.setdefault('clock_recoveries',[])
            value.setdefault('accounting_epoch',None)
            if not isinstance(value['clock_recoveries'],list) or len(value['clock_recoveries'])>12:
                raise ValueError()
            epoch=value['accounting_epoch']
            if epoch is not None and (not isinstance(epoch,dict) or epoch.get('state') not in ('awaiting_bootstrap','current') or epoch.get('id') not in [r['id'] for r in value['clock_recoveries']]):
                raise ValueError()
            window(value['window'])
            if not isinstance(value['attempts'], dict) or len(value['attempts']) > ATTEMPT_CAP or not isinstance(value['windows'], list) or len(value['windows']) > 12:
                raise ValueError()
            for aid, a in value['attempts'].items():
                if aid != a['id'] or a['state'] not in ('reserved','uncertain','confirmed','not_dispatched') or type(a['cost']) is not int or not 0 <= a['cost'] <= 30 or a['consumed'] is not True:
                    raise ValueError()
            if type(value['rotation']) is not int or value['rotation'] < 0:
                raise ValueError()
            for k in ('next_due_at','bootstrap_due_at','last_clock'):
                stamp(value[k], True)
            anchor=value['clock_anchor']
            if anchor is not None:
                stamp(anchor['at'])
                if type(anchor['monotonic']) not in (int,float) or not math.isfinite(anchor['monotonic']) or anchor['monotonic']<0:raise ValueError()
                if anchor.get('boot') is not None:
                    boot=anchor['boot'];stamp(boot['started_at'])
                    if not isinstance(boot['id'],str) or not boot['id'] or type(boot['uptime']) not in (int,float) or not math.isfinite(boot['uptime']) or boot['uptime']<0:raise ValueError()
            o=value['observation']
            if o is not None:
                if any(type(o[k]) is not int or o[k]<0 for k in ('used','remaining','last')) or o['used']+o['remaining'] != value['ceiling']:
                    raise ValueError()
                stamp(o['at'])
            return value
        except (ValueError, KeyError, TypeError, AttributeError):
            raise QuotaStop('quota_ledger_corrupt_or_oversize') from None

    def _write(self, value):
        data=packed(dict(value=value,sha256=sha256(packed(value)).hexdigest()))
        if len(data)>32*1024*1024:
            raise QuotaStop('quota_record_capacity')
        path=self.directory/('quota-'+str(uuid4())+'.tmp')
        try:
            fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd,'wb') as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.replace(path,self.directory/'quota.json')
            marker=self.directory/'initialized'
            if not marker.exists():
                fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                try:os.write(fd,b'predict-shared-odds-quota-1');os.fsync(fd)
                finally:os.close(fd)
            fd=os.open(self.directory,os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        finally:
            path.unlink(missing_ok=True)

    def transition_account(self, account):
        """Explicit policy/account epoch; retained attempts never refunded or reused."""
        if (not isinstance(account,dict) or not isinstance(account.get('account_id'),str)
                or not account['account_id'] or type(account.get('monthly_credits')) is not int
                or account['monthly_credits']!=POLICY.monthly_ceiling):
            raise QuotaStop('paid_account_policy_required')
        def change(v,at):
            if any(a['state'] in ('reserved','uncertain') for a in v['attempts'].values()):raise QuotaStop('ambiguous_dispatch_unresolved')
            history=v.setdefault('account_transitions',[])
            if len(history)>=64:raise QuotaStop('account_transition_capacity')
            history.append(dict(at=at,old_account_id=v.get('account_id'),old_ceiling=v['ceiling'],
                old_observation=deepcopy(v['observation']),old_window=deepcopy(v['window']),
                old_pause=v['pause'],old_bootstrap_due_at=v['bootstrap_due_at'],next_due_at=v['next_due_at'],
                account=deepcopy(account),reason='owner_paid_account_policy_transition'))
            v.update(account_id=account['account_id'],ceiling=account['monthly_credits'],observation=None,
                     bootstrap_due_at=None,pause=None)
        self.transact(change,clock_recovery=True)

    def repair_admission(self,evidence):
        """Clear only a parser pause after exact retained-response replay evidence."""
        if not isinstance(evidence,dict) or not evidence.get('replay_verified') or not evidence.get('path'):raise QuotaStop('admission_repair_evidence_required')
        def repair(v,at):
            if v['pause']!='aggregate_admission_failed':raise QuotaStop('admission_repair_pause_mismatch')
            if any(a['state'] in ('reserved','uncertain') for a in v['attempts'].values()):raise QuotaStop('ambiguous_dispatch_unresolved')
            history=v.setdefault('account_transitions',[])
            if len(history)>=64:raise QuotaStop('account_transition_capacity')
            history.append(dict(at=at,reason='retained_admission_repair',old_pause=v['pause'],evidence=deepcopy(evidence),next_due_at=v['next_due_at'],observation=deepcopy(v['observation'])))
            v['pause']=None
        self.transact(repair)

    def repair_credential_selection(self, evidence):
        """Resolve only a returned, zero-cost sports bootstrap on a proven old route.

        Never resolves a paid/transport-uncertain attempt or supplies paid balance.
        Prior bootstrap due is retained in the explicit selection transition.
        """
        def repair(v,at):
            pending=[a for a in v['attempts'].values() if a['state'] in ('reserved','uncertain')]
            if len(pending)!=1:raise QuotaStop('selection_repair_requires_one_free_response')
            a=pending[0]
            if (a['state']!='uncertain' or not a['bootstrap'] or a['cost']!=0 or a['request']!=dict(path='/v4/sports',params={})
                or a.get('quota_failure')!='quota_ceiling_or_headers_contradictory' or not a.get('response_at')
                or v['pause']!='quota_ceiling_or_headers_contradictory'):
                raise QuotaStop('selection_repair_not_a_free_wrong_account_response')
            record=dict(at=at,reason='credential_selection_repair',account_id=v.get('account_id'),evidence=deepcopy(evidence),
                        attempt_id=a['id'],old_bootstrap_due_at=v['bootstrap_due_at'],next_due_at=v['next_due_at'],
                        authority='Correct ordinary paid credential selection after legacy fallback; sports endpoint documented zero credit cost')
            v.setdefault('account_transitions',[]).append(record)
            a.update(state='confirmed',charged=0,reconciled_at=at,account_scope='legacy_fallback_account',
                     accounting_basis='Documented zero-cost sports bootstrap; quota header contradiction retained; paid balance not inferred')
            v.update(bootstrap_due_at=None,pause=None)
        self.transact(repair)

    def confirm_account_window(self, evidence):
        """Rebind same reset dates to fresh owner account evidence, retaining history."""
        evidence=window(evidence)
        def confirm(v,at):
            if any(a['state'] in ('reserved','uncertain') for a in v['attempts'].values()):raise QuotaStop('ambiguous_dispatch_unresolved')
            old=v['window']
            if old is None or any(old[k]!=evidence[k] for k in ('starts_at','ends_at')):raise QuotaStop('account_window_dates_require_transition')
            v.setdefault('account_transitions',[]).append(dict(at=at,reason='paid_reset_window_owner_confirmation',old_window=deepcopy(old),window=deepcopy(evidence),account_id=v.get('account_id'),next_due_at=v['next_due_at']))
            v['window']=deepcopy(evidence)
        self.transact(confirm)

    def record_sports(self, available):
        from app.reference.product import SPORT_KEYS
        if not isinstance(available,list) or set(available)-set(SPORT_KEYS.values()):raise QuotaStop('aggregate_bootstrap_schema')
        def record(v,at):
            v['sports_inventory']=dict(active=sorted(available),at=at,account_id=v.get('account_id'))
        self.transact(record)

    def begin_manual_cycle(self, owner, requests, identity):
        if owner is None or owner.file is None:raise QuotaStop('acquisition_ownership_required')
        if not isinstance(identity,str) or not 1<=len(identity)<=80:raise QuotaStop('manual_refresh_identity_invalid')
        def begin(v,at):
            if v['pause']:raise QuotaStop(v['pause'])
            if any(a['state'] in ('reserved','uncertain') for a in v['attempts'].values()):raise QuotaStop('ambiguous_dispatch_unresolved')
            if any(a.get('cycle_id')==identity for a in v['attempts'].values()):raise QuotaStop('manual_refresh_already_consumed')
            if self.available(v) is None or self.available(v)<POLICY.credits_per_batch*len(requests):raise QuotaStop('quota_reserve_or_exhausted')
            v['manual_cycle']=dict(id=identity,requests=deepcopy(requests),runtime_id=owner_runtime(owner),at=at,authority='Owner clicked on-demand shared Odds API refresh',scheduled_next_due_at=v['next_due_at'])
            return identity
        return self.transact(begin)

    def begin_cycle(self, owner, requests):
        from .current_schedule import schedule
        if owner is None or owner.file is None:raise QuotaStop('acquisition_ownership_required')
        def begin(v,at):
            plan=schedule(at)
            if not plan['open']:raise QuotaStop('aggregate_outside_window')
            if v.get('cycle',{}).get('slot')==plan['slot']:return None
            if v['next_due_at'] and stamp(at)<stamp(v['next_due_at']):return None
            if v['pause']:raise QuotaStop(v['pause'])
            if any(a['state'] in ('reserved','uncertain') for a in v['attempts'].values()):raise QuotaStop('ambiguous_dispatch_unresolved')
            allowance=self.available(v)
            if allowance is None or allowance<POLICY.credits_per_batch*len(requests):raise QuotaStop('quota_reserve_or_exhausted')
            cycle=dict(id=str(uuid4()),slot=plan['slot'],requests=deepcopy(requests),runtime_id=owner_runtime(owner),at=at)
            v['cycle']=cycle;v['next_due_at']=plan['next_due_at']
            return cycle['id']
        return self.transact(begin)

    def _anchor(self, at, mono, boot):
        return dict(at=at,monotonic=mono,boot=deepcopy(boot),clock_kind='suspend_inclusive_v1')

    def _clock_reason(self, value, at, mono, boot):
        if value['last_clock'] and stamp(at)<stamp(value['last_clock']):
            return 'clock_regression'
        anchor=value['clock_anchor']
        if anchor and mono is not None:
            old_boot=anchor.get('boot')
            if self.clock is now and (not boot or not old_boot):
                return 'clock_continuity_unknown'
            if old_boot and (not boot or old_boot['id']!=boot['id']):
                return 'clock_continuity_unknown'
            # A legacy monotonic counter has no supported cross-clock identity.
            if anchor.get('clock_kind') is None and boot is not None:
                return 'clock_continuity_unknown'
            elapsed=mono-anchor['monotonic']
            if elapsed<0 or abs((stamp(at)-stamp(anchor['at'])).total_seconds()-elapsed)>120:
                return 'clock_continuity_unknown'
        return None

    def _restart_reason(self, v, at, mono, boot, evidence):
        if self.failed:return self.failed
        if v['pause'] not in (None,'clock_continuity_unknown'):return v['pause']
        if any(a['state'] in ('reserved','uncertain') for a in v['attempts'].values()):return 'ambiguous_dispatch_unresolved'
        if evidence is None:return 'reset_window_evidence_unverified'
        if not stamp(evidence['starts_at'])<=stamp(at)<stamp(evidence['ends_at']):return 'reset_window_not_current'
        if v['window']!=evidence and (v['window'] is None or stamp(evidence['starts_at'])<stamp(v['window']['ends_at'])):return 'reset_window_evidence_unverified'
        anchor=v['clock_anchor']
        if v['last_clock'] and stamp(at)<stamp(v['last_clock']):return 'clock_regression'
        if not anchor or not boot or mono is None:return 'restart_identity_unknown'
        try:
            age=(stamp(at)-stamp(boot['started_at'])).total_seconds()
            if not boot['id'] or age<0 or abs(age-boot['uptime'])>120 or abs(mono-boot['uptime'])>5:return 'restart_clock_evidence_contradictory'
            if stamp(boot['started_at'])<=stamp(anchor['at']):return 'restart_not_established'
            if anchor.get('boot') and anchor['boot']['id']==boot['id']:return 'restart_not_established'
        except (KeyError,TypeError,ValueError):return 'restart_identity_unknown'
        if len(v['clock_recoveries'])>=12:return 'quota_record_capacity'
        return None

    def prepare_clock(self, owner, candidate, evidence, *, cleanup_safe):
        """Owned, durable epoch transition. It grants only an ordinarily due free
        bootstrap; it never clears spending, attempts, due times or reservations.
        New-process startup holds the exclusive lifecycle lock; in-process
        recovery must finish cleanup before constructing the next scheduler.
        """
        if not cleanup_safe:raise QuotaStop('cleanup_safety_unresolved')
        if owner is None or owner.file is None:raise QuotaStop('acquisition_ownership_required')
        evidence=window(evidence)
        def prepare(v,at):
            mono=self.monotonic() if self.monotonic else None
            boot=self.boot_loader()
            reason=self._clock_reason(v,at,mono,boot)
            if reason is None:
                if v['pause']:raise QuotaStop(v['pause'])
                if any(a['state'] in ('reserved','uncertain') for a in v['attempts'].values()):raise QuotaStop('ambiguous_dispatch_unresolved')
                return
            failure=self._restart_reason(v,at,mono,boot,evidence)
            if failure:raise QuotaStop(failure)
            identity=str(uuid4())
            v['clock_recoveries'].append(dict(id=identity,at=at,old_anchor=deepcopy(v['clock_anchor']),
                old_last_clock=v['last_clock'],old_pause=v['pause'],new_anchor=self._anchor(at,mono,boot),
                runtime_id=owner_runtime(owner),candidate_digest=candidate,account_window=deepcopy(evidence),
                reason='os_evidenced_restart',authority='free_accounting_bootstrap_only'))
            v['clock_anchor']=self._anchor(at,mono,boot)
            v['last_clock']=at
            v['pause']=None
            v['accounting_epoch']=dict(id=identity,state='awaiting_bootstrap',window_id=evidence['id'])
        self.transact(prepare,clock_recovery=True)

    def transact(self, action, *, clock_recovery=False):
        if self.failed:
            raise QuotaStop(self.failed)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd=os.open(self.directory/'quota.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'r+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:
                value=self._read()
                at=self.clock()
                if not clock_recovery:
                    mono=self.monotonic() if self.monotonic else None
                    boot=self.boot_loader() if self.monotonic else None
                    reason=self._clock_reason(value,at,mono,boot)
                    if reason:
                        value['pause']=reason
                        self._write(value)
                        raise QuotaStop(reason)
                    if mono is not None:value['clock_anchor']=self._anchor(at,mono,boot)
                    value['last_clock']=at
                result=action(value, at)
                self._write(value)
                return result
            except OSError:
                self.failed='quota_persistence_failed'
                raise QuotaStop(self.failed) from None

    def snapshot(self):
        try:
            v=self._read()
        except (OSError, QuotaStop):
            return dict(schema=SCHEMA,used=None,remaining=None,reserved=None,available=None,reset=None,next_due_at=None,observation=None,
                unresolved_attempts=None,engineering_reserve=RESERVE,ceiling=CEILING,ledger_byte_ceiling=32*1024*1024,attempt_ceiling=ATTEMPT_CAP,pause='quota_ledger_unavailable')
        unresolved=[a for a in v['attempts'].values() if a['state'] in ('reserved','uncertain')]
        reserved=sum(a['cost'] for a in unresolved)
        o=v['observation']
        return dict(schema=SCHEMA,used=None if o is None else o['used'],remaining=None if o is None else o['remaining'],
            reserved=reserved,available=None if o is None else max(0,o['remaining']-reserved-RESERVE),
            reset=v['window'],next_due_at=v['next_due_at'],rotation=v['rotation'],
            bootstrap_due_at=v['bootstrap_due_at'],observation=deepcopy(o),pause=self.failed or v['pause'],
            attempts=len(v['attempts']),unresolved_attempts=len(unresolved),engineering_reserve=RESERVE,ceiling=v['ceiling'],account_id=v.get('account_id'),account_transitions=deepcopy(v.get('account_transitions',[])),cycle=deepcopy(v.get('cycle')),sports_inventory=deepcopy(v.get('sports_inventory')),
            observation_age_seconds=None if o is None or stamp(self.clock())<stamp(o['at']) else (stamp(self.clock())-stamp(o['at'])).total_seconds(),
            observation_clock_skew=o is not None and stamp(self.clock())<stamp(o['at']),
            ledger_encoded_bytes=len(packed(v)),ledger_byte_ceiling=32*1024*1024,attempt_ceiling=ATTEMPT_CAP,
            last_clock=v['last_clock'],clock_anchor=deepcopy(v['clock_anchor']),
            clock_recoveries=deepcopy(v['clock_recoveries']),accounting_epoch=deepcopy(v['accounting_epoch']))

    def recovery_reason(self, evidence):
        """Read-only preflight; dispatch still locks/rechecks the exact facts."""
        q=self.snapshot()
        if q.get('pause')=='quota_ledger_unavailable':return 'quota_ledger_unavailable'
        v=self._read()
        at=self.clock();mono=self.monotonic() if self.monotonic else None
        boot=self.boot_loader() if self.monotonic else None
        clock_reason=self._clock_reason(v,at,mono,boot)
        if clock_reason:
            return self._restart_reason(v,at,mono,boot,evidence)
        if q.get('pause'):return q['pause']
        if q.get('unresolved_attempts'):return 'ambiguous_dispatch_unresolved'
        if q.get('observation') is None:return 'quota_unknown'
        if evidence is None or evidence!=q.get('reset'):return 'reset_window_evidence_unverified'
        at=self.clock()
        if not stamp(evidence['starts_at'])<=stamp(at)<stamp(evidence['ends_at']):return 'reset_window_not_current'
        if q.get('last_clock') and stamp(at)<stamp(q['last_clock']):return 'clock_regression'
        return None

    def bind_window(self, evidence):
        evidence=window(evidence)
        def bind(v,at):
            if evidence is None: return
            if v['window']==evidence: return
            if not stamp(evidence['starts_at'])<=stamp(at)<stamp(evidence['ends_at']):
                raise QuotaStop('reset_window_not_current')
            if v['window']:
                if stamp(evidence['starts_at'])<stamp(v['window']['ends_at']) or any(a['state'] in ('reserved','uncertain') for a in v['attempts'].values()):
                    raise QuotaStop('reset_transition_unresolved')
                if len(v['windows'])>=12: raise QuotaStop('quota_record_capacity')
                v['windows'].append(dict(window=v['window'],observation=v['observation']))
                v['observation']=None
                v['pause']=None
                # Do not erase next-due: reopening/reset cannot force a catch-up.
            elif v['observation'] and stamp(v['observation']['at'])<stamp(evidence['starts_at']):
                v['observation']=None
            v['window']=evidence
        self.transact(bind)

    @staticmethod
    def available(v):
        o=v['observation']
        reserved=sum(a['cost'] for a in v['attempts'].values() if a['state'] in ('reserved','uncertain'))
        return None if o is None else max(0,o['remaining']-reserved-RESERVE)

    def reserve(self, owner, candidate, request, cost, *, bootstrap=False, qualification=None, cycle_id=None):
        if owner is None or owner.file is None:
            raise QuotaStop('acquisition_ownership_required')
        if type(cost) is not int or not 0<=cost<=30 or bootstrap and cost!=0:
            raise QuotaStop('invalid_reservation')
        def reserve(v,at):
            if len(v['attempts'])>=ATTEMPT_CAP: raise QuotaStop('quota_record_capacity')
            if v['pause']: raise QuotaStop(v['pause'])
            from datetime import timedelta
            diagnostic=False
            if qualification is not None:
                expected={'schema','id','candidate_digest','expires_at','window_id','maximum_credits','maximum_requests','authority'}
                if set(qualification)!=expected or qualification['schema']!='predict-u4-qualification-1' or qualification['candidate_digest']!=candidate or qualification['authority']!='predict-standing-source-u4-20261003' or qualification['maximum_credits']!=3 or qualification['maximum_requests']!=2 or not isinstance(qualification['id'],str):
                    raise QuotaStop('qualification_envelope_invalid')
                if not v['window'] or qualification['window_id']!=v['window']['id'] or not stamp(at)<stamp(qualification['expires_at'])<=stamp(at)+timedelta(minutes=5):
                    raise QuotaStop('qualification_envelope_expired')
                prior=[a for a in v['attempts'].values() if a.get('qualification_id')==qualification['id']]
                if len(prior)>=2 or sum(a['cost'] for a in prior)+cost>3:
                    raise QuotaStop('qualification_envelope_consumed')
                if not bootstrap and (request.get('params',{}).get('bookmakers')!='novig,prophetx' or request['params'].get('markets')!='h2h,spreads,totals' or cost!=3):
                    raise QuotaStop('qualification_scope_invalid')
                diagnostic=True
            if bootstrap:
                if not diagnostic and v['bootstrap_due_at'] and stamp(at)<stamp(v['bootstrap_due_at']):
                    raise QuotaStop('bootstrap_budget_delayed')
                v['bootstrap_due_at']=(stamp(at)+timedelta(hours=6)).isoformat()
            else:
                if v['accounting_epoch'] and v['accounting_epoch']['state']!='current':raise QuotaStop('restart_accounting_refresh_required')
                if v['window'] is None: raise QuotaStop('reset_window_unknown')
                if not stamp(v['window']['starts_at'])<=stamp(at)<stamp(v['window']['ends_at']):
                    raise QuotaStop('reset_window_expired')
                if v['observation'] is None: raise QuotaStop('quota_unknown')
                if any(a['state'] in ('reserved','uncertain') for a in v['attempts'].values()):
                    raise QuotaStop('ambiguous_dispatch_unresolved')
                allowance=self.available(v)
                if allowance < cost: raise QuotaStop('quota_reserve_or_exhausted')
                cycle=next((v.get(kind,{}) for kind in ('cycle','manual_cycle') if v.get(kind,{}).get('id')==cycle_id),{}) if cycle_id is not None else {}
                in_cycle=bool(cycle)
                if in_cycle and (request not in cycle['requests'] or any(a.get('cycle_id')==cycle_id and a['request']==request for a in v['attempts'].values())):raise QuotaStop('cycle_dispatch_duplicate_or_outside_scope')
                if not diagnostic and not in_cycle and v['next_due_at'] and stamp(at)<stamp(v['next_due_at']):
                    raise QuotaStop('aggregate_budget_delayed')
                seconds=(stamp(v['window']['ends_at'])-stamp(at)).total_seconds()
                slots=allowance//max(1,cost)
                interval=max(6*3600,seconds/max(1,slots))
                proposed=stamp(at)+timedelta(seconds=interval)
                if not in_cycle:v['next_due_at']=max(proposed,stamp(v['next_due_at']) if v['next_due_at'] else proposed).isoformat()
                v['rotation']+=1
            aid=str(uuid4())
            v['attempts'][aid]=dict(id=aid,runtime_id=owner_runtime(owner),candidate_digest=candidate,
                authority='predict-standing-source-u4-20261003',request=deepcopy(request),cost=cost,
                baseline=deepcopy(v['observation']),window_id=None if v['window'] is None else v['window']['id'],
                at=at,state='reserved',consumed=True,bootstrap=bootstrap,qualification_id=None if qualification is None else qualification['id'],cycle_id=cycle_id)
            return aid
        return self.transact(reserve)

    def dispatched(self, aid, owner):
        if owner is None or owner.file is None: raise QuotaStop('acquisition_ownership_required')
        def mark(v,at):
            a=v['attempts'][aid]
            if a['state']!='reserved' or v['pause']: raise QuotaStop('dispatch_not_reserved')
            if a['runtime_id']!=owner_runtime(owner):raise QuotaStop('reservation_owner_conflict')
            if not a['bootstrap'] and v['accounting_epoch'] and v['accounting_epoch']['state']!='current':raise QuotaStop('restart_accounting_refresh_required')
            if not a['bootstrap'] and (not v['window'] or not stamp(v['window']['starts_at'])<=stamp(at)<stamp(v['window']['ends_at'])):
                raise QuotaStop('reset_window_expired')
            a['state']='uncertain';a['dispatch_at']=at
        self.transact(mark)

    def reconcile_uncharged(self, owner, aid, evidence_path):
        """Resolve one expired uncertain dispatch only on unchanged usage counters.

        A later free usage observation is distinct from the lost response. Any
        spend, extra pending dispatch, expired window or uncertain identity keeps
        the original reservation. Due times and consumed authority stay intact.
        """
        if owner is None or owner.file is None:raise QuotaStop('acquisition_ownership_required')
        path=Path(evidence_path)
        if not path.is_absolute() or path.is_symlink() or path.stat().st_size>8192:raise QuotaStop('usage_recovery_evidence_invalid')
        raw=path.read_bytes();e=json.loads(raw)
        if e.get('schema')!='predict-usage-observation-1' or e.get('status')!=200 or e.get('endpoint_class')!='sports_bootstrap' or e.get('purpose')!='read_only_usage_recovery':raise QuotaStop('usage_recovery_evidence_invalid')
        def recover(v,at):
            pending=[a for a in v['attempts'].values() if a['state'] in ('reserved','uncertain')]
            if len(pending)!=1 or pending[0]['id']!=aid:raise QuotaStop('ambiguous_dispatch_unresolved')
            a=pending[0];baseline=a.get('baseline');q=headers(e['headers'],v['ceiling'])
            if (a['state']!='uncertain' or not baseline or v['pause'] or not v['window'] or a['window_id']!=v['window']['id']
                or not stamp(v['window']['starts_at'])<=stamp(at)<stamp(v['window']['ends_at'])
                or not 0<=(stamp(at)-stamp(e['received_at'])).total_seconds()<=300
                or (stamp(e['received_at'])-stamp(a['dispatch_at'])).total_seconds()<120
                or q['last']!=0 or any(q[k]!=baseline[k] or q[k]!=v['observation'][k] for k in ('used','remaining'))):
                raise QuotaStop('usage_recovery_not_uncharged')
            a.update(state='confirmed',charged=0,reconciled_at=at,
                recovery=dict(kind='unchanged_provider_usage_after_expired_dispatch',evidence=str(path),sha256=sha256(raw).hexdigest(),received_at=e['received_at'],headers=e['headers']))
            v['observation']=dict(q,at=e['received_at'],attempt_id=aid)
        self.transact(recover)

    def reconcile(self, aid, items):
        def reconcile(v,at):
            a=v['attempts'][aid]
            if a['state']=='confirmed': return # Duplicate response is a no-op.
            if a['state']!='uncertain': raise QuotaStop('response_without_dispatch')
            a['quota_headers']=[[k,val] for k,val in items if k in ('x-requests-used','x-requests-remaining','x-requests-last') and isinstance(val,str) and len(val)<=12 and val.isdigit()]
            try:
                q=headers(items,v['ceiling'])
                previous=v['observation']
                baseline=a['baseline']
                if q['last']>a['cost'] or previous and (q['used']<previous['used'] or q['remaining']>previous['remaining']) or baseline and q['used']-baseline['used']<q['last']:
                    raise QuotaStop('quota_counter_or_charge_contradictory')
                if a['bootstrap'] and q['last']!=0: raise QuotaStop('bootstrap_unexpected_charge')
            except QuotaStop as exc:
                v['pause']=str(exc)
                a['response_at']=at
                a['quota_failure']=str(exc)
                # Valid monotone usage evidence still lowers the ceiling on an
                # unexpected charge; never reclaim the uncertain reservation.
                if 'q' in locals() and (v['observation'] is None or q['used']>=v['observation']['used'] and q['remaining']<=v['observation']['remaining']):
                    v['observation']=dict(q,at=at,attempt_id=aid)
                return
            v['observation']=dict(q,at=at,attempt_id=aid)
            a.update(state='confirmed',charged=q['last'],reconciled_at=at)
            epoch=v['accounting_epoch']
            if epoch and epoch['state']=='awaiting_bootstrap' and a['bootstrap'] and a['window_id']==epoch['window_id'] and stamp(a['dispatch_at'])>=stamp(v['clock_recoveries'][-1]['at']):
                epoch.update(state='current',attempt_id=aid,validated_at=at)
            # Unrelated uncertain attempts remain reserved even after bootstrap.
        self.transact(reconcile)

    def pause(self, reason):
        self.transact(lambda v,at:v.update(pause=reason))


def owner_runtime(owner):
    owner.file.seek(0)
    return json.load(owner.file)['runtime_id']
