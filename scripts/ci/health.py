"""Bounded, read-only Actions sample; no inferred flakes or billing costs."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import statistics
import time
import urllib.request


def selected_runs(runs, now):
    window = now - timedelta(days=30)
    return [
        r
        for r in runs[:30]
        if r["name"] == "CI"
        and r["status"] == "completed"
        and window
        <= datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
        <= now
    ]


def analyze(runs, now):
    rows = selected_runs(runs, now)
    result = {
        "sample_limit": 30,
        "window_days": 30,
        "retrieved_at": now.isoformat(),
        "sample_runs": len(runs),
        "ci_runs": len(rows),
        "events": {},
        "queue_seconds": None,
        "critical_path_seconds": None,
        "runner_minutes": None,
        "quota": None,
        "suspected_flakes": None,
    }
    for event in ("pull_request", "push", "workflow_dispatch", "merge_group"):
        selected = [r for r in rows if r["event"] == event]
        first = [
            r["conclusion"]
            if r["run_attempt"] == 1
            else r.get("first_attempt_conclusion")
            for r in selected
        ]
        first = [value for value in first if value in ("success", "failure")]
        durations = []
        for r in selected:
            if r["conclusion"] in ("success", "failure") and r.get("job_completed_at"):
                start = datetime.fromisoformat(
                    r["run_started_at"].replace("Z", "+00:00")
                )
                end = datetime.fromisoformat(
                    r["job_completed_at"].replace("Z", "+00:00")
                )
                durations.append((end - start).total_seconds())
        result["events"][event] = {
            "runs": len(selected),
            "first_attempt_observed": len(first),
            "first_attempt_pass_rate": sum(value == "success" for value in first)
            / len(first)
            if first
            else None,
            "rerun_runs": sum(r["run_attempt"] > 1 for r in selected),
            "observed_rerun_recoveries": sum(
                r.get("first_attempt_conclusion") == "failure"
                and r["conclusion"] == "success"
                for r in selected
                if r["run_attempt"] > 1
            ),
            "unavailable_first_attempts": sum(
                r["run_attempt"] > 1 and r.get("first_attempt_conclusion") is None
                for r in selected
            ),
            "cancelled": sum(r["conclusion"] == "cancelled" for r in selected),
            "median_elapsed_seconds": statistics.median(durations)
            if durations
            else None,
            "p95_elapsed_seconds": sorted(durations)[
                max(0, __import__("math").ceil(len(durations) * 0.95) - 1)
            ]
            if len(durations) >= 20
            else None,
            "duration_sample": len(durations),
        }
    return result


def collect(fetch, now):
    window = (now - timedelta(days=30)).date().isoformat()
    runs = fetch(
        f"/actions/workflows/ci.yml/runs?per_page=30&status=completed&created=%3E%3D{window}"
    )["workflow_runs"][:30]
    failure_steps = {}
    runner_seconds = 0
    observed_jobs = 0
    incomplete = 0
    for run in selected_runs(runs, now):
        if run["run_attempt"] > 1:
            try:
                first = fetch(f"/actions/runs/{run['id']}/attempts/1")
                if (
                    first.get("id") != run["id"]
                    or first.get("run_attempt") != 1
                    or run.get("head_sha")
                    and first.get("head_sha") != run["head_sha"]
                ):
                    raise ValueError("First attempt identity mismatch")
                run["first_attempt_conclusion"] = first["conclusion"]
            except Exception as error:
                run["first_attempt_unavailable"] = type(error).__name__
        try:
            response = fetch(
                f"/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100"
            )
            jobs = response["jobs"]
        except Exception as error:
            run["jobs_unavailable"] = type(error).__name__
            incomplete += 1
            continue
        for job in jobs:
            for step in job.get("steps", []):
                if step.get("conclusion") == "failure":
                    label = step["name"]
                    failure_steps[label] = failure_steps.get(label, 0) + 1
        completed = [j for j in jobs if j.get("completed_at") and j.get("started_at")]
        if completed and len(completed) == len(jobs) == response["total_count"]:
            run["first_job_started_at"] = min(j["started_at"] for j in completed)
            run["job_completed_at"] = max(j["completed_at"] for j in completed)
            observed_jobs += len(completed)
            runner_seconds += sum(
                (
                    datetime.fromisoformat(j["completed_at"].replace("Z", "+00:00"))
                    - datetime.fromisoformat(j["started_at"].replace("Z", "+00:00"))
                ).total_seconds()
                for j in completed
            )
        else:
            incomplete += 1
    metrics = analyze(runs, now)
    queues = [
        (
            datetime.fromisoformat(r["first_job_started_at"].replace("Z", "+00:00"))
            - datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
        ).total_seconds()
        for r in selected_runs(runs, now)
        if r.get("first_job_started_at")
    ]
    metrics["queue_seconds"] = (
        dict(
            sample=len(queues),
            median=statistics.median(queues),
            meaning="run creation to first job start; not billing time",
        )
        if queues
        else None
    )
    metrics["failed_step_categories"] = failure_steps
    metrics.update(
        runner_minutes=runner_seconds / 60 if observed_jobs else None,
        observed_jobs=observed_jobs,
        incomplete_job_samples=incomplete,
    )
    return metrics, runs


def resource_sample(fetch):
    """Two bounded optional metadata reads; outages do not erase run evidence."""
    result = {
        "cache_bytes": None,
        "cache_entries": None,
        "artifact_sample_bytes": None,
        "artifact_sample_count": None,
        "artifact_total_count": None,
        "resource_unavailable": {},
    }

    def integer(value):
        if type(value) is not int or value < 0:
            raise ValueError("Invalid resource measurement")
        return value

    try:
        cache = fetch("/actions/cache/usage")
        size = integer(cache["active_caches_size_in_bytes"])
        count = integer(cache["active_caches_count"])
        result.update(cache_bytes=size, cache_entries=count)
    except Exception as error:
        result["resource_unavailable"]["cache"] = type(error).__name__
    try:
        artifacts = fetch("/actions/artifacts?per_page=30")
        rows = artifacts["artifacts"]
        total = integer(artifacts["total_count"])
        if not isinstance(rows, list) or len(rows) > 30 or total < len(rows):
            raise ValueError("Invalid bounded artifact sample")
        sizes = [integer(row["size_in_bytes"]) for row in rows]
        result.update(
            artifact_sample_bytes=sum(sizes),
            artifact_sample_count=len(rows),
            artifact_total_count=total,
        )
    except Exception as error:
        result["resource_unavailable"]["artifacts"] = type(error).__name__
    return result


def main():
    now = datetime.now(timezone.utc)
    runs = []
    try:
        repository = os.environ["GITHUB_REPOSITORY"]
        token = os.environ["GH_TOKEN"]
        deadline = time.monotonic() + 180

        def fetch(path):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Health sample deadline")
            request = urllib.request.Request(
                "https://api.github.com/repos/" + repository + path,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            with urllib.request.urlopen(
                request, timeout=min(20, remaining)
            ) as response:
                return json.load(response)

        metrics, runs = collect(fetch, now)
        metrics.update(resource_sample(fetch))
        metrics["status"] = "PASS"
    except Exception as error:
        metrics = analyze([], now)
        metrics.update(
            status="UNAVAILABLE",
            reason=type(error).__name__,
            failed_step_categories=None,
            observed_jobs=None,
        )
    metrics.update(
        schema=1,
        tested_sha=os.environ.get("GITHUB_SHA"),
        event=os.environ.get("GITHUB_EVENT_NAME", "local"),
        ref=os.environ.get("GITHUB_REF"),
        run_url=os.environ.get("CI_RUN_URL"),
        baseline=None,
    )
    output = Path("test-results/health")
    output.mkdir(parents=True, exist_ok=True)
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    (output / "runs.json").write_text(
        json.dumps(
            [
                {
                    k: r.get(k)
                    for k in (
                        "id",
                        "event",
                        "head_sha",
                        "conclusion",
                        "run_attempt",
                        "created_at",
                        "run_started_at",
                        "job_completed_at",
                        "first_job_started_at",
                        "first_attempt_conclusion",
                        "jobs_unavailable",
                        "html_url",
                    )
                }
                for r in runs
                if r in selected_runs(runs, now)
            ],
            indent=2,
        )
        + "\n"
    )
    summary = (
        "## CI health (advisory)\n\nUp to 30 completed CI workflow runs from 30 days; separate events. No comparable performance baseline, no flake claim. Elapsed uses last completed job minus workflow start; p95 requires 20 durations. Queue measures creation to first job start when available; critical path/quota unavailable. Runner minutes are observed job time, not a bill. Reruns without first-attempt evidence are excluded from pass rate.\n\n```json\n"
        + json.dumps(metrics, indent=2).replace("`", "\\u0060").replace("<", "\\u003c")
        + "\n```\n"
    )
    (output / "summary.md").write_text(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(summary)


if __name__ == "__main__":
    main()
