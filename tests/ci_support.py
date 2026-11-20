"""Load repository CI tools without invoking their command-line entry points."""

import importlib.util
from pathlib import Path
import sys


def load(name):
    scripts = Path(__file__).resolve().parents[1] / "scripts/ci"
    spec = importlib.util.spec_from_file_location(name, scripts / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(scripts))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(scripts))
    return module


def readiness_evidence(root, sha="a" * 40, run="10", attempt="1"):
    """Author complete run artifacts without executing product or workflow code."""
    import json

    module = load("required_evidence")
    junit = '<testsuite tests="1"><testcase name="authored" time="0.01"/></testsuite>'
    paths = {}
    for lane, shard in module.EXPECTED:
        name = f"{lane}-{run}-{attempt}" + (f"-{shard}" if shard else "")
        path = root / name
        path.mkdir(parents=True)
        if lane == "ci-offline":
            names = sorted(module.offline_inventory()[0])
        else:
            names = (
                sorted(module.QUALITY_CHECKS)
                if lane == "ci-quality"
                else ["postgres" if shard else "browser"]
            )
        checks = [dict(name=name, status="PASS") for name in names]
        if lane == "ci-offline":
            for check in checks:
                if "__" in check["name"]:
                    check["tests"] = dict(tests=1, failed=0, skipped=0)
                    (path / (check["name"] + ".xml")).write_text(junit)
        else:
            junit_path = path / (
                "quality/junit.xml" if lane == "ci-quality" else "junit.xml"
            )
            junit_path.parent.mkdir(exist_ok=True)
            junit_path.write_text(junit)
        if shard:
            (path / "toolchain.json").write_text(
                json.dumps(
                    dict(shard_index=int(shard), shard_count=4, suite="registered-sql")
                )
            )
        metrics = path / (
            "quality/metrics.json" if lane == "ci-quality" else "metrics.json"
        )
        metrics.write_text(
            json.dumps(
                dict(
                    schema=1,
                    overall="PASS",
                    tested_sha=sha,
                    run_id=run,
                    run_attempt=attempt,
                    checks=checks,
                )
            )
        )
        paths[(lane, shard)] = path
    return paths
