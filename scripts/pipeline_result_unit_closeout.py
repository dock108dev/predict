"""Render the final bounded unit observation without declaring financial success."""
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);v=json.loads((root/'delivery-report.json').read_text())
c=json.loads((root/'final-census-summary.json').read_text());d=json.loads((root/'accepted-original-end.json').read_text());loaded=json.loads((root/'accepted-loaded-end.json').read_text());r=json.loads((root/'accepted-runtime-end.json').read_text())
p=v['population'];u=v['units'];g=v['generation_ledger'];total=c['totals'];end={e['source_event_id']:e for e in d['rows']}
lines=['# Independently sealed result units — final live qualification','',
'**D02 remains open.** Dependency-current unsupported diagnostics do not qualify numeric EV, executable pairs, or sustained complete result delivery. No commit or push. Sole checkout on `main`.', '',
'## Fixed implementation and evidence','',
f"- Interval: {v['start']} → {v['end']} ({v['duration_seconds']:.2f}s); {v['samples']} samples.",
f"- Engine: `{loaded['engine']}`; runtime: `{loaded['runtime']['runtime_id']}`.",f"- Python tree: `{loaded['python_tree']}`.",
f"- Unhealthy samples: {v['unhealthy_samples']}; inactive samples: {v['inactive_samples']}; board-worker unavailable samples: {v['board_unavailable_samples']}.",
f"- Actual sample gaps: `{json.dumps(v['sample_gap_seconds'])}`. The requested interval was five seconds; subinterval lifetimes can be missed.",
'- Preliminary runs are not combined. The `accepted-live` folder name identifies the final observation files; it is not owner acceptance.',
'- Full closure, implementation boundaries and development repairs: [implementation-notes.md](implementation-notes.md).','',
'## Population and completeness','',
f"- All {p['original_events']} original identities remain in the denominator. Endpoint dispositions: `{json.dumps(d['counts'])}`.",
f"- Original events with any sampled-current known unit: {p['events_any_current']}/68; any repeat-current unit: {p['events_any_repeat']}/68; all known units repeat-current: {p['events_all_known_units_repeat']}/68.",
f"- Original events without result inventory evidence: {p['events_without_inventory']}. Their undiscovered units are unknown, not zero or successfully complete.",
f"- Broader window: {p['initial_window_events']} initial source identities, {p['observed_window_events']} seen; {len(p['arrival_event_ids'])} arrivals/reappearances and {len(p['window_exit_event_ids'])} exits on the last observed schedule.",
f"- Known interval inventory: {u['known_inventory']} units. Sampled-current at least once: {u['ever_sampled_current']}; repeat-current generations: {u['repeat_current']}; repeat with changed dependency hashes: {u['repeat_changed_current']}.",
f"- Endpoint retained units: {u['retained_end']}; current {u['current_end']}, historical {u['historical_end']}, known pending/unsealed {u['unsealed_known_end']}; {u['known_units_outside_window_end']} known units outside the final window.",
f"- Endpoint financial input states: `{json.dumps(u['financial_states_end'])}`.",
'- Event coverage uses the entire known game-unit inventory associated with each native identity. One easy market is never reported as complete event delivery.','',
'## Generations, changes and timing','',
f"- Generation ledger: `{json.dumps(g)}`.",
f"- Input changes: `{json.dumps(v['input_changes'])}`; original-cohort semantic/receipt changes: `{json.dumps(v['original_cohort_input_changes'])}`.",
'- Meaningful change detection includes price/contract/book revisions and source clocks; receipt-only execution changes are separated. A changed hash is not proof of a particular settlement-clause change.',
'- Admissions and publication markers are SQL transaction events. `commit_observed_at` is a post-transaction upper visibility bound. First visible/current samples are separate observations.','',
'| Timing | n | p50 | p95 | max |','|---|---:|---:|---:|---:|']
for k,a in [*v['latency'].items(),*v['seal_timing_ms'].items()]:
 lines.append(f"| {k} | {a['n']} | {a.get('p50','—')} | {a.get('p95','—')} | {a.get('max','—')} |")
