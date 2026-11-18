"""Check that shipped guides refer to publishable project files."""

from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = (
    "README.md",
    "NEXT_STEPS.md",
    "docs/current-pregame.md",
    "docs/storage-ownership.md",
    "docs/odds-archive-operations.md",
    "docs/CI.md",
    "docs/hetzner.md",
    "docs/architecture.md",
    "docs/benchmark-ev.md",
    "docs/sportsgameodds-operations-20261110.md",
    "docs/fee-coverage-policy.md",
    "docs/novig-nflwin-modeled-basis.md",
    "docs/combined-occurrence-input-contract.md",
    "docs/comparison-board-api-contract.md",
    "docs/comparison-slate-api-contract.md",
    "docs/configuration.md",
    "docs/acquisition.md",
    "docs/raw-prices.md",
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
    "docs/examples/current-pregame-1/README.md",
    "docs/scanner-usage.md",
    "docs/examples/opportunity-summaries-1/README.md",
    "docs/examples/scanner-transitions-1/README.md",
    "docs/examples/selected-ticket-1/README.md",
    "docs/scanner-qualification-decisions.md",
    "docs/examples/scanner-1/README.md",
    "docs/sports-integration.md",
    "docs/ui-design.md",
    "docs/local-ui-development.md",
    "docs/contracts/predict-admin-1.md",
    "docs/contracts/predict-current-1.md",
    "docs/contracts/predict-retained-prices-1.md",
)


def validate(root):
    root = root.resolve()
    local_links = {}
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
            if relative.parts:
                local_links.setdefault(relative.as_posix(), (name, target))

    # In a checkout, a link to an ignored artifact can exist locally and still
    # break when CI checks the published tree. Tracked files remain valid even
    # when they match an ignore rule.
    if local_links and (root / ".git").exists():
        result = subprocess.run(
            ["git", "check-ignore", "--stdin", "-z"],
            cwd=root,
            input="\0".join(local_links) + "\0",
            text=True,
            capture_output=True,
        )
        if result.returncode != 1:
            result.check_returncode()
        if result.stdout:
            name, target = local_links[result.stdout.split("\0", 1)[0]]
            raise ValueError(
                f"Local-only reference in maintained link: {name}: {target}"
            )
    print(f"PASS: {len(DOCUMENTS)} maintained documents; all shipped references exist")


if __name__ == "__main__":
    validate(ROOT)
