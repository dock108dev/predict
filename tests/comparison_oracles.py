"""Locate immutable upstream test inputs without depending on local research notes."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = {
    "docs/comparison-r05-fee-proposals-20261008.json": "tests/fixtures/comparison-oracles/fee-proposals.json",
    "docs/comparison-r05-fee-vectors-20261008.json": "tests/fixtures/comparison-oracles/fee-vectors.json",
    "docs/comparison-r06-estimate-policy.md": "tests/fixtures/comparison-oracles/estimate-policy.md",
    "docs/comparison-r06-policy-vectors-20261008.json": "tests/fixtures/comparison-policy-vectors.json",
    "docs/comparison-r07-probability-vectors-20261008.json": "tests/fixtures/comparison-oracles/probability-vectors.json",
    "docs/comparison-r07-probabilities.md": "tests/fixtures/comparison-oracles/probability-policy.md",
    "app/fixtures/fee-schedules-v1.json": "app/fixtures/fee-schedules-v1.json",
    "app/fixtures/public-contracts-v1.json": "app/fixtures/public-contracts-v1.json",
}


def artifact_path(reference):
    # A source name is provenance; it need not be the fixture's storage location.
    return ROOT / ARTIFACTS[reference]
