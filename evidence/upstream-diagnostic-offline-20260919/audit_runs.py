"""Read-only run audit; writes a new report beside these new diagnostic artifacts."""
import base64
from collections import Counter
import fcntl
import json
from pathlib import Path
import time

from app.collection.delivery_analysis import analyze
from app.collection.delivery_budget import CAP
from app.collection.segmented import SegmentedReader
from app.collection.supervised import PROFILE
from tests.delivery_fixture import NetworkGuard

ROOT=Path(__file__).resolve().parent

def direct():
 p=ROOT/'direct';outer=json.loads((p/'supervisor.json').read_text());v=json.loads((p/'validation.json').read_text())
 events=outer['events'];start=next(x['mono'] for x in events if x['event']=='started')
 stop=next(x for x in events if x['event']=='direct_stop_sent');closed=next(x for x in events if x['event']=='closed')
 assert outer['exitcode']==0 and not outer['cutoff'] and v['cleanup_complete']
 assert 240<=closed['mono']-start<=241 and closed['cleanup_finished']-closed['mono']<=5
 assert 0<=closed['mono']-stop['clock']['mono']<=1
 assert len(set(v['books'].values()))==1
 a=v['accounting'];assert a['received']==a['accepted']+a['rejected'] and a['accepted']==a['durable']==a['drained']
 assert a['pending']==a['unresolved']==a['durable_not_queued']==0
 replay=analyze(p/'history')
 assert replay['replay_state_peak']<=48*1024**2 and v['analysis']['replay_state_peak']<=48*1024**2
 assert {k:x for k,x in v['analysis'].items() if k!='replay_state_peak'}=={k:x for k,x in replay.items() if k!='replay_state_peak'} and v['analysis']['complete']
 counts=Counter();slots=Counter();slot_numbers=[];final=None;health=[];stop_seen=False;after_stop=0;body_bytes=0;raw_frames=0;anchors=[]
 for row in SegmentedReader(p/'history').rows():
  counts[row['type']]+=1
  if row.get('clock'):anchors.append(row['clock'])
  if row['type']=='stop':stop_seen=True
  if row['type']=='coverage' and row['usable'] and stop_seen:after_stop+=1
  if row['type']=='native_receive':raw_frames+=1;body_bytes+=row['body_bytes']
  if row['type']=='http_begin' and row['kind']=='reference':slots['attempted']+=1;slot_numbers.append(row['slot'])
  if row['type']=='reference_skipped':slots['skipped']+=1;slot_numbers.append(row['slot'])
  if row['type']=='slots_final':final=row;slots['not_reached']=len(row['not_reached']);slot_numbers+=row['not_reached']
  if row['type']=='health':health.append(row)
 assert sorted(slot_numbers)==list(range(60,300,15)) and sum(slots.values())==16
 assert sum(final['requests'].values())==sum(final['results'].values()) and not final['bodies']['pending']
 assert final['requests']['reference']<=16 and sum(final['requests'].values())<=96
 assert final['generations'][0]<=44 and final['generations'][1]<=52 and after_stop==0
 assert counts['selection']==2 and counts['subscription']==1
 assert a['rss']<=192*1024**2 and a['state_peak']<=48*1024**2
 assert a['queue_peak_objects']<=24 and a['queue_peak_bytes']<=2*1024**2
 warm=[r['rss'] for r in health if r['clock']['mono']>=start+30]
 growth=max(warm)-min(warm);assert growth<=8*1024**2
 measured=dict(logical=a['logical'],frames=a['frames'],encoded_ingress=a['encoded_ingress'],expanded_ingress=a['expanded_ingress'],output=outer['outer_accounting']['retained_bytes_including_helper_and_marker'])
 frozen_headroom={k:1-n/PROFILE[k] for k,n in measured.items()}
 diagnostic_headroom={k:1-n/CAP[k] for k,n in measured.items()}
 assert min(frozen_headroom.values())>=.25
 basis=json.loads((ROOT/'one-market-load-basis.json').read_text())
 assert raw_frames>=2*basis['max_market_frames'] and body_bytes>=2*basis['max_market_bytes']
 actual=sum(x.stat().st_size for x in p.rglob('*') if x.is_file())
 marker=(ROOT/'ownership'/'261c39b2-8362-4f31-ae55-e8f9037f77ae.attempt.json').stat().st_size
 assert actual+marker==outer['outer_accounting']['retained_bytes_including_helper_and_marker']
 return dict(candidate=json.loads((p/'candidate.json').read_text())['sha256'],direct_stop_elapsed=closed['mono']-start,
  intake_stop_latency=closed['mono']-stop['clock']['mono'],cleanup_seconds=closed['cleanup_finished']-closed['mono'],
  native_frames=raw_frames,native_body_bytes=body_bytes,books=v['books'],slots=dict(slots),requests=final['requests'],
  rss=a['rss'],state_peak=a['state_peak'],queue_peak=a['queue_peak_objects'],post_warmup_rss_growth=growth,
  frozen_headroom=frozen_headroom,diagnostic_headroom=diagnostic_headroom,
  analysis=Counter(r['classification'] for r in v['analysis']['comparisons']),
  stale_reference_samples=sum(r.get('stale_at_send',False) for r in v['analysis']['comparisons']),
  outer=outer['outer_accounting'],clock_max_bracket_uncertainty=max(c['uncertainty'] for c in anchors),
  utc_offset_drift=max(c['utc_offset'] for c in anchors)-min(c['utc_offset'] for c in anchors),
  after_stop_coverage_admissions=after_stop)

def cutoff():
 p=ROOT/'cutoff';outer=json.loads((p/'supervisor.json').read_text());events=outer['events']
 start=next(x['mono'] for x in events if x['event']=='started');end=next(x['clock']['mono'] for x in events if x['event']=='independent_cutoff')
 assert any(x['event']=='stall_entered' for x in events)
 assert outer['cutoff'] and outer['exitcode']!=0 and 300<=end-start<=301
 assert not (p/'finalization-resources.json').exists() and not json.loads((p/'history/manifest.json').read_text())['complete']
 assert not analyze(p/'history')['complete']
 with (ROOT/'ownership'/'collector.lock').open('a') as handle:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
 assert (ROOT/'ownership'/'ed437dd3-c78a-4a1c-a68a-86e3b7ec21cc.attempt.json').exists()
 return dict(candidate=json.loads((p/'candidate.json').read_text())['sha256'],cutoff_elapsed=end-start,
  exitcode=outer['exitcode'],history_complete=False,receipt_present=False,ownership_released=True,attempt_preserved=True,
  outer=outer['outer_accounting'],result='expected forced termination; incomplete suffix and write accounting remain unknown')

if __name__=='__main__':
 with NetworkGuard():
  result=dict(direct=direct(),cutoff=cutoff())
  (ROOT/'run-audit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
