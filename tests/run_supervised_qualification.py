"""Finite fresh-process offline qualification runner. Never calls a venue."""
import asyncio
from collections import Counter
from hashlib import sha256
import ipaddress
import json
from pathlib import Path
import resource
import signal
import socket
import sys
import tempfile
import time
import traceback
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.collection.supervised import NAME,PROFILE
from app.collection.segmented import digest_file
from app.collection.continuous import rss
from tests.supervised_remote_fixture import RemoteRepresentative

def identity():
    paths=sorted(p for base in ('app','tests') for p in (ROOT/base).rglob('*')
                 if p.is_file() and p.suffix in ('.py','.json','.js','.html','.css'))
    hashes={str(p.relative_to(ROOT)):digest_file(p) for p in paths}
    return dict(files=hashes,sha256=sha256(json.dumps(hashes,sort_keys=True,separators=(',',':')).encode()).hexdigest())

async def lifecycle(mode,out):
    f=RemoteRepresentative();checks={}; result={}; started=time.monotonic()
    try:
        o=await f.start(out,duration=300);s=o.session
        initial=s.status_coverage();assert initial['kalshi']['usable']==64 and initial['polymarket_us']['usable']==32,initial
        feed_started=f.feed_started
        while not s.stop_event.is_set():
            elapsed=time.monotonic()-s.started_monotonic
            if mode=='active' and elapsed>=240:
                result['before_stop']=dict(coverage=s.status_coverage(),active_sockets=sum(len(p.groups) for p in s.producers.values()),elapsed=elapsed)
                result['stop_issued_at']=elapsed
                await o.stop();break
            if rss()>=PROFILE['rss']:raise AssertionError('RSS limit')
            if sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>PROFILE['output']+8*1024**2:raise AssertionError('artifact limit')
            await asyncio.sleep(.05)
        await o.finalizer
        fixture=await f.finish_fixture()
        replay=json.loads((s.output/'replay.json').read_text()) if (s.output/'replay.json').exists() else {}
        result.update(outcome=o.mock_result,accounting=s.accounting(),resources=s.resources(),coverage=s.status_coverage(),
            discovery=s.discovery.status(),source_rows=f.rows,source_frames=f.frames,source_books=f.books,
            source_sequence=f.sequence.hexdigest(),fixture_sent_frames=fixture['sent'],fixture_sent_bytes=fixture['sent_bytes'],
            active_seconds=s.closed_at-feed_started,rest_requests=fixture['rest_requests'],connections=fixture['connections'],
            selected_initial=initial,all_fixture_feeds_closed=fixture['closed'],fixture=fixture,
            replay=replay,output_bytes=sum(p.stat().st_size for p in (out/'pilot').rglob('*') if p.is_file()))
        expected='manual_stop' if mode=='active' else 'duration_or_kickoff_cutoff'
        checks['reason']=s.reason==expected
        checks['runtime']=abs(s.collection_seconds-(240 if mode=='active' else 300))<2
        checks['refresh']=s.discovery.published_generation==2 and all(p.applied_generation==2 for p in s.producers.values())
        checks['closed']=s.cleanup_complete and s.queue.qsize()==0 and o.owner_lock is None and fixture['closed'] and not fixture['error']
        pacing={}
        for venue in ('kalshi','polymarket_us'):
            ts=[r['at'] for r in fixture['request_timestamps'] if r['venue']==venue]
            pacing[venue]=dict(requests=len(ts),minimum_interval=min(b-a for a,b in zip(ts,ts[1:])))
        result['pacing']=pacing
        checks['pacing']=all(x['minimum_interval']>=.5 for x in pacing.values()) and [pacing[v]['requests'] for v in ('kalshi','polymarket_us')]==[68,78]
        checks['fixture_budget']=fixture['rss_peak']<128*1024**2
        checks['accounting']=s.counts['received']==s.counts['accepted']+s.counts['rejected'] and s.counts['accepted']==s.counts['durably_acknowledged']==s.persisted==s.delivered
        checks['replay']=o.mock_result['status']=='complete' and replay.get('sequence_sha256')==f.sequence.hexdigest() and replay.get('counts',{}).get('prediction_book')==f.books
        result['traffic_measurement']=dict(frames_per_second=f.frames/result['active_seconds'],flow_encoded=f.flow_encoded,flow_expanded=f.flow_expanded,
            required_encoded=2*(764742+2634748+331508)/23.1797301769*result['active_seconds'],
            required_expanded=2*(1344716+11371300+490683)/23.1797301769*result['active_seconds'])
        checks['busy']=f.frames/result['active_seconds']>=50.13
        checks['real_payload_volume']=f.flow_encoded>=result['traffic_measurement']['required_encoded'] and f.flow_expanded>=result['traffic_measurement']['required_expanded']
        checks['stop_latency']=o.mock_result.get('stop_to_closed_seconds',999)<=5
        checks['finalization']=o.mock_result.get('replay_seconds',999)<=240
        a=s.journal.history.accounting()
        checks['headroom']=all(a[k]<=.75*PROFILE[p] for k,p in [('logical','logical'),('encoded_ingress','encoded_ingress'),('expanded_ingress','expanded_ingress')]) and f.frames<=.75*PROFILE['frames'] and result['output_bytes']<=.75*PROFILE['output'] and rss()<=192*1024**2
        checks['queue']=s.queue.high_items<=24 and s.queue.high_bytes<=2*1024**2
        for kind,samples in [('live',s.state_samples),('replay',o.mock_result.get('replay_state_samples',[]))]:
            checks[kind+'_state']=bool(samples) and max(x['bytes'] for x in samples)<=48*1024**2
            warm=[x['bytes'] for x in samples if (x.get('seconds',100)>=70)]
            checks[kind+'_plateau']=bool(warm) and max(warm)-min(warm)<=8*1024**2
        # Profile construction remains idle and consumed attempt cannot be restarted.
        try:await o.start(duration=300)
        except ValueError:checks['consumed_attempt']=True
        else:checks['consumed_attempt']=False
        result['checks']=checks
        result['passed']=all(checks.values())
    except BaseException:
        result.update(passed=False,error=traceback.format_exc(),checks=checks)
        if f.owner and f.owner.session:
            result.update(reason=f.owner.session.reason,accounting=f.owner.session.accounting())
    finally:
        await f.close()
        result['wall_seconds']=time.monotonic()-started
        result['rss_peak']=rss()
        if f.fixture_result:
            result['combined_process_peak_upper_bound']=rss()+f.fixture_result['rss_peak']
    return result

