"""Scan only exported publishable files; keep secrets fully redacted and local."""

import json
import hashlib
import argparse
import re
from datetime import date
from pathlib import Path
import subprocess
import tempfile
from export import export


def verify_rules(binary, config):
    """A public-ID exception must still detect credentials in the same file."""
    with tempfile.TemporaryDirectory(prefix="predict-secret-controls-") as folder:
        root = Path(folder)
        source = root / "source/app/dashboard/opportunity_board.py"
        source.parent.mkdir(parents=True)
        public_id = "855f58fad5f0f14b" + "239f4f63df27998b"
        credential = hashlib.sha256(
            b"disposable secret scanner detection control"
        ).hexdigest()
        source.write_text(
            f'PUBLIC = ("the_odds_api", "{public_id}")\napi_key = "{credential}"\n'
        )
        example_name = "docs/examples/scanner-readiness-1/waiting.json"
        # Authored public values exercise the allowlist without local retained data.
        scope_digest = (
            "293fa8caabbe6d12038b95ea3dceb3572685adc622f7419d1f438e29b278bb65"
        )
        example = root / "source" / example_name
        example.parent.mkdir(parents=True)
        example.write_text(
            '"key": "' + scope_digest + '"\napi_key = "' + credential + '"\n'
        )
        review_name = "app/reviews/native/retained-1694c5363a2386593b8c44f1-v1.json"
        team = "f61f9daa-407b-4c46-96e8-feee19cd6f51"
        native = root / "source" / review_name
        native.parent.mkdir(parents=True)
        native.write_text(
            '"hockey_team": "' + team + '"\napi_key = "' + credential + '"\n'
        )
        report = root / "report.json"
        result = subprocess.run(
            [
                str(binary),
                "dir",
                str(root / "source"),
                "--config",
                str(config.resolve()),
                "--redact=100",
                "--no-banner",
                "--report-format=json",
                "--report-path",
                str(report),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        value = json.loads(report.read_text())
        if (
            result.returncode != 1
            or not isinstance(value, list)
            or len(value) != 3
            or any(row.get("StartLine") != 2 for row in value)
            or {str(Path(row["File"]).relative_to(root / "source")) for row in value}
            != {"app/dashboard/opportunity_board.py", example_name, review_name}
        ):
            raise ValueError(
                "Secret scanner detection/exception controls failed; no source scan can qualify"
            )
    print(
        "Secret scanner controls: PASS; credential detection retained in all three excepted file classes"
    )


def main():
    config = Path(".gitleaks.toml")
    review = re.search(r"Review after: (\d{4}-\d{2}-\d{2})", config.read_text())
    if not review or date.fromisoformat(review[1]) < date.today():
        raise ValueError("Secret exceptions require review")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="test-results/quality")
    output = Path(parser.parse_args().output)
    output.mkdir(parents=True, exist_ok=True)
    if any(
        (output / name).exists() for name in ("gitleaks.json", "secret-metrics.json")
    ):
        raise ValueError(
            "Use fresh secret report paths; existing evidence is preserved"
        )
    binary = Path(".local/ci-tools/gitleaks").resolve()
    verify_rules(binary, config)
    with tempfile.TemporaryDirectory(prefix="predict-secrets-") as folder:
        source = Path(folder) / "source"
        export(source)
        result = subprocess.run(
            [
                str(binary),
                "dir",
                str(source),
                "--config",
                str(config.resolve()),
                "--redact=100",
                "--no-banner",
                "--report-format=json",
                "--report-path",
                str((output / "gitleaks.json").resolve()),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        report = output / "gitleaks.json"
        findings = json.loads(report.read_text()) if report.exists() else None
        if not isinstance(findings, list):
            raise ValueError(
                "Secret scan report missing or malformed; evidence unavailable"
            )
        # Paths only: never publish raw secret/match content or arbitrary scanner logs.
        safe = [
            {k: row.get(k) for k in ("RuleID", "StartLine", "EndLine")}
            | {"File": str(Path(row["File"]).relative_to(source))}
            for row in findings
        ]
        report.write_text(json.dumps(safe, indent=2) + "\n")
        (output / "secret-metrics.json").write_text(
            json.dumps(
                dict(
                    status="PASS"
                    if result.returncode == 0 and not findings
                    else "FAIL",
                    findings=len(findings),
                    severity=None,
                    tool="gitleaks 8.30.1",
                    scope="publishable current-tree export; no owner state or historical Git scan",
                    baseline=None,
                ),
                indent=2,
            )
            + "\n"
        )
        print(
            "Secret scan findings:",
            len(findings),
            "(redacted report; severity unavailable)",
        )
        return int(result.returncode != 0 or bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
