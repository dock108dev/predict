"""Small fail-closed shared operational ledger; never a quote archive.

Every mutation locks/reloads/fsyncs/replaces/fsyncs the directory. Consumers also
hold the common acquisition lock for the entire request/client lifecycle.
"""
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4
from app.dashboard.current_contract import packed, stamp
from .current_policy import ROOT

SCHEMA = 'predict-shared-odds-quota-1'
DIRECTORY = ROOT / '.local/predict-odds'
WINDOW_PATH = ROOT / '.local/predict-odds-window.json'
CEILING, RESERVE = 500, 50


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


def headers(items):
    result = {}
    for key in ('x-requests-used', 'x-requests-remaining', 'x-requests-last'):
        found = [v for k, v in items if k.lower() == key]
        if len(found) != 1 or not isinstance(found[0], str) or not re.fullmatch(r'[0-9]{1,12}', found[0]):
            raise QuotaStop('quota_missing_duplicate_or_malformed')
        result[key] = int(found[0])
    used, remaining, last = (result[k] for k in ('x-requests-used', 'x-requests-remaining', 'x-requests-last'))
    if used + remaining != CEILING or last > used:
        raise QuotaStop('quota_ceiling_or_headers_contradictory')
    return dict(used=used, remaining=remaining, last=last)


