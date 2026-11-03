"""Read selected frozen-cohort publications through the ordinary HTTP API."""
import json,sys,time,urllib.request,urllib.parse,urllib.error
from pathlib import Path
from pipeline_convergence_report import publication_current

def run(source,target):
 records=json.loads(Path(source).read_text())['records'];sample=records[-1]
 stable=set(sample['summary']['stable_ids']);rows=[]
 pubs=[p for p in sample['publications'] if publication_current(p,sample) and stable.intersection(p['publication_events'] or [])]
 for p in pubs:
  for view in ('ev','arbs'):
   started=time.monotonic();url='http://127.0.0.1:8783/api/boards/'+view+'?'+urllib.parse.urlencode(dict(game=p['game_key'],filter='all'))
   try:
    with urllib.request.urlopen(url,timeout=30) as response:value=json.load(response);status=response.status
   except urllib.error.HTTPError as exc:status=exc.code;value=json.load(exc)
   row=dict(view=view,game_key=p['game_key'],source_events=sorted(stable.intersection(p['publication_events'] or [])),seconds=time.monotonic()-started,status=status,
     facts={k:value.get(k) for k in ('read_at','calculated_at','economic_revision','calculation_context','background_reasons','calculation_reasons','observation_reasons','comparison_reasons','estimate_availability','availability','collection','error','reason')},result_rows=len(value.get('rows',[])))
   rows.append(row);Path(target).write_text(json.dumps(dict(captured_sample_at=sample['at'],engine=sample['engine'],eligible_stable=len(stable),selected_valid_publications=len(pubs),reads=rows),indent=2))
   print(json.dumps({k:v for k,v in row.items() if k!='facts'}),flush=True)
if __name__=='__main__':run(*sys.argv[1:])
