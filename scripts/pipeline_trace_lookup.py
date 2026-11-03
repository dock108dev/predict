"""Drill into a saved coherent census by source and native record/peer identity."""
import argparse,json
p=argparse.ArgumentParser(description=__doc__);p.add_argument('snapshot');p.add_argument('--source');p.add_argument('--identity',required=True)
a=p.parse_args();v=json.load(open(a.snapshot));found=[]
for section in ('native_receipt_trace','branch_dispositions'):
 for r in (v.get(section) or {}).get('records',[]):
  source=r.get('source') or r.get('native_key',[None])[0]
  if (not a.source or source==a.source) and a.identity in json.dumps(r):found.append(dict(population=section,**r))
print(json.dumps(dict(captured_at=v['captured_at'],records=found),indent=2))
