"""Fixed-denominator retained coverage acceptance accounting, offline only."""
import json
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'evidence/v1-counterpart-completion-20261001-v1'
def main():
 c=json.loads((ROOT/'evidence/v1-admission-delivery-repair-20261001-v1/coverage-63.json').read_text());cells=c['cells'];assert len(cells)==63
 from app.collection.v1_coverage import PAIRED
 def aggregate(index):
  g=defaultdict(lambda:dict(paired=0,requirements=0))
  for r in cells:
   key=r['cell_id'].split('/')[index];g[key]['requirements']+=1;g[key]['paired']+=r['cell_id'] in PAIRED
  return dict(g)
 status=dict(denominator=63,minimum_valid_retained_pairs=48,optional_easy_target=51,current_valid_retained_pairs=15,percent=100*15/63,shortfall=33,met=False,closure='At least 48 exact eligible retained pairs plus ordinary V1 workflow pass; all four approved comparison venues continue useful contributions; freshness/runtime qualification separately reported',counting='Any two approved comparison venues, exact eligible event/award/outcome/period/line; no metadata, reference-only prices or synthetic fixtures',sports=aggregate(0),periods=aggregate(1),families=aggregate(2),source_contribution=c['summary']['by_source'],authorization_changed=False,automated_execution='V2',account_economics='Optional for dependent displayed calculations')
 (OUT/'beta-coverage-status.json').write_text(json.dumps(status,indent=2)+'\n')
 lines=['# Beta coverage acceptance and post-beta backlog','', 'October 1, 2026 owner decision. This is acceptance policy, with no new collection authority.','', '**Beta coverage requires at least 48 of the fixed 63 requirements with valid retained price pairs (76.19%).** 51/63 is desirable only when straightforward. Do not delay beta to chase all 63. Current coverage is 15/63 (23.81%); the shortfall is 33. The next retained-native candidate set can potentially add two requirements after current refresh and actual paired books. This is not evidence that 48/63 is impossible.','', 'Count exact eligible comparisons between any two of Kalshi, Polymarket US, Novig and ProphetX. Metadata admission, reference-only prices and synthetic engineering fixtures never count. Keep historical retained coverage separate from freshness, current availability and runtime qualification. All four comparison venues must continue contributing useful comparisons; four venues per pair and four venues in every cell are unnecessary.','', '| Sport | Valid retained pairs | Fixed requirements |','| --- | ---: | ---: |']
 for k,v in status['sports'].items():lines.append(f"| {k} | {v['paired']} | {v['requirements']} |")
 lines+=['','| Market family | Valid retained pairs | Fixed requirements |','| --- | ---: | ---: |']
 for k,v in status['families'].items():lines.append(f"| {k} | {v['paired']} | {v['requirements']} |")
 lines+=['','| Period group | Valid retained pairs | Fixed requirements |','| --- | ---: | ---: |']
 for k,v in status['periods'].items():lines.append(f"| {k} | {v['paired']} | {v['requirements']} |")
 lines+=['','Retained paired requirement contributions: Kalshi 3, Polymarket US 3, Novig 14, ProphetX 14. Counts overlap because a requirement can contain more than one venue pair. These dated counts do not prove healthy current feeds.','', 'Prioritize exact native counterparts and other missing cells with implemented locators and admitted identities. Use bounded discovery hypotheses for NFL H1 line/availability questions. Avoid repeated engineering or acquisition cycles on unknown segment locators and unavailable observations while easier supported pairs remain. No broad already-covered moneyline or reference-only outright repetition is planned.','', 'Once 48/63 is reached and the ordinary V1 workflow passes, close the beta coverage workstream. Record remaining cells below as post-beta limitations; they no longer block beta solely because coverage is incomplete. Preserve the complete denominator and source evidence. If observed offerings make 48 unattainable, report the exact shortfall, attempted scopes, empty/capped/unknown distinctions and retained evidence; do not silently shrink the scope.','', 'The following is the visible unresolved inventory today. It becomes the post-beta backlog only after the closure gate passes; currently the workstream remains open.','', '| Requirement | Current blocker class | Next work |','| --- | --- | --- |']
 inventory=json.loads((OUT/'counterpart-inventory.json').read_text())
 for t in inventory['targets']:
  if not t['retained_paired']:lines.append(f"| {t['cell_id']} | {t['disposition']} | {'Bounded native refresh / exact paired books' if t['actionable_missing_requirement'] else 'Specific football H1 offering hypothesis' if t['discovery_hypothesis'] else 'Deferred identity/locator/observed-offering evidence; no request planned'} |")
 (ROOT/'docs/beta-coverage-acceptance.md').write_text('\n'.join(lines)+'\n')
 print(json.dumps(status,indent=2))
if __name__=='__main__':main()
