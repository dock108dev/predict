"""Supported one-shot independent balance observation under acquisition ownership.

Use from the owned service control or CLI after safe cleanup. No paid request,
retry, missing-receipt search, credential write, or scheduler catch-up occurs here.
"""
import asyncio
from copy import deepcopy
import json
import os
import time
from pathlib import Path
from uuid import uuid4
from app.dashboard.current_contract import packed, stamp
from .current_policy import ROOT, candidate
from .current_conservative import POLICY, AUTHORITY, digest, recovery_preflight
from .current_quota import QuotaLedger, QuotaStop, load_window, owner_runtime


def credential_binding(root=ROOT):
    path=Path(root)/'.env'
    if path.is_symlink() or not path.is_file() or path.stat().st_size>65536:
        raise QuotaStop('recovery_credential_changed')
    s=path.stat()
    return dict(device=s.st_dev,inode=s.st_ino,size=s.st_size,modified_ns=s.st_mtime_ns,changed_ns=s.st_ctime_ns)


def context(ledger, covered, binding, *, root=ROOT, window_loader=load_window):
    v=ledger._read()
    metadata=json.loads((Path(root)/'.local/predict-odds-account.json').read_text())
    if metadata.get('account_id')!=v.get('account_id') or window_loader()!=v['window']:
        raise QuotaStop('recovery_context_mismatch')
    if any(binding['modified_ns']/1e9>=stamp(v['attempts'][aid]['dispatch_at']).timestamp() for aid in covered):
        raise QuotaStop('recovery_credential_changed')
    if credential_binding(root)!=binding:raise QuotaStop('recovery_credential_changed')
    return v


