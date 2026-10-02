"""Offline factual coverage accounting; workflow acceptance is maintained separately.

Version 2 never writes historical evidence, sealed packages or beta acceptance.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / 'evidence/private-beta-workflow-20261001-v1/coverage-accounting'


def build_status():
    source = ROOT / 'evidence/v1-admission-delivery-repair-20261001-v1/coverage-63.json'
    coverage = json.loads(source.read_text())
    cells = coverage['cells']
    from app.collection.v1_coverage import PAIRED
    if len(cells) != 63 or len({row['cell_id'] for row in cells}) != 63:
        raise ValueError('Expected 63 distinct factual requirements')
    paired = set(PAIRED)
    if not paired <= {row['cell_id'] for row in cells}:
        raise ValueError('Paired requirements must belong to the factual ledger')

    def aggregate(index):
        groups = defaultdict(lambda: dict(paired=0, requirements=0))
        for row in cells:
            key = row['cell_id'].split('/')[index]
            groups[key]['requirements'] += 1
            groups[key]['paired'] += row['cell_id'] in paired
        return dict(groups)

    return dict(
        version='workflow-coverage-accounting-2',
        policy='Useful ordinary workflow with clear limitations; no numeric coverage gate',
        evidence_class='Historical retained real observations, not current availability',
        input=str(source.relative_to(ROOT)), denominator=len(cells),
        current_valid_retained_pairs=len(paired),
        percent=100 * len(paired) / len(cells),
        remaining_requirements=len(cells) - len(paired),
        source_record_count=252,
        counting='Exact event/outcome/period/line between two comparison venues; metadata, references and synthetic controls do not count',
        sports=aggregate(0), periods=aggregate(1), families=aggregate(2),
        source_contribution=coverage['summary']['by_source'],
        acceptance_document='docs/beta-coverage-acceptance.md',
        authority='docs/configuration.md#saved-review-and-live-collection',
        authorization_changed=False,
    )


def write_status(output):
    output = Path(output).resolve()
    # Only a new accounting namespace is writable. CLI overrides support isolated
    # temporary verification without making old packages possible destinations.
    if output.is_relative_to(ROOT):
        permitted = (ROOT / 'evidence/private-beta-workflow-20261001-v1').resolve()
        if not output.is_relative_to(permitted) or output == permitted:
            raise ValueError('Use the new workflow accounting namespace or external disposable output')
    elif output.is_relative_to(ROOT.parent):
        raise ValueError('Output outside the repository must be disposable, not a sibling project')
    status = build_status()
    output.mkdir(parents=True, exist_ok=True)
    (output / 'coverage-status.json').write_text(json.dumps(status, indent=2) + '\n')
    lines = ['# Retained comparison coverage accounting', '',
             'Historical factual distribution only. Beta readiness is evaluated through the ordinary workflow.', '',
             f"Retained pairs: {status['current_valid_retained_pairs']}/63. Remaining roadmap requirements: {status['remaining_requirements']}. Source records: 252.", '',
             'Metadata, references and synthetic prices do not add retained pairs. These observations do not establish current availability.', '']
    for label, key in [('Sport', 'sports'), ('Market family', 'families'), ('Period', 'periods')]:
        lines += [f'| {label} | Retained pairs | Requirements |', '| --- | ---: | ---: |']
        lines += [f"| {name} | {value['paired']} | {value['requirements']} |" for name, value in status[key].items()]
        lines.append('')
    (output / 'coverage-accounting.md').write_text('\n'.join(lines) + '\n')
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(write_status(args.output), indent=2))


if __name__ == '__main__':
    main()
