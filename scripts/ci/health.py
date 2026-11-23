"""Bounded, read-only Actions sample; no inferred flakes or billing costs."""

from datetime import datetime, timedelta, timezone
from collections import defaultdict
import json
import os
from pathlib import Path
import statistics
import time
import urllib.request

from reporting import behavior_table, run_reference, safe


def selected_runs(runs, now):
    window = now - timedelta(days=30)
    return [
        r
        for r in runs[:30]
        if r["name"] == os.environ.get("CI_HISTORY_WORKFLOW_NAME", "CI")
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
    for event in (
        "pull_request",
        "push",
        "workflow_dispatch",
        "merge_group",
        "schedule",
    ):
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
            if (
                r["run_attempt"] == 1
                and r["conclusion"] in ("success", "failure")
                and r.get("job_completed_at")
            ):
                start = datetime.fromisoformat(
                    r["run_started_at"].replace("Z", "+00:00")
                )
                end = datetime.fromisoformat(
                    r["job_completed_at"].replace("Z", "+00:00")
                )
                if end >= start:
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
    timed_jobs = 0
    observed_runner_seconds = 0
    incomplete = 0
    skipped_jobs = 0
    unmeasured_steps = 0
    job_times, step_times, event_seconds = (
        defaultdict(list),
        defaultdict(list),
        defaultdict(float),
    )

    def duration(row):
        try:
            start, end = (
                datetime.fromisoformat(row[k].replace("Z", "+00:00"))
                for k in ("started_at", "completed_at")
            )
            if start.utcoffset() is None or end.utcoffset() is None or end < start:
                return None
            return (end - start).total_seconds()
        except (KeyError, TypeError, ValueError, AttributeError):
            return None

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
            if (
                not isinstance(jobs, list)
                or type(response["total_count"]) is not int
                or response["total_count"] < len(jobs)
            ):
                raise ValueError("Malformed job inventory")
        except Exception as error:
            run["jobs_unavailable"] = type(error).__name__
            incomplete += 1
            continue
        completed = []
        executed = []
        for job in jobs:
            if not isinstance(job, dict):
                executed.append(None)
                continue
            if job.get("conclusion") == "skipped":
                skipped_jobs += 1
                continue
            executed.append(job)
            seconds = duration(job)
            if seconds is not None:
                completed.append(job)
                timed_jobs += 1
                observed_runner_seconds += seconds
                event_seconds[run["event"]] += seconds
                label = (
                    job.get("name")
                    if isinstance(job.get("name"), str)
                    else "Unnamed job"
                )
                job_times[label].append(seconds)
            for step in job.get("steps") or []:
                if not isinstance(step, dict):
                    unmeasured_steps += 1
                    continue
                if step.get("conclusion") == "failure":
                    label = (
                        step.get("name")
                        if isinstance(step.get("name"), str)
                        else "Unnamed step"
                    )
                    failure_steps[label] = failure_steps.get(label, 0) + 1
                if step.get("conclusion") != "skipped":
                    seconds = duration(step)
                    if seconds is None:
                        unmeasured_steps += 1
                    else:
                        label = (
                            step.get("name")
                            if isinstance(step.get("name"), str)
                            else "Unnamed step"
                        )
                        step_times[label].append(seconds)
        if (
            completed
            and len(completed) == len(executed)
            and len(jobs) == response["total_count"]
        ):
            run["first_job_started_at"] = min(j["started_at"] for j in completed)
            run["job_completed_at"] = max(j["completed_at"] for j in completed)
            observed_jobs += len(completed)
            runner_seconds += sum(duration(job) for job in completed)
        else:
            incomplete += 1
    metrics = analyze(runs, now)
    queues = [
        (
            datetime.fromisoformat(r["first_job_started_at"].replace("Z", "+00:00"))
            - datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
        ).total_seconds()
        for r in selected_runs(runs, now)
        if r["run_attempt"] == 1 and r.get("first_job_started_at")
    ]
    queues = [seconds for seconds in queues if seconds >= 0]
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
        observed_runner_minutes=observed_runner_seconds / 60 if timed_jobs else None,
        timed_jobs=timed_jobs,
        incomplete_job_samples=incomplete,
        skipped_jobs=skipped_jobs,
        unmeasured_steps=unmeasured_steps,
        runner_minutes_scope="complete job inventories of sampled latest CI attempts; not billing",
        observed_runner_minutes_scope="all valid latest-attempt job timings, including partial inventories; lower bound, not billing",
        unobserved_prior_attempts=sum(
            r["run_attempt"] - 1 for r in selected_runs(runs, now)
        ),
        runner_minutes_by_event={
            event: seconds / 60 for event, seconds in event_seconds.items()
        },
        job_timings={
            name: dict(
                samples=len(values),
                seconds=sum(values),
                median_seconds=statistics.median(values),
            )
            for name, values in job_times.items()
        },
        step_timings={
            name: dict(
                samples=len(values),
                seconds=sum(values),
                median_seconds=statistics.median(values),
            )
            for name, values in step_times.items()
        },
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


def render_summary(metrics):
    measured = metrics["status"] == "PASS" and metrics["ci_runs"] > 0
    result = "PASS" if measured else "NOT RUN"
    text = "## CI health (advisory)\n\n" + behavior_table(
        [
            (
                "Read a bounded sample of completed CI runs",
                result,
                "Shows how often CI succeeds on the first attempt and where reruns occur",
                "Read-only Actions API. "
                + (
                    f"{metrics['ci_runs']} runs in the 30-day window"
                    if measured
                    else metrics.get("reason", "No completed runs in the window")
                ),
            )
        ],
        "The sample covers up to 30 completed runs across changing commits. Timings use first attempts, and p95 uses the existing minimum of 20 observations. A rerun recovery does not identify a flaky test. Critical path, billing and comparable performance baselines are unavailable.",
    )
    text += f"Sampled {safe(metrics['retrieved_at'])}. {run_reference()}.\n\n"
    text += "| Event | Runs | First-attempt successes | Reruns / recovered | Cancelled | Median / p95 elapsed (s) |\n|---|---:|---|---|---:|---|\n"
    for event, values in metrics["events"].items():
        rate = values["first_attempt_pass_rate"]
        observed = values["first_attempt_observed"]
        first = "Unavailable" if rate is None else f"{rate:.0%} of {observed} observed"
        text += (
            f"| {safe(event)} | {values['runs']} | {first} | "
            f"{values['rerun_runs']} / {values['observed_rerun_recoveries']} | {values['cancelled']} | "
            f"{safe(values['median_elapsed_seconds'])} / {safe(values['p95_elapsed_seconds'])} "
            f"({values['duration_sample']} measured) |\n"
        )
    queue = metrics.get("queue_seconds")
    text += f"\nMedian time to first job (s): {safe(queue['median'] if queue else None)}. Complete-inventory runner minutes: {safe(metrics.get('runner_minutes'))}. Observed job minutes including partial inventories: {safe(metrics.get('observed_runner_minutes'))}.\n"
    text += (
        "\nCompute covers only observed jobs in each sampled run's latest attempt. "
        f"Prior attempts not measured: {safe(metrics.get('unobserved_prior_attempts'))}. "
        f"Incomplete job samples: {safe(metrics.get('incomplete_job_samples'))}. "
        f"Skipped jobs: {safe(metrics.get('skipped_jobs'))}. "
        "Partial observations are lower bounds, not zero usage or billing.\n"
    )
    for heading, key in (
        ("Job execution", "job_timings"),
        ("Step execution (setup, tests and reports)", "step_timings"),
    ):
        values = metrics.get(key, {})
        text += f"\n### {heading}\n\n| Name | Measured samples | Summed seconds | Median seconds |\n|---|---:|---:|---:|\n"
        for name, value in sorted(values.items(), key=lambda item: -item[1]["seconds"]):
            text += f"| {safe(name)} | {value['samples']} | {value['seconds']:.1f} | {value['median_seconds']:.1f} |\n"
        if not values:
            text += "| Unavailable | — | — | — |\n"
    text += f"\nUnmeasured non-skipped steps: {safe(metrics.get('unmeasured_steps'))}. Step totals exclude unreported runner overhead; overlapping workflow jobs are summed separately.\n"
    text += f"\nRepository cache bytes: {safe(metrics.get('cache_bytes'))}. Bytes in sampled artifacts: {safe(metrics.get('artifact_sample_bytes'))}. See the current health artifact for job failures and measurement limits.\n"
    return text


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
        run_id=os.environ.get("GITHUB_RUN_ID"),
        run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
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
    summary = render_summary(metrics)
    (output / "summary.md").write_text(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(summary)


if __name__ == "__main__":
    main()