if __name__=='__main__':
    mode=sys.argv[1];root=Path(sys.argv[2]) if len(sys.argv)>2 else ROOT/'evidence/supervised-5m-20260916'
    out=root/mode;out.mkdir(exist_ok=False)
    (out/'tmp').mkdir();tempfile.tempdir=str(out/'tmp')
    major=mode in ('active','deadline')
    signal.alarm(660 if major else 180)
    resource.setrlimit(resource.RLIMIT_CPU,(600 if major else 180,600 if major else 180))
    resource.setrlimit(resource.RLIMIT_FSIZE,(224*1024**2,224*1024**2))
    original=socket.socket.connect;destinations=Counter()
    def connect(sock,address):
        if not isinstance(address,tuple) or not ipaddress.ip_address(address[0]).is_loopback:raise AssertionError('external network blocked')
        destinations[address[0]]+=1;return original(sock,address)
    before=identity()
    with patch('socket.socket.connect',connect),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials blocked')):
        if major:result=asyncio.run(lifecycle(mode,out))
        else:
            suites={'retained':['tests.test_supervised.Retained','tests.test_segmented.SavedCalculations'],
                    'pacing':['tests.test_supervised_pacing'],
                    'bounds':['tests.test_supervised.Bounds'],
                    'legacy':['tests.test_segmented_collector'],
                    'history':['tests.test_segmented.Segments','tests.test_segmented.CrashBoundaries','tests.test_segmented.Owner']}
            suite=unittest.defaultTestLoader.loadTestsFromNames(suites[mode]);r=unittest.TextTestRunner(verbosity=2).run(suite)
            result=dict(passed=r.wasSuccessful(),tests=r.testsRun,failures=len(r.failures),errors=len(r.errors),rss_peak=rss())
            if mode=='pacing':
                from tests.test_supervised_pacing import TIMESTAMPS, RETRY_EVENTS
                result['request_timestamps']=TIMESTAMPS
                result['retry_events']=RETRY_EVENTS
    result.update(candidate=before,source_unchanged=identity()==before,profile=dict(PROFILE),connected_addresses=dict(destinations))
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('candidate','profile','replay','selected_initial')},indent=2))
    sys.exit(0 if result['passed'] else 1)
