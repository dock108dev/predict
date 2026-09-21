"""Read-only audit of one launcher attempt. Does not write retained evidence."""
import argparse
from collections import Counter
import json
from pathlib import Path

from app.collection.delivery_analysis import analyze
from app.collection.delivery_budget import CAP
from app.collection.delivery_manifest import read_json, digest, validate_session_spec
from app.collection.segmented import SegmentedReader
from app.collection.supervised import PROFILE


def fixture_audit(output, start, closed):
    output=Path(output)
    telemetry=read_json(output/'fixture-observations.json')
    rows=telemetry['observations']
    assert telemetry['closed'] is True and len(rows)<=98
    origins=[r for r in rows if r['event']=='origin']
    http=[r for r in rows if r['event']=='http']
    ws=[r for r in rows if r['event']=='ws']
    assert len(origins)==1 and len(ws)==telemetry['ws_calls']==1
    assert 0<=origins[0]['mono']-start<60
    assert len(http)==telemetry['http_calls']<=96
    client=[r for r in SegmentedReader(output/'collector/history').rows() if r['type']=='http_begin']
    assert len(client)==len(http)
    for observed,requested in zip(http,client):
        assert observed['path']==requested['path']
        assert observed['query']=={k:str(v) for k,v in requested['params'].items()}
        assert requested['clock']['mono']<=observed['mono']<=closed
    assert all(origins[0]['mono']<=r['mono']<=closed for r in http+ws)
    return dict(fixture_start_offset_seconds=origins[0]['mono']-start,
                server_http_requests=len(http),server_ws_connections=len(ws))


def audit(output):
    output=Path(output)
    spec=read_json(output/'spec.json');candidate=read_json(output/'candidate.json')
    marker=Path(spec['ownership'])/(spec['attempt']+'.attempt.json')
    bound=read_json(marker);outer=read_json(output/'launcher-result.json')
    assert bound['candidate']==candidate['sha256']==outer['candidate']
    assert bound['spec']==digest(spec)==outer['spec']
    retained=sum(p.stat().st_size for p in output.rglob('*') if p.is_file())+marker.stat().st_size
    assert retained==outer['retained_bytes']<=CAP['output']
    result=dict(candidate=candidate['sha256'],spec=digest(spec),status=outer['status'],retained_bytes=retained)
    if outer['status']=='complete':
        validate_session_spec(read_json(output/'collector/spec.json'),spec)
        receipt=read_json(output/'collector/finalization-resources.json')
        helper=sum(p.stat().st_size for p in output.iterdir() if p.is_file())+marker.stat().st_size
        assert receipt['cumulative_application_file_write_bytes']+helper==outer['cumulative_write_bytes']<=CAP['write_bytes']
        saved=read_json(output/'collector/analysis.json');replay=analyze(output/'collector/history')
        assert saved['replay_state_peak']<=48*1024**2 and replay['replay_state_peak']<=48*1024**2
        assert {k:v for k,v in saved.items() if k!='replay_state_peak'}=={k:v for k,v in replay.items() if k!='replay_state_peak'}
        after=False
        for row in SegmentedReader(output/'collector/history').rows():
            if row['type']=='stop':after=True
            if after:assert not (row['type']=='coverage' and row['usable']) and row['type']!='http_begin'
        result.update(replay=True,write_bytes=outer['cumulative_write_bytes'])
    return result


