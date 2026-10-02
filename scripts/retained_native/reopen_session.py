"""Fresh-process, version-bound original and derived reopening with wire-price checks."""
import json,sys
from pathlib import Path
from decimal import Decimal as D
from app.dashboard.session_history import load
from app.dashboard.session_projection import stable
from app.dashboard.price_comparison import comparisons,comparisons_for_game
OUT=Path('evidence/native-retained-coverage-20260930-v1');sid=sys.argv[1];audit=json.loads((OUT/'sessions'/(sid+'.json')).read_text());folder=audit['folder'];old=None;old_error=None
try:
 old=load(folder,native_interpretation='native-book-comparison-3');assert stable(old)==audit['original_projection_sha256'],'Original sealed projection changed'
except ValueError as exc:
 if not audit.get('projection_error'):raise
 assert str(exc)==audit['projection_error'];old_error=str(exc)
new=load(folder);rows=comparisons(new,{});oracle_path=OUT/'oracles'/(sid+'.json');checked=0
if oracle_path.exists():
 oracle=json.loads(oracle_path.read_text())
 for g in new['games']:
  if not g.get('native_raw'):continue
  for r in comparisons_for_game(new,{},g['id']):
   for leg in r['legs']:
    native=leg['native_identity'];key='|'.join((leg['venue'],native['event_id'],native['market_id']));expected=oracle['latest_purchases'][key][leg['side']]
    assert [(D(l['price']),D(l['quantity'])) for l in leg['levels'] or []]==[(D(l['price']),D(l['quantity'])) for l in expected]
    if expected:assert D(leg['ask'])==D(expected[0]['price']) and D(leg['top_size'])==D(expected[0]['quantity'])
    assert leg['entry']['upper'] is None or sid=='3363b035-4a97-43df-bae8-57426e873514'
    checked+=1
 # The original book oracles are scoped to this exact SID, never another capture.
assert all(r.get('net') is None and r.get('ev') is None for r in rows if r.get('native_raw'))
(OUT/'derived').mkdir(exist_ok=True);path=OUT/'derived'/(sid+'.json');value=dict(snapshot=new,comparisons=rows)
if '--check' in sys.argv:assert stable(value)==stable(json.loads(path.read_text())),'Fresh derived output differs'
else:path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
report=dict(session_id=sid,original_v3_sha256=None if old is None else stable(old),original_failure=old_error,derived_v4_sha256=stable(new),serialized_sha256=stable(value),games=len(new['games']),native_games=sum(bool(g.get('native_raw')) for g in new['games']),native_cards=sum(bool(r.get('native_raw')) for r in rows),metadata_only=sum(a.get('status')=='METADATA_ONLY' for a in new['native_comparison_review']['assessments'].values()),independent_leg_checks=checked,cutoff=new['durable_cursor'])
print(json.dumps(report))
