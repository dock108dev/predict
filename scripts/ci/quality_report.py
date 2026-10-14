"""Render fixed-schema tool reports without evaluating report contents."""

import html
import importlib.metadata
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import sys
import xml.etree.ElementTree as ET


def read(path, expected):
    value = json.loads(path.read_text())
    if not isinstance(value, expected):
        raise ValueError("Unexpected report schema")
    return value


def render(
    outcomes,
    root,
    postgres=False,
    package=False,
    expanded=False,
    audit=False,
    browser=False,
):
    required = (
        {"browser": root / "browser/junit.xml"}
        if browser
        else {"audit": root / "quality/audit.json"}
        if audit
        else {"package": root / "package/metrics.json"}
        if package
        else {"postgres": root / "postgres/junit.xml"}
        if postgres
        else {
            "source": root / "quality/junit.xml",
            "audit": root / "quality/audit.json",
            "package": root / "package/metrics.json",
        }
    )
    if expanded:
        required.update(
            lint=None,
            workflow=None,
            docs=None,
            secrets=root / "quality/secret-metrics.json",
        )
    records = []
    errors = []
    for name, path in required.items():
        raw = outcomes.get(name, {}).get("outcome", "not run")
        status = {
            "success": "PASS",
            "failure": "FAIL",
            "cancelled": "CANCELLED",
            "skipped": "SKIPPED",
        }.get(raw, "NOT RUN")
        record = {"name": name, "status": status, "measurements": None}
        try:
            if path is None:
                pass  # Exit status is the evidence for source/static checks.
            elif path.suffix == ".xml":
                cases = list(ET.parse(path).getroot().iter("testcase"))
                if not cases:
                    raise ValueError("zero tests")
                record["measurements"] = {
                    "tests": len(cases),
                    "failed": sum(
                        c.find("failure") is not None or c.find("error") is not None
                        for c in cases
                    ),
                    "skipped": sum(c.find("skipped") is not None for c in cases),
                    "seconds": sum(float(c.get("time", "0")) for c in cases),
                }
                if record["measurements"]["failed"] or record["measurements"][
                    "skipped"
                ] == len(cases):
                    raise ValueError("failed or entirely skipped suite")
            elif name == "audit":
                data = read(path, dict)
                deps = data["dependencies"]
                if not isinstance(deps, list) or not deps:
                    raise ValueError("empty dependency report")
                if any(
                    not isinstance(d, dict)
                    or not isinstance(d.get("name"), str)
                    or not d.get("name")
                    or ("skip_reason" not in d and not isinstance(d.get("vulns"), list))
                    for d in deps
                ):
                    raise ValueError("missing or malformed dependency findings")
                findings = sum(len(d["vulns"]) for d in deps if "vulns" in d)
                unavailable = sum("skip_reason" in d for d in deps)
                record["measurements"] = {
                    "dependencies": len(deps),
                    "findings": findings,
                    "unavailable": unavailable,
                    "severity": "PyPI API does not consistently supply severity",
                }
                if findings or unavailable:
                    raise ValueError("vulnerabilities or unavailable dependencies")
            elif name == "secrets":
                data = read(path, dict)
                if (
                    data.get("status") != "PASS"
                    or type(data.get("findings")) is not int
                    or data["findings"] != 0
                ):
                    raise ValueError("Secret findings or unavailable scan evidence")
                record["measurements"] = data
            else:
                data = read(path, dict)
                if data["status"] != "PASS" or data["wheel_bytes"] <= 0:
                    raise ValueError("invalid build measurement")
                record["measurements"] = data
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
            record["reason"] = str(error)
            if status == "PASS":
                record["status"] = "FAIL"
            errors.append(name)
        if status != "PASS":
            errors.append(name)
        records.append(record)

    def safe(v):
        return (
            html.escape(str(v))
            .replace("|", "&#124;")
            .replace("`", "&#96;")
            .replace("\n", " ")
        )

    def display_measurement(record):
        value = record.get("measurements")
        if record["name"] != "package" or not isinstance(value, dict):
            return value
        inventory = value.get("installed_dependencies")
        return {
            **{
                k: value.get(k) for k in ("wheel_bytes", "files", "seconds", "baseline")
            },
            "dependencies": len(inventory) if isinstance(inventory, list) else None,
            "unknown_license_expressions": sum(
                not d.get("license_expression")
                for d in inventory
                if isinstance(d, dict)
            )
            if isinstance(inventory, list)
            else None,
            "inventory": "full package artifact metrics.json",
        }

    text = f"## {'Package' if package else 'Storage' if postgres else 'Browser' if browser else 'Quality'} results\n\nTested SHA: `{safe(os.environ.get('GITHUB_SHA', 'local'))}`; event: {safe(os.environ.get('GITHUB_EVENT_NAME', 'local'))}; {safe(platform.platform())}; Python {platform.python_version()}.\n\n| Check | Status | Measurement / reason |\n|---|---|---|\n"
    text += "\n".join(
        f"| {r['name']} | {r['status']} | {safe(display_measurement(r))}; {safe(r.get('reason', ''))} |"
        for r in records
    )
    text += "\n\nMissing data remains unavailable. Inspect the corresponding artifact/log for the first FAIL; a SKIPPED/NOT RUN check needs its earlier setup blocker resolved.\n"
    if "audit" in required:
        text += "Dependency findings use the current live database queried by pip-audit, with no comparable baseline.\n"
    identity = f"\nPR head: `{safe(os.environ.get('PR_HEAD_SHA'))}`; ref: `{safe(os.environ.get('GITHUB_REF'))}`; run: {safe(os.environ.get('CI_RUN_URL'))}.\n"
    text += identity
    text += f"Merge queue candidate: `{safe(os.environ.get('MERGE_QUEUE_SHA'))}`.\n"
    return text, records, bool(errors)


def main():
    root = Path("test-results")
    root.mkdir(exist_ok=True)
    text, records, failed = render(
        json.loads(os.environ.get("CHECK_OUTCOMES", "{}")),
        root,
        "--postgres" in sys.argv,
        "--package" in sys.argv,
        "--expanded" in sys.argv,
        "--audit" in sys.argv,
        "--browser" in sys.argv,
    )
    name = (
        "browser"
        if "--browser" in sys.argv
        else "package-summary"
        if "--package" in sys.argv
        else "postgres"
        if "--postgres" in sys.argv
        else "quality"
    )

    def version(tool):
        try:
            return importlib.metadata.version(tool)
        except importlib.metadata.PackageNotFoundError:
            return None

    (root / name).mkdir(exist_ok=True)
    (root / name / "summary.md").write_text(text)
    (root / name / "metrics.json").write_text(
        json.dumps(
            {
                "tested_sha": os.environ.get("GITHUB_SHA"),
                "merge_queue_sha": os.environ.get("MERGE_QUEUE_SHA"),
                "platform": platform.platform(),
                "python": platform.python_version(),
                "overall": "FAIL" if failed else "PASS",
                "pr_head": os.environ.get("PR_HEAD_SHA"),
                "ref": os.environ.get("GITHUB_REF"),
                "run_url": os.environ.get("CI_RUN_URL"),
                "event": os.environ.get("GITHUB_EVENT_NAME"),
                "checks": records,
                "baseline": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tools": {
                    name: version(name)
                    for name in ("ruff", "pip-audit", "build", "pytest", "playwright")
                },
            },
            indent=2,
        )
        + "\n"
    )
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(text)
    print(text, end="")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