class QuotaLedger:
    def __init__(self, directory=DIRECTORY, *, clock=now, monotonic=None):
        self.directory = Path(directory)
        self.clock = clock
        self.monotonic=monotonic if monotonic is not None else time.monotonic if clock is now else None
        self.failed = None

    def _read(self):
        path = self.directory/'quota.json'
        if not path.exists():
            if (self.directory/'initialized').exists():raise QuotaStop('quota_ledger_missing')
            return dict(schema=SCHEMA, ceiling=CEILING, engineering_reserve=RESERVE,
                window=None, windows=[], observation=None, attempts={}, next_due_at=None,
                rotation=0, bootstrap_due_at=None, last_clock=None, clock_anchor=None, pause=None)
        if path.is_symlink() or path.stat().st_size > 512*1024:
            raise QuotaStop('quota_ledger_corrupt_or_oversize')
        try:
            envelope = json.loads(path.read_text())
            if set(envelope)!={'value','sha256'} or sha256(packed(envelope['value'])).hexdigest()!=envelope['sha256']:raise ValueError()
            value=envelope['value']
            required = {'schema','ceiling','engineering_reserve','window','windows','observation','attempts','next_due_at','rotation','bootstrap_due_at','last_clock','clock_anchor','pause'}
            if set(value) != required or value['schema'] != SCHEMA or value['ceiling'] != CEILING or value['engineering_reserve'] != RESERVE:
                raise ValueError()
            window(value['window'])
            if not isinstance(value['attempts'], dict) or len(value['attempts']) > 512 or not isinstance(value['windows'], list) or len(value['windows']) > 12:
                raise ValueError()
            for aid, a in value['attempts'].items():
                if aid != a['id'] or a['state'] not in ('reserved','uncertain','confirmed','not_dispatched') or type(a['cost']) is not int or not 0 <= a['cost'] <= 30 or a['consumed'] is not True:
                    raise ValueError()
            if type(value['rotation']) is not int or value['rotation'] < 0:
                raise ValueError()
            for k in ('next_due_at','bootstrap_due_at','last_clock'):
                stamp(value[k], True)
            o=value['observation']
            if o is not None:
                if any(type(o[k]) is not int or o[k]<0 for k in ('used','remaining','last')) or o['used']+o['remaining'] != CEILING:
                    raise ValueError()
                stamp(o['at'])
            return value
        except (ValueError, KeyError, TypeError, AttributeError):
            raise QuotaStop('quota_ledger_corrupt_or_oversize') from None

    def _write(self, value):
        data=packed(dict(value=value,sha256=sha256(packed(value)).hexdigest()))
        if len(data)>512*1024:
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

    def transact(self, action):
        if self.failed:
            raise QuotaStop(self.failed)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd=os.open(self.directory/'quota.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'r+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:
                value=self._read()
                at=self.clock()
                if self.monotonic is not None:
                    mono=self.monotonic();anchor=value['clock_anchor']
                    value['clock_anchor']=dict(at=at,monotonic=mono)
                    if anchor and (mono<anchor['monotonic'] or abs((stamp(at)-stamp(anchor['at'])).total_seconds()-(mono-anchor['monotonic']))>120):
                        value['pause']='clock_continuity_unknown'
                        self._write(value)
                        raise QuotaStop('clock_continuity_unknown')
                if value['last_clock'] and stamp(at)<stamp(value['last_clock']):
                    value['pause']='clock_regression'
                    self._write(value)
                    raise QuotaStop('clock_regression')
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
                unresolved_attempts=None,engineering_reserve=RESERVE,ceiling=CEILING,ledger_byte_ceiling=512*1024,attempt_ceiling=512,pause='quota_ledger_unavailable')
        unresolved=[a for a in v['attempts'].values() if a['state'] in ('reserved','uncertain')]
        reserved=sum(a['cost'] for a in unresolved)
        o=v['observation']
        return dict(schema=SCHEMA,used=None if o is None else o['used'],remaining=None if o is None else o['remaining'],
            reserved=reserved,available=None if o is None else max(0,o['remaining']-reserved-RESERVE),
            reset=v['window'],next_due_at=v['next_due_at'],rotation=v['rotation'],
            bootstrap_due_at=v['bootstrap_due_at'],observation=deepcopy(o),pause=self.failed or v['pause'],
            attempts=len(v['attempts']),unresolved_attempts=len(unresolved),engineering_reserve=RESERVE,ceiling=CEILING,
            observation_age_seconds=None if o is None or stamp(self.clock())<stamp(o['at']) else (stamp(self.clock())-stamp(o['at'])).total_seconds(),
            observation_clock_skew=o is not None and stamp(self.clock())<stamp(o['at']),
            ledger_encoded_bytes=len(packed(v)),ledger_byte_ceiling=512*1024,attempt_ceiling=512,
            last_clock=v['last_clock'],clock_anchor=deepcopy(v['clock_anchor']))

    def recovery_reason(self, evidence):
        """Read-only preflight; dispatch still locks/rechecks the exact facts."""
        q=self.snapshot()
        if q.get('pause'):return q['pause']
        if q.get('unresolved_attempts'):return 'ambiguous_dispatch_unresolved'
        if q.get('observation') is None:return 'quota_unknown'
        if evidence is None or evidence!=q.get('reset'):return 'reset_window_evidence_unverified'
        at=self.clock()
        if not stamp(evidence['starts_at'])<=stamp(at)<stamp(evidence['ends_at']):return 'reset_window_not_current'
        if q.get('last_clock') and stamp(at)<stamp(q['last_clock']):return 'clock_regression'
        anchor=q.get('clock_anchor')
        if anchor and self.monotonic is not None:
            elapsed=self.monotonic()-anchor['monotonic']
            if elapsed<0 or abs((stamp(at)-stamp(anchor['at'])).total_seconds()-elapsed)>120:return 'clock_continuity_unknown'
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

    def reserve(self, owner, candidate, request, cost, *, bootstrap=False, qualification=None):
        if owner is None or owner.file is None:
            raise QuotaStop('acquisition_ownership_required')
        if type(cost) is not int or not 0<=cost<=30 or bootstrap and cost!=0:
            raise QuotaStop('invalid_reservation')
        def reserve(v,at):
            if len(v['attempts'])>=512: raise QuotaStop('quota_record_capacity')
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
                if v['window'] is None: raise QuotaStop('reset_window_unknown')
                if not stamp(v['window']['starts_at'])<=stamp(at)<stamp(v['window']['ends_at']):
                    raise QuotaStop('reset_window_expired')
                if v['observation'] is None: raise QuotaStop('quota_unknown')
                if any(a['state'] in ('reserved','uncertain') for a in v['attempts'].values()):
                    raise QuotaStop('ambiguous_dispatch_unresolved')
                allowance=self.available(v)
                if allowance < cost: raise QuotaStop('quota_reserve_or_exhausted')
                if not diagnostic and v['next_due_at'] and stamp(at)<stamp(v['next_due_at']):
                    raise QuotaStop('aggregate_budget_delayed')
                seconds=(stamp(v['window']['ends_at'])-stamp(at)).total_seconds()
                slots=allowance//max(1,cost)
                interval=max(6*3600,seconds/max(1,slots))
                proposed=stamp(at)+timedelta(seconds=interval)
                v['next_due_at']=max(proposed,stamp(v['next_due_at']) if v['next_due_at'] else proposed).isoformat()
                v['rotation']+=1
            aid=str(uuid4())
            v['attempts'][aid]=dict(id=aid,runtime_id=owner_runtime(owner),candidate_digest=candidate,
                authority='predict-standing-source-u4-20261003',request=deepcopy(request),cost=cost,
                baseline=deepcopy(v['observation']),window_id=None if v['window'] is None else v['window']['id'],
                at=at,state='reserved',consumed=True,bootstrap=bootstrap,qualification_id=None if qualification is None else qualification['id'])
            return aid
        return self.transact(reserve)

    def dispatched(self, aid, owner):
        if owner is None or owner.file is None: raise QuotaStop('acquisition_ownership_required')
        def mark(v,at):
            a=v['attempts'][aid]
            if a['state']!='reserved' or v['pause']: raise QuotaStop('dispatch_not_reserved')
            if not a['bootstrap'] and (not v['window'] or not stamp(v['window']['starts_at'])<=stamp(at)<stamp(v['window']['ends_at'])):
                raise QuotaStop('reset_window_expired')
            a['state']='uncertain';a['dispatch_at']=at
        self.transact(mark)

    def reconcile(self, aid, items):
        def reconcile(v,at):
            a=v['attempts'][aid]
            if a['state']=='confirmed': return # Duplicate response is a no-op.
            if a['state']!='uncertain': raise QuotaStop('response_without_dispatch')
            try:
                q=headers(items)
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
            # Unrelated uncertain attempts remain reserved even after bootstrap.
        self.transact(reconcile)

    def pause(self, reason):
        self.transact(lambda v,at:v.update(pause=reason))


def owner_runtime(owner):
    owner.file.seek(0)
    return json.load(owner.file)['runtime_id']