def qualification(output):
    """Additional full-duration gates. Calling this never starts or regenerates a run."""
    output=Path(output);result=audit(output)
    assert result['status']=='complete'
    outer=read_json(output/'launcher-result.json');spec=read_json(output/'spec.json')
    from app.collection.delivery_manifest import verify
    verify(read_json(output/'candidate.json'),spec)
    events=outer['events'];start=read_json(output/'start.json')['mono']
    sent=next(e for e in events if e['event']=='stop_sent')
    worker=[e['value'] for e in events if e['event']=='worker']
    received=next(e for e in worker if e['event']=='stop_received')
    closed=next(e for e in worker if e['event']=='intake_closed')
    cleanup=next(e for e in worker if e['event']=='cleanup')
    finalized=next(e for e in worker if e['event']=='finalized')
    assert sent['source']==received['source']=='scheduled'
    assert 240<=sent['clock']['mono']-start<=241
    assert 0<=closed['mono']-sent['clock']['mono']<=1
    assert cleanup['cleanup_finished']-closed['mono']<=5
    result.update(fixture_audit(output,start,closed['mono']))
    assert outer['outer_finished']['mono']-start<=660
    receipt=read_json(output/'collector/finalization-resources.json')
    assert receipt['status']=='complete' and receipt['finalization_through_report_seconds']<=240
    summary=read_json(output/'collector/validation.json');a=summary['accounting']
    assert a['received']==a['accepted']+a['rejected'] and a['accepted']==a['durable']==a['drained']
    assert a['pending']==a['unresolved']==a['durable_not_queued']==0
    assert len(set(summary['books'].values()))==1 and summary['books']['received']>0
    counts=Counter();slots=[];raw_bytes=0;raw_frames=0;health=[];selections=[];final=None;sync=None
    for row in SegmentedReader(output/'collector/history').rows():
        counts[row['type']]+=1
        if row['type']=='selection':selections.append(row)
        if row['type']=='coverage' and row['usable'] and sync is None:sync=row['clock']['mono']
        if row['type']=='native_receive':raw_frames+=1;raw_bytes+=row['body_bytes']
        if row['type']=='http_begin' and row['kind']=='reference':slots.append(row['slot'])
        if row['type']=='reference_skipped':slots.append(row['slot'])
        if row['type']=='slots_final':final=row;slots.extend(row['not_reached'])
        if row['type']=='health':health.append(row)
    assert sync is not None and sync-start<=60
    assert len(selections)==2 and [r['kind'] for r in selections]==['initial','refresh']
    assert selections[0]['audit']['selected']==selections[1]['audit']['selected']
    assert 120<=selections[1]['clock']['mono']-start<240
    assert counts['subscription']==1 and finalized['connections']==1
    assert sorted(slots)==list(range(60,300,15))
    assert final and not final['bodies']['pending']
    assert sum(final['requests'].values())==sum(final['results'].values())<=96
    assert final['requests']['initial']<=40 and final['requests']['refresh']<=40 and final['requests']['reference']<=16
    assert final['generations'][0]<=44 and final['generations'][1]<=52
    assert raw_frames>=124 and raw_bytes>=36720  # Retained one-market basis, not regenerated.
    assert a['rss']<=192*1024**2 and receipt['post_report_write_process_high_water_bytes']<=192*1024**2
    assert a['state_peak']<=48*1024**2 and a['queue_peak_objects']<=24 and a['queue_peak_bytes']<=2*1024**2
    warm=[r['rss'] for r in health if r['clock']['mono']-start>=30]
    assert warm and max(warm)-min(warm)<=8*1024**2
    measured={k:a[k] for k in ('logical','frames','encoded_ingress','expanded_ingress')}
    measured['output']=outer['retained_bytes']
    frozen={k:1-v/PROFILE[k] for k,v in measured.items()};diagnostic={k:1-v/CAP[k] for k,v in measured.items()}
    assert min(frozen.values())>=.25
    watcher=[e['value'] for e in events if e['event']=='watchdog' and e['value']['event']=='watchdog_resources']
    assert len(watcher)==1
    resources=[outer['launcher_resources'],finalized['resources'],watcher[0]]
    assert all(r['rss']<256*1024**2 for r in resources) and sum(r['cpu_seconds'] for r in resources)<=600
    result.update(stop_elapsed=closed['mono']-start,cleanup_seconds=cleanup['cleanup_finished']-closed['mono'],
                  frozen_headroom=frozen,diagnostic_headroom=diagnostic,raw_frames=raw_frames,raw_bytes=raw_bytes,
                  qualifications='one-market offline workload only')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);p.add_argument('--qualification',action='store_true');a=p.parse_args()
    print(json.dumps((qualification if a.qualification else audit)(a.output),indent=2))
