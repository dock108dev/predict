"""Bounded offline replay of diagnostic native inputs, never a delivery guarantee."""
import argparse
import base64
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import quote

from app.adapters.kalshi import Response, decode, parse_market, parse_book
from app.adapters.kalshi_stream import BookReconstructor, RecoveryRequired
from app.dashboard.bounds import retained_bytes
from app.models.core import EvidenceKind
from .coverage import stamp
from .delivery_budget import CAP, MIB
from .segmented import SegmentedReader
from .supervised import bound_native,native_state


def body(row):
    raw=base64.b64decode(row['body_b64'],validate=True)
    if len(raw)>CAP['body'] or sha256(raw).hexdigest()!=row['body_sha256'] or len(raw)!=row['body_bytes']:
        raise ValueError('native_body_identity')
    return raw


def restored(value):
    r=value['raw'];mid=r['ref']['market_id'];eid=r['ref']['event_id']
    response=Response(r['json_text'],r['source'],stamp(r['received_at']),EvidenceKind(r['kind']))
    return parse_market(response,next(m for m in decode(r['json_text'])['markets'] if m['ticker']==mid),eid,'KXNFLGAME')


def analyze_rows(rows,*,complete=True):
    from .delivery_capture import canonical
    market=engine=None;primary=None;primary_id=None;receipt=None;pending=None;active_ref=None
    results=[];local=[];truth=[];mode=None;clock_offset=None;clock_bad=False;terminated=False
    count=0;native_count=0;stale_seen=False;native_digest=sha256();state_peak=0;first_mono=None;last_mono=None
    def close_native():
        nonlocal pending
        if not pending:return
        if pending['expected'] is not None and 'coverage' not in pending['stages']:
            if pending.get('shutdown_rejection'):
                pending=None
                return
            stages=pending['stages']
            missing=next((s for s in ('parser','emission','admission','durable','queue','drain','coverage') if s not in stages),'coverage')
            local.append(dict(classification='local_processing_loss',receive_id=pending['id'],
                body_sha256=pending['hash'],market=market.raw.ref.market_id,expected=pending['expected'],
                boundary=missing,intentional=pending.get('intentional',False),
                basis='valid native replay; expected downstream boundary absent',clock=pending['clock']))
        pending=None
    for row in rows:
        count+=1
        if count>CAP['logical']+1:raise ValueError('analysis_record_cap')
        clock=row.get('clock')
        if clock:
            if first_mono is None:first_mono=clock['mono']
            if last_mono is not None and clock['mono']<last_mono:raise ValueError('monotonic_regression')
            last_mono=clock['mono']
            if clock_offset is None:clock_offset=clock['utc_offset']
            if abs(clock['utc_offset']-clock_offset)>max(.01,clock['uncertainty']*2):clock_bad=True
        kind=row['type']
        if kind=='start':
            if mode is not None or row['mode'] not in ('synthetic','real'):raise ValueError('diagnostic_mode')
            mode=row['mode']
        elif kind=='selection' and engine is None:
            market=restored(row['market'])
            evidence_kind=EvidenceKind.SYNTHETIC if mode=='synthetic' else EvidenceKind.OBSERVATION
            if market.raw.kind!=evidence_kind:raise ValueError('selection_provenance')
            engine=BookReconstructor([market],kind=evidence_kind);bound_native(engine)
        elif kind=='subscription':
            expected=engine.begin(row['command']['id'])
            if expected!=row['command']:raise ValueError('subscription_identity')
        elif kind=='native_receive':
            close_native();raw=body(row);native_count+=1;native_digest.update(raw)
            try:
                book=engine.feed(raw,engine.generation,stamp(row['received']['utc']))
                expected=canonical(book) if book else None
            except RecoveryRequired:expected=None
            pending=dict(id=row['receive_id'],hash=row['body_sha256'],expected=expected,stages=set(),clock=row['received'])
            if expected is not None:
                for t in truth:
                    if t['state']==expected and row['received']['mono']>=t['mono']:t['seen']=True
                if active_ref and expected!=active_ref['primary_state']:active_ref['overlap']=True
        elif kind=='native_stage':
            if not pending or pending['id']!=row['receive_id']:raise ValueError('unlinked_native_stage')
            if row['status'] in ('complete','accepted','inserted'):
                if row['stage']=='emission' and row['state']!=pending['expected']:raise ValueError('reconstruction_mismatch')
                pending['stages'].add(row['stage'])
            if row['status']=='failed':pending['intentional']=row.get('intentional',False)
            if row['status']=='rejected' and row.get('intentional') and row.get('reason')=='intake_closed':
                pending['shutdown_rejection']=True
        elif kind=='coverage':
            if row['usable']:
                if not pending or row['receive_id']!=pending['id'] or pending['expected'] is None:raise ValueError('coverage_without_native')
                if not {'parser','emission','admission','durable','queue','drain'}<=pending['stages']:raise ValueError('coverage_pipeline_gap')
                primary=pending['expected'];primary_id=pending['id'];receipt=row['receipt_mono'];pending['stages'].add('coverage')
            elif row['reason']=='receipt_expiry':stale_seen=True
        elif kind=='http_begin' and row['kind']=='reference':
            if active_ref is not None:raise ValueError('overlapping_references')
            expected_path='/trade-api/v2/markets/'+quote(market.raw.ref.market_id,safe='')+'/orderbook' if market else None
            if row['path']!=expected_path or row['params']!={'depth':20}:raise ValueError('reference_native_identity')
            if row['primary_state']!=primary or row['primary_id']!=primary_id:raise ValueError('reference_primary_lineage')
            active_ref=dict(request_id=row['request_id'],primary_state=primary,primary_id=primary_id,
                receipt_mono=receipt,overlap=False,slot=row['slot'],path=row['path'],params=row['params'])
        elif kind=='http_end':
            raw=body(row)
            if row['kind']!='reference':continue
            if not active_ref or row['request_id']!=active_ref['request_id']:raise ValueError('reference_interval_gap')
            if row['path']!=active_ref['path'] or row['params']!=active_ref['params']:raise ValueError('reference_request_mismatch')
            ref=active_ref;active_ref=None
            # Request identity remains in authoritative HTTP rows, linked by ID;
            # preserve the existing report schema while strengthening validation.
            ref.pop('path');ref.pop('params')
            ref.update(body_sha256=row['body_sha256'],started=row['started'],ended=row['ended'],
                market=market.raw.ref.market_id if market else None,server_state_age=None,
                timing_uncertain=row['timing_uncertain'],headers=row['headers'],classification='insufficient_evidence')
            ref['stale_at_send']=ref['receipt_mono'] is not None and row['started']['mono']-ref['receipt_mono']>30
            try:
                if row['outcome']!='success' or row['status']!=200:raise ValueError('reference_failed')
                state=canonical(parse_book(Response(raw.decode(),row['path'],stamp(row['ended']['utc']),market.raw.kind),market))
                if any(v is None for v in state.values()):raise ValueError('incomparable_sides')
                ref['reference_state']=state
                if ref['overlap'] or row['timing_uncertain'] or clock_bad or primary is None:
                    ref['reason']='timing_overlap_delay_or_missing_baseline'
                else:
                    ref['classification']='sampled_consistency' if state==ref['primary_state'] else 'cross_path_disagreement'
                    ref['reason']='returned images only; exchange time/cache age unknown'
            except (ValueError,KeyError,TypeError):ref['reason']='failed_or_incomparable_reference'
            results.append(ref)
            if len(results)>16:raise ValueError('reference_analysis_cap')
        elif kind=='fixture_truth':
            # Never accept authoritativeness from a REST timestamp/header.
            if mode!='synthetic' or row.get('authority')!='controlled-native-fixture-v1':raise ValueError('untrusted_change_authority')
            if len(truth)>=16:raise ValueError('fixture_truth_cap')
            truth.append(dict(state=row['state'],mono=row['change_mono'],seen=False,
                authoritative=row.get('ordered') is True and first_mono<=row['change_mono']<=row['clock']['mono']
                    and primary is not None and row['state']!=primary and engine.sid is not None,
                record_id=row['ingress_id'],market=row['market']))
        elif kind=='session_finished':terminated=True
        if len(local)>16:raise ValueError('local_failure_cap')
        state_peak=max(state_peak,retained_bytes((native_state(engine) if engine else {},primary,pending,results,truth,local)))
        if state_peak>48*MIB:raise ValueError('replay_state_cap')
    close_native()
    if active_ref:
        results.append(dict(classification='insufficient_evidence',reason='unfinished_reference',request_id=active_ref['request_id']))
    valid=complete and terminated and not clock_bad
    for t in truth:
        if t['authoritative'] and not t['seen'] and valid and not local and engine and engine.sid is not None and primary is not None and t['market']==market.raw.ref.market_id:
            results.append(dict(classification='synthetic_missing_change',fixture_record=t['record_id'],state=t['state'],
                change_mono=t['mono'],market=t['market'],reason='controlled fixture change absent through captured end; synthetic only'))
    if not valid:
        for r in results:r.update(classification='insufficient_evidence',reason='incomplete_history_or_clock_uncertainty')
        # A retained prefix can still prove a local boundary, but not its absent suffix.
        local=[dict(r,classification='insufficient_evidence',reason='incomplete_history') for r in local]
    if not results and not local:results=[dict(classification='insufficient_evidence',reason='no_comparable_reference_or_demonstrated_local_loss')]
    return dict(schema='delivery-analysis-v1',complete=valid,records=count,native_frames=native_count,
        native_sha256=native_digest.hexdigest(),stale_seen=stale_seen,clock_uncertain=clock_bad,
        comparisons=results,local=local,replay_state_peak=state_peak,
        limitations=['REST state age/order unknown','agreement does not prove uninterrupted delivery',
                    'no exchange completeness or sustained capacity claim'])


def analyze(folder):
    reader=SegmentedReader(folder)
    # A corrupt or interrupted input is not silently promoted via tail salvage.
    try:return analyze_rows(reader.rows())
    except (ValueError,OSError) as exc:
        return dict(schema='delivery-analysis-v1',complete=False,comparisons=[dict(
            classification='insufficient_evidence',reason=type(exc).__name__+':'+str(exc))],local=[])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('history',type=Path)
    args=p.parse_args();print(json.dumps(analyze(args.history),indent=2))


if __name__=='__main__':main()
