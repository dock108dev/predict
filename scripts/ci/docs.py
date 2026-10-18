"""Check shipped project guides without private or local-planning exemptions."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = (
    "README.md",
    "docs/CI.md",
    "docs/architecture.md",
    "docs/benchmark-ev.md",
    "docs/combined-occurrence-input-contract.md",
    "docs/comparison-board-api-contract.md",
    "docs/comparison-slate-api-contract.md",
    "docs/configuration.md",
    "docs/development.md",
    "docs/current-row-storage.md",
    "docs/data-app-runtime-contract.md",
    "docs/latest-board-results.md",
    "docs/broad-coverage.md",
    "docs/error-handling.md",
    "docs/estimated-runtime.md",
    "docs/market-data-gaps.md",
    "docs/native-retained-coverage.md",
    "docs/native-review-records.md",
    "docs/offline-opportunities.md",
    "docs/offline-pricing.md",
    "docs/reference-contracts.md",
    "docs/requested-trade-financial-contract.md",
    "docs/security.md",
    "docs/scanner-projection-contract.md",
    "docs/scanner-ticket-contract.md",
    "docs/scanner-client-contract.md",
    "docs/scanner-transition-contract.md",
    "docs/scanner-summary-contract.md",
    "docs/scanner-preparation-contract.md",
    "docs/scanner-readiness-contract.md",
    "docs/examples/scanner-readiness-1/README.md",
    "docs/sc06-customer-instructions.md",
    "docs/sc06-performance-20261016.md",
    "docs/examples/opportunity-summaries-1/README.md",
    "docs/examples/scanner-transitions-1/README.md",
    "docs/examples/selected-ticket-1/README.md",
    "docs/scanner-qualification-decisions.md",
    "docs/examples/scanner-1/README.md",
    "docs/sports-integration.md",
    "docs/ui-design.md",
    "docs/contracts/predict-admin-1.md",
    "docs/contracts/predict-current-1.md",
    "docs/contracts/predict-retained-prices-1.md",
)


def validate(root):
    root = root.resolve()
    for name in DOCUMENTS:
        document = root / name
        if not document.is_file():
            raise ValueError("Missing maintained document: " + name)
        source = document.read_text()
        if re.search(r"/(?:Users|home)/[^/\s]+/", source):
            raise ValueError("Personal filesystem path in maintained document: " + name)
        for target in re.findall(r"\]\(([^)]+)\)", source):
            if target.startswith(("https://", "http://", "mailto:", "#")):
                continue
            reference = Path(target.split("#")[0])
            path = (document.parent / reference).resolve()
            if (
                reference.is_absolute()
                or not path.is_relative_to(root)
                or not path.exists()
            ):
                raise ValueError(f"Missing/escaping maintained link: {name}: {target}")
            relative = path.relative_to(root)
            if (
                relative.parts
                and relative.parts[0]
                in {".local", ".venv", "evidence", "test-results", "node_modules"}
                or relative.name == "PLAN.md"
                or (
                    relative.name.startswith(".env")
                    and relative.name
                    not in {".env.example", ".env.sample", ".env.template"}
                )
                or (path.suffix == ".md" and relative.as_posix() not in DOCUMENTS)
            ):
                raise ValueError(
                    f"Local-only reference in maintained link: {name}: {target}"
                )
    print(f"PASS: {len(DOCUMENTS)} maintained documents; all shipped references exist")


if __name__ == "__main__":
    validate(ROOT)
