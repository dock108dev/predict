"""Reconcile the exact unresolved historical cohort against retained observations.

No SQL, providers, guessed receipt clocks, or stable-cohort substitutions. Sampled
currentness and commit lineage are reported separately: a commit can already be
superseded by the next observation. Input hashes cannot reveal changed fields.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.storage.store import stamp
from scripts.pipeline_convergence_report import publication_current


def distribution(values):
    values = sorted(values)
    return dict(samples=len(values), minimum=values[0] if values else None,
                p50=values[len(values)//2] if values else None,
                p95=values[min(len(values)-1, int(len(values)*.95))] if values else None,
                maximum=values[-1] if values else None)


def build(history, run):
    samples = run['records']
    if not samples:
        raise ValueError('changing_report_requires_observations')
    first, last = samples[0], samples[-1]
    if len({s['engine'] for s in samples}) != 1 or len({s['runtime']['runtime_id'] for s in samples}) != 1:
        raise ValueError('changing_report_requires_fixed_engine_and_runtime')
    selected = [r for r in history['rows'] if r['current_disposition'] in ('repeatedly invalidated', 'deferred')]
    rows = []
    ledger = {g['id']: g for s in samples for g in s['generations'] if g['engine'] == first['engine']}
    for retained in selected:
        eid = retained['source_event_id']
        observations = []
        for sample in samples:
            event = next((e for e in sample['events'] if e['id'] == eid), None)
            pubs = [p for p in sample['publications'] if eid in (p['publication_events'] or []) and p['selected']]
            observations.append(dict(at=sample['at'], event=event,
                current=[p for p in pubs if publication_current(p, sample)], publications=pubs))
        generations = [g for g in ledger.values() if eid in g['events']]
        commits = [g for g in generations if g['published_at'] and stamp(first['at']) <= stamp(g['published_at']) <= stamp(last['at'])]
        valid_commits = [g for g in commits if g['disposition'] == 'published' and not g['facts'].get('retained_financial_only')]
        current = [o for o in observations if o['current']]
        signatures = [o['event']['semantic_revision'] if o['event'] else None for o in observations]
        changes = sum(a != b for a, b in zip(signatures, signatures[1:]))
        last_attempt = next((a for a in last['attempts'] if a['event_id'] == eid and a['branch'] == 'metrics'), None)
        unfinished = [g for g in generations if g['disposition'] in ('eligible_pending', 'failed', 'deferred')]
        disposition = ('not_in_final_offered_window' if observations[-1]['event'] is None else
            'current_at_final_sample' if observations[-1]['current'] else
            'published_current_then_invalidated' if current else
            'valid_commit_between_samples' if valid_commits else
            'only_historical_commits_inputs_overtaken' if commits else 'no_observed_publication_progress')
        rows.append(dict(source_event_id=eid, source=retained['source'], native_event_id=retained['native_event_id'],
            historical_disposition=retained['current_disposition'], final_disposition=disposition,
            comparison_bundle_keys=sorted({p['game_key'] for o in observations for p in o['publications']} | {g['game_key'] for g in generations}),
            component_members=(observations[-1]['event'] or {}).get('component'),
            observed_component_revision_changes=changes, current_samples=len(current),
            first_observed_current_at=current[0]['at'] if current else None,
            last_observed_current_at=current[-1]['at'] if current else None,
            last_observed_current_publication=max((p['calculated_at'] for o in current for p in o['current'] if p.get('calculated_at')), default=None),
            last_current_sample_publications=current[-1]['current'] if current else [],
            unique_generations=len(generations), commit_generations=len(commits), valid_commit_generations=len(valid_commits),
            historical_commit_generations=len(commits)-len(valid_commits),
            generation_dispositions=dict(Counter(g['disposition'] for g in generations)),
            generation_reasons=dict(Counter(g['reason'] or 'none' for g in generations)),
            capture_to_first_commit_seconds=distribution([(stamp(g['published_at'])-stamp(g['admitted_at'])).total_seconds() for g in commits]),
            receipt_to_publication_seconds=None,
            oldest_unfinished_capture_age_seconds=max(((stamp(last['at'])-stamp(g['admitted_at'])).total_seconds() for g in unfinished), default=None),
            last_attempt=last_attempt, generation_lineage=generations,
            observed_membership=[dict(at=o['at'],component=o['event']['component'] if o['event'] else None) for i,o in enumerate(observations)
                if i == 0 or (o['event'] or {}).get('component') != (observations[i-1]['event'] or {}).get('component')],
            evidence_limits=['Historical observer retained component hashes, not per-field input revisions; price, depth, metadata, fee, rule and expiry deltas cannot be distinguished retroactively.',
                'Sampled currentness does not establish continuous currentness or currentness at unsampled commits.',
                'Receipt-to-publication and individual comparison identities require the captured offer manifest; bundle identities are not individual comparisons.']))
    return dict(evidence_class='retained_previous_engine_observations_reanalyzed_offline',
        engine=first['engine'], runtime=first['runtime']['runtime_id'], interval=[first['at'], last['at']],
        seconds=(stamp(last['at'])-stamp(first['at'])).total_seconds(), samples=len(samples),
        original_dispositions=dict(Counter(r['historical_disposition'] for r in rows)),
        dispositions=dict(Counter(r['final_disposition'] for r in rows)), rows=rows,
        provider_requests=0, fresh_live_observation=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reconciliation', type=Path)
    parser.add_argument('observations', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    report = build(json.loads(args.reconciliation.read_text()), json.loads(args.observations.read_text()))
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'rows'}))


if __name__ == '__main__':
    main()
