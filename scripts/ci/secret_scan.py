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
        finance_name = "tests/fixtures/l02-native-20261104.json"
        finance = root / "source" / finance_name
        finance.parent.mkdir(parents=True)
        event_ids = (
            "87d2b814c3f0d3691e9cebbf2de76295",
            "c75744790b7acf6260c78ba5e739c0e5",
        )
        finance.write_text(
            json.dumps([["the_odds_api", event_id] for event_id in event_ids])
            + f'\napi_key = "{credential}"\n'
            + f'api_key = "{event_ids[0]}"\n'
            + json.dumps(["the_odds_api", credential])
            + "\n"
        )
        board_name = "docs/examples/current-pregame-1/positive-board.json"
        selector = "0a109b585d8316c25b3f7ac36e86c2cae34b4db43277f260bea4b1b9f3a8de8a"
        (root / "source" / board_name).parent.mkdir(parents=True)
        (root / "source" / board_name).write_text(
            f'"id": "{selector}"\n"api_key": "{selector}"\n"api_key": "{credential}"\n'
        )
        expected = {
            ("app/dashboard/opportunity_board.py", 2),
            (example_name, 2),
            (review_name, 2),
            (finance_name, 2),
            (finance_name, 3),
            (finance_name, 4),
            (board_name, 2),
            (board_name, 3),
        }
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
            or len(value) != len(expected)
            or {
                (
                    str(Path(row["File"]).relative_to(root / "source")),
                    row.get("StartLine"),
                )
                for row in value
            }
            != expected
        ):
            raise ValueError(
                "Secret scanner detection/exception controls failed; no source scan can qualify"
            )
    print(
        "Secret scanner controls: PASS; five excepted file classes checked, credential fields and unlisted event values detected"
    )


def main():
    config = Path(".gitleaks.toml")
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
    stage = "scanner setup"
    try:
        stage = "exception policy review"
        review = re.search(r"Review after: (\d{4}-\d{2}-\d{2})", config.read_text())
        if not review or date.fromisoformat(review[1]) < date.today():
            raise ValueError("Secret exceptions require review")
        binary = Path(".local/ci-tools/gitleaks").resolve()
        stage = "detection controls"
        verify_rules(binary, config)
        with tempfile.TemporaryDirectory(prefix="predict-secrets-") as folder:
            source = Path(folder) / "source"
            raw_report = Path(folder) / "scanner.json"
            stage = "publishable file export"
            export(source, include_retained=False)
            stage = "gitleaks execution"
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
                    str(raw_report),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            stage = "gitleaks report validation"
            findings = json.loads(raw_report.read_text())
            if not isinstance(findings, list) or result.returncode != int(
                bool(findings)
            ):
                raise ValueError("Scanner exit status and finding report disagree")
            # Publish only validated location metadata. Raw findings stay
            # disposable even when parsing or sanitization fails.
            safe = []
            for row in findings:
                rule, start, end = (
                    row[key] for key in ("RuleID", "StartLine", "EndLine")
                )
                if (
                    not isinstance(rule, str)
                    or not re.fullmatch(r"[A-Za-z0-9_.-]+", rule)
                    or type(start) is not int
                    or type(end) is not int
                    or not 0 < start <= end
                ):
                    raise ValueError("Invalid scanner finding location")
                path = Path(row["File"]).resolve().relative_to(source.resolve())
                safe.append(
                    dict(RuleID=rule, StartLine=start, EndLine=end, File=str(path))
                )
            (output / "gitleaks.json").write_text(json.dumps(safe, indent=2) + "\n")
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
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        # Never copy arbitrary scanner output/exception text into published reports.
        reason = f"Secret scan unavailable during {stage} ({type(error).__name__}); inspect the secret-scan step"
        (output / "secret-metrics.json").write_text(
            json.dumps(
                dict(status="FAIL", findings=None, stage=stage, reason=reason), indent=2
            )
            + "\n"
        )
        print(reason)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
