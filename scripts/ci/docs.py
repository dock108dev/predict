"""Check links in the project guides and API documentation."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = (
    "README.md",
    "docs/CI.md",
    "docs/development.md",
    "docs/configuration.md",
    "docs/architecture.md",
    "docs/security.md",
    "docs/error-handling.md",
    "docs/benchmark-ev.md",
    "docs/market-data-gaps.md",
    "docs/sports-integration.md",
    "docs/ui-design.md",
    "docs/native-retained-coverage.md",
    "docs/native-review-records.md",
    "docs/offline-opportunities.md",
    "docs/offline-pricing.md",
    "docs/reference-contracts.md",
    "docs/contracts/predict-current-1.md",
    "docs/contracts/predict-admin-1.md",
)


def validate(root):
    for name in DOCUMENTS:
        document = root / name
        for target in re.findall(r"\]\(([^)]+)\)", document.read_text()):
            if "://" in target or target.startswith("#"):
                continue
            path = (document.parent / target.split("#")[0]).resolve()
            if not path.is_relative_to(root.resolve()) or not path.exists():
                raise ValueError(f"Missing/escaping maintained link: {name}: {target}")
    print(f"PASS: {len(DOCUMENTS)} maintained documents; local references exist")


if __name__ == "__main__":
    validate(ROOT)
