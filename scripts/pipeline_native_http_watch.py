"""Try ordinary EV reads when the fixed native observer sees a current frame."""
import gzip,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.pipeline_convergence_report import publication_current
from scripts.pipeline_recovered_reads import read,release

folder=Path(sys.argv[1]);target=Path(sys.argv[2]);ids=set(json.loads((folder/'historical-identities.json').read_text()))
records=json.loads(target.read_text()).get('records',[]) if target.exists() else []
seen={(r['game'],r['generation']) for r in records};start=time.monotonic()
finish_seconds=float(sys.argv[3]) if len(sys.argv)>3 else 1210
while time.monotonic()-start<1500 and len(records)<64:
    files=sorted(folder.glob('sample-*.json*'))
    if files:
        p=files[-1]
        try:s=json.loads(gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes())
        except (OSError,ValueError,EOFError):time.sleep(1);continue
        for pub in s['publications']:
            members=ids.intersection(pub['publication_events'] or [])
            key=(pub['game_key'],pub['generation'])
            if not members or key in seen or not publication_current(pub,s):continue
            seen.add(key);tokens=[]
            try:
                result=read('/api/boards/ev',dict(game=pub['game_key'],filter='all'));v=result.pop('data',{});tokens.append(v.get('read_token'))
                facts={k:v.get(k) for k in ('read_at','calculated_at','economic_revision','background_reasons','calculation_reasons','observation_reasons','comparison_reasons','availability','estimate_availability','error','reason')}
                records.append(dict(sample_at=s['at'],engine=s['engine'],runtime=s['runtime']['runtime_id'],game=pub['game_key'],generation=pub['generation'],
                    source_event_ids=sorted(members),http=result,facts=facts,
                    same_economic_revision=v.get('economic_revision')==pub['economic_revision'],
                    no_frame_refusal=result.get('status')==200 and not v.get('background_reasons') and not v.get('calculation_reasons')))
            finally:release(tokens)
            target.write_text(json.dumps(dict(records=records,limit=64,scope='Observed current original-native financial frames; no frame refusal is not numeric qualification.'),indent=2))
            print(json.dumps(dict(reads=len(records),status=result.get('status'),no_frame_refusal=records[-1]['no_frame_refusal'])),flush=True)
            if len(records)>=64:break
        if s['summary']['elapsed_seconds']>=finish_seconds:break
    time.sleep(2)
if not target.exists():target.write_text(json.dumps(dict(records=[],limit=64)))