lines += ['',f"Observed current-lifetime lower bounds: `{json.dumps(v['observed_current_lifetime_lower_bound_seconds'])}`. Single samples contribute zero-duration lower bounds; runs at the final sample are right-censored. These are not claims of continuous validity between samples.",
f"Original-cohort timing (separate from the broader unit population): `{json.dumps(v['cohort_latency'])}`; seal timing milliseconds: `{json.dumps(v['cohort_seal_timing_ms'])}`.",
'Full per-unit observed runs and all reason counts are in [delivery-report.json](delivery-report.json). Exact receipt-to-SQL admission and queue-entry times are not available for every individual unit; no synthetic end-to-end latency is inferred. The separate bounded runtime observer contains ingress operation timing and scheduler evidence.','',
'## Coherent post-run next-72-hour census','',
f"Snapshot: {c['at']} → {c['window_end']}.",
f"- Normalized execution offers: {c['normalized_execution_offers']}; reference offers: {c['normalized_reference_offers']}.",
f"- Published raw execution observations: {total.get('published_price_observations',0)}; normalized unpublished: {total.get('normalized_without_publication',0)}.",
f"- Raw display: current {total.get('raw_display:current',0)}, last-known {total.get('raw_display:last_known',0)}, pending {total.get('raw_display:pending',0)}.",
f"- Result-unit census: `{json.dumps({k:x for k,x in c['result_units'].items() if k not in ('records','notes')})}`.",
f"- Same-outcome price pairs: {c['same_outcome_price_pairs']}; normal-score complement classes: `{json.dumps(c['normal_score_complements'])}`. Neither establishes complete financial eligibility.",
f"- Matching primary dispositions: `{json.dumps(c['matching_primary'])}`.",
f"- Retained numeric full-EV rows: {total.get('full_ev_numeric_retained',0)}; published pair rows: {c['published_pair_rows']}.",
'- Full receipt, matching, branch and input-gap reconciliations are in [final-census.json](final-census.json) and [final-census-summary.json](final-census-summary.json). Legacy game-level financial-current fields are not result-unit authority.','',
'## Storage and account boundary','',
f"- Database bytes: start {v['storage']['start']:,}, end {v['storage']['end']:,}, peak {v['storage']['peak']:,}; cap remains {v['storage']['cap']:,}. Minimum measured headroom: {v['storage']['minimum_headroom']:,} bytes.",
f"- Account guard: `{r['quota']['blocking_reason']}`; reserved {r['quota']['reserved']}, held uncertain {r['quota']['held_uncertain_credits']}, unresolved {r['unresolved_attempt_count']}. No accounting reset or forced paid probe.",
'- The runtime supplement recorded 103 available and 37 unavailable database-status samples, with `database_unavailable`, despite successful direct observer SQL reads and healthy overall heartbeats. This remains a database/maintenance-status limitation; uninterrupted availability is not established.',
'- Captured Originals, explicit Stop/source-pause choices, reader leases and independent maintenance remain preserved. Runtime/resource snapshots and operation timings are retained separately.','',
'## Verification and ordinary use','',
'[PostgreSQL, client, API and browser evidence](ordinary-use-and-verification.md). The later browser EV list hit `current_slate_read_capacity`; selected-read success does not establish whole-list usability. Runtime ingress, resource, maintenance and oldest unresolved scheduler evidence are in [runtime-report.json](runtime-report.json).','',
'## All original identities','',
'`Known` is known game-unit inventory; `ever`, `repeat` and `end` are independently current unit counts. Missing inventory remains unknown. Endpoint absence without withdrawal evidence is a gap, not retirement.','',
'| Source | Native event | Endpoint disposition | Known | Ever | Repeat | End current | Unit generations attempted |','|---|---|---|---:|---:|---:|---:|---:|']
for e in v['original_dispositions']:
 lines.append(f"| {e['source']} | `{e['native_event_id']}` | {end[e['source_event_id']]['disposition']} | {e['known_game_units'] if e['full_inventory_evidence'] else 'unknown'} | {e['units_ever_current']} | {e['units_repeat_current']} | {e['units_current_end']} | {e['attempts']} |")
lines += ['', '## Remaining accountable work','',
'The pipeline/publication engineer must reduce capture-to-seal exposure for still-changing units while preserving complete discovery and candidate/reference closure, then repeat this same frozen event and result-level qualification. Shared full-occurrence discovery, conservative reference invalidation, ingress contention and incomplete inventory traversal remain material limits. Missing financial models, fees, payout terms, source rules, scoring/equality evidence and clocks remain separate financial-input gaps.','']
(root/'delivery-report.md').write_text('\n'.join(lines))
print(root/'delivery-report.md')