async def observe_and_activate(ledger, owner, candidate_digest, covered, recovery_id,
                               *, root=ROOT, transport=None, key_loader=None, window_loader=load_window):
    from .current_aggregate import CurrentOddsTransport, credential
    if owner is None or owner.file is None:raise QuotaStop('acquisition_ownership_required')
    runtime=owner_runtime(owner)
    recovery_preflight(ledger._read(),ledger.clock(),covered,owner_runtime=runtime,recovery_id=recovery_id)
    binding=credential_binding(root)
    v=context(ledger,covered,binding,root=root,window_loader=window_loader)
    def begin(value,at):
        recovery_preflight(value,at,covered,owner_runtime=runtime,recovery_id=recovery_id)
        if value['window']!=v['window'] or value.get('account_id')!=v.get('account_id'):raise QuotaStop('recovery_context_mismatch')
        probes=value.setdefault('recovery_probes',[])
        if len(probes)>=64:raise QuotaStop('quota_record_capacity')
        if any(p['id']==recovery_id or p['state']=='observing' for p in probes):raise QuotaStop('recovery_observation_consumed')
        probes.append(dict(id=recovery_id,at=at,state='observing',runtime_id=runtime,candidate_digest=candidate_digest,
                           authority=AUTHORITY,covered=deepcopy(covered),credential_binding=binding))
    ledger.transact(begin)
    transport=transport or CurrentOddsTransport()
    from .current_transport_diagnostics import exception_kind, receipt
    started=time.monotonic();phase='credential';primary=None;cleanup=None
    lag=[0.0];last=[started]
    async def monitor():
        while True:
            await asyncio.sleep(0.05)
            tick=time.monotonic();lag[0]=max(lag[0],tick-last[0]-0.05);last[0]=tick
    watcher=asyncio.create_task(monitor())
    def diagnostics():
        r=receipt(getattr(transport,'response_receipt',None))
        transport_phase=getattr(transport,'phase',None)
        return dict(phase=phase,transport_phase=transport_phase if transport_phase in
            ('idle','request_start','dns','connection','awaiting_headers','body','complete') else 'unknown',
            elapsed_seconds=round(time.monotonic()-started,6),max_callback_delay_seconds=round(max(0,lag[0]),6),
            http_status=None if r is None else r['status'],receipt_present=r is not None,
            primary_failure=primary,cleanup=cleanup)
    async def close_transport():
        nonlocal cleanup
        tick=time.monotonic()
        try:
            await asyncio.wait_for(transport.close(),timeout=5)
            cleanup=dict(outcome='closed',elapsed_seconds=round(time.monotonic()-tick,6))
        except BaseException as exc:
            cleanup=dict(outcome='failed',elapsed_seconds=round(time.monotonic()-tick,6),**exception_kind(exc))
            ledger.pause('cleanup_safety_unresolved')
            if isinstance(exc,asyncio.CancelledError):raise
            raise QuotaStop('cleanup_safety_unresolved') from None
    try:
        key=(key_loader or credential)()
        context(ledger,covered,binding,root=root,window_loader=window_loader)
        phase='observation'
        response=await asyncio.wait_for(transport.request(dict(path='/v4/sports',params={}),key),timeout=22)
        phase='validation'
        context(ledger,covered,binding,root=root,window_loader=window_loader)
        from .current_quota import headers
        headers(response['headers'],v['ceiling'])
        if response['status']!=200:raise QuotaStop('aggregate_authentication' if response['status'] in (401,403) else 'recovery_observation_failed')
        from app.reference.odds_acquire import strict_json
        from app.reference.product import SPORT_KEYS
        sports=strict_json(response['body'])
        if not isinstance(sports,list) or len(sports)>512 or any(not isinstance(s,dict) or not isinstance(s.get('key'),str) or type(s.get('active')) is not bool for s in sports):
            raise QuotaStop('aggregate_bootstrap_schema')
        e=dict(schema='predict-independent-balance-1',id=str(uuid4()),purpose=POLICY,
            recovery_id=recovery_id,runtime_id=runtime,candidate_digest=candidate_digest,
            endpoint='https://api.the-odds-api.com/v4/sports',method='GET',params={},
            account_id=v['account_id'],window=deepcopy(v['window']),status=response['status'],
            headers=response['headers'],received_at=response['received_at'],retries=0,documented_cost=0,
            credential_reference='.env',credential_binding=binding,credential_unchanged_since_snapshot=True,
            active_sports=sorted({s['key'] for s in sports if s['active'] and s.get('has_outrights') is False and s['key'] in SPORT_KEYS.values()}),
            documentation='https://the-odds-api.com/liveapi/guides/v4/#get-sports')
        phase='evidence'
        # Durable separate evidence before import; exclusive name, never overwrite.
        directory=ledger.directory/'independent-balances'
        directory.mkdir(mode=0o700,exist_ok=True)
        path=directory/(recovery_id+'.json')
        data=packed(e)
        if len(data)>8192:raise QuotaStop('recovery_evidence_invalid')
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        fd=os.open(directory,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
        phase='cleanup'
        await close_transport()
        phase='activation'
        def activate(value,at):
            from .current_conservative import import_balance
            if credential_binding(root)!=binding:raise QuotaStop('recovery_credential_changed')
            import_balance(value,e,at,covered,owner_runtime=runtime,candidate=candidate_digest,recovery_id=recovery_id)
            probe=next(p for p in value['recovery_probes'] if p['id']==recovery_id)
            probe.update(state='activated',evidence=str(path),evidence_sha256=digest(e),completed_at=at,diagnostics=diagnostics())
        ledger.transact(activate)
        return ledger.snapshot()
    except BaseException as exc:
        failure=str(exc) if isinstance(exc,QuotaStop) else 'recovery_observation_cancelled' if isinstance(exc,asyncio.CancelledError) else 'recovery_observation_failed'
        primary=dict(reason=failure,phase=phase,elapsed_seconds=round(time.monotonic()-started,6),**exception_kind(exc))
        if cleanup is None:
            try:await close_transport()
            except (QuotaStop,asyncio.CancelledError):pass
        def fail(value,at):
            p=next(p for p in value['recovery_probes'] if p['id']==recovery_id)
            p.update(state='failed',reason=failure,completed_at=at,
                     response_receipt=receipt(getattr(transport,'response_receipt',None)),diagnostics=diagnostics())
            if value['pause'] is None:value['pause']=failure
        ledger.transact(fail)
        if isinstance(exc,asyncio.CancelledError):raise
        raise QuotaStop(failure) from None
    finally:
        watcher.cancel()
        await asyncio.gather(watcher,return_exceptions=True)


def main():
    import argparse
    from .local_ownership import LocalOwnership
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--request',required=True,help='Local JSON with recovery_id, candidate_digest and exact covered attempt hashes')
    args=p.parse_args()
    request_path=Path(args.request)
    if request_path.is_symlink() or request_path.stat().st_size>8192:raise QuotaStop('recovery_evidence_invalid')
    request=json.loads(request_path.read_text())
    if set(request)!={'recovery_id','candidate_digest','covered_attempts'} or request['candidate_digest']!=candidate()[0]:
        raise QuotaStop('candidate_changed')
    owner=LocalOwnership();owner.acquire('conservative-recovery-'+str(uuid4()))
    try:
        q=asyncio.run(observe_and_activate(QuotaLedger(),owner,request['candidate_digest'],request['covered_attempts'],request['recovery_id']))
        print(json.dumps(dict(status='activated',remaining=q['remaining'],available=q['available'],held=q['reserved'],next_due_at=q['next_due_at'])))
    finally:owner.release()


if __name__=='__main__':main()
