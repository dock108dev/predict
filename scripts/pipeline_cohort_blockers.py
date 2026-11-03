"""Join recovered source events to the independently captured downstream census."""
import json,sys
from pathlib import Path
from collections import Counter

def run(reconciliation,census,target):
 history=json.loads(Path(reconciliation).read_text());current=json.loads(Path(census).read_text())
 rows=current['branch_dispositions']['records'];result=[]
 for event in history['rows']:
  venues={'the_odds_api':{'novig','prophetx','pinnacle'}}.get(event['source'],{event['source']})
  linked=[r for r in rows if r['native_key'][0] in venues and r['native_key'][1]==event['native_event_id']]
  counts=Counter((r['branch'],r['stage'],r['disposition'],r['primary_reason']) for r in linked)
  identities={json.dumps(r['publication'],sort_keys=True) for r in linked if r.get('publication')}
  result.append(dict(source_event_id=event['source_event_id'],source=event['source'],native_event_id=event['native_event_id'],
   publication_disposition=event['current_disposition'],publication_reason=event['current_reason'],
   generation_ids=[g['id'] for g in event['generation_lineage']],
   financial_offer_dispositions=[dict(branch=k[0],stage=k[1],disposition=k[2],reason=k[3],offers=v) for k,v in sorted(counts.items())],
   captured_occurrence_comparison_and_metric_evidence=[json.loads(v) for v in sorted(identities)],
   coverage='normalized offers linked' if linked else 'no current normalized offers found in this census; consult membership snapshot'))
 Path(target).write_text(json.dumps(dict(census_at=current['captured_at'],publication_observation_at=history['frozen_summary']['at'],rows=result,
  limits=['The census and final observer are distinct SQL snapshots; clocks are retained.',
   'Publication eligibility and financial metric eligibility are separate. Offer exclusions are not counts of comparison pairs.']),indent=2))
 print('reconciled historical events',len(result))

if __name__=='__main__':run(*sys.argv[1:])
