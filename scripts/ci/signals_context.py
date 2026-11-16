"""Read-only Actions context for the advisory readiness summary."""

import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode

from health import analyze
from signals_evidence import git, read_json


def commit(value):
    return (
        value
        if isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{40}", value)
        and value != "0" * 40
        else None
    )


def base_sha(root, sha, event_name, event):
    if event_name == "pull_request":
        # The test runs on GitHub's generated merge commit. Its first parent
        # is the exact destination tree used to create the tested candidate.
        try:
            return commit(git(root, "rev-parse", f"{sha}^1").decode().strip())
        except (OSError, subprocess.SubprocessError):
            return None
    if event_name == "merge_group":
        return commit(event.get("merge_group", {}).get("base_sha"))
    if event_name == "push":
        return commit(event.get("before"))
    if (
        event_name == "workflow_dispatch"
        and os.environ.get("GITHUB_REF") == "refs/heads/main"
    ):
        try:
            return commit(git(root, "rev-parse", f"{sha}^1").decode().strip())
        except (OSError, subprocess.SubprocessError):
            return None
    return None


def load_base(root, repo, sha):
    if not sha:
        return
    try:
        git(root, "cat-file", "-e", f"{sha}^{{commit}}")
    except subprocess.CalledProcessError:
        token = os.environ["GH_TOKEN"]
        auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env = dict(
            os.environ,
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
            GIT_CONFIG_VALUE_0="AUTHORIZATION: basic " + auth,
            GIT_TERMINAL_PROMPT="0",
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "fetch",
                "--no-tags",
                "--depth=1",
                f"https://github.com/{repo}.git",
                sha,
            ],
            env=env,
            check=True,
            timeout=20,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def actions(repo, endpoint, **kwargs):
    path = f"repos/{repo}/actions/{endpoint}"
    if kwargs:
        path += "?" + urlencode(kwargs)
    result = subprocess.check_output(
        ["gh", "api", path], timeout=10, stderr=subprocess.DEVNULL
    )
    return json.loads(result)


def baseline(repo, sha, destination):
    if not sha:
        return None
    result = actions(
        repo,
        "workflows/ci.yml/runs",
        head_sha=sha,
        branch="main",
        event="push",
        status="success",
        per_page=5,
    )
    for run in result["workflow_runs"]:
        if (run.get("head_sha"), run.get("conclusion"), run.get("event")) != (
            sha,
            "success",
            "push",
        ):
            continue
        run_id, attempt = run["id"], run["run_attempt"]
        if not all(type(n) is int and n > 0 for n in (run_id, attempt)):
            continue
        folder = destination / str(run_id)
        subprocess.run(
            [
                "gh",
                "run",
                "download",
                str(run_id),
                "--repo",
                repo,
                "--name",
                f"ci-readiness-{run_id}-{attempt}",
                "--dir",
                str(folder),
            ],
            timeout=15,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        values = read_json(folder / "signals.json")
        if (
            values.get("schema"),
            values.get("tested_sha"),
            values.get("run_id"),
            values.get("run_attempt"),
        ) == (1, sha, str(run_id), str(attempt)) and read_json(
            folder / "metrics.json"
        ).get("overall") == "PASS":
            return values
    return None


def slowest_job(data):
    durations = []
    for job in data.get("jobs", []):
        if (
            job.get("status") != "completed"
            or not job.get("started_at")
            or not job.get("completed_at")
        ):
            continue
        duration = (
            datetime.fromisoformat(job["completed_at"])
            - datetime.fromisoformat(job["started_at"])
        ).total_seconds()
        if duration >= 0:
            durations.append(
                dict(
                    name=job["name"], seconds=duration, conclusion=job.get("conclusion")
                )
            )
    return max(durations, key=lambda job: job["seconds"], default=None)


def inherited_artifact_attempts(data, run, attempt):
    """An older report qualifies only when GitHub kept that successful job."""
    lanes = {
        "Offline checks": ("ci-offline", None),
        "Source, security and package": ("ci-quality", None),
        "Ordinary browser journey": ("ci-browser", None),
    }
    attempts = {}
    seen = set()
    for job in data.get("jobs", []):
        name = job.get("name", "")
        shard = re.fullmatch(
            r"PostgreSQL storage / SQL migrations and boards \((\d+)\)", name
        )
        key = ("storage", shard[1]) if shard else lanes.get(name)
        if key is None:
            continue
        version = job.get("run_attempt")
        if key in seen:
            attempts.pop(key, None)
        elif (
            str(job.get("run_id")) == str(run)
            and job.get("status") == "completed"
            and job.get("conclusion") == "success"
            and type(version) is int
            and 0 < version < int(attempt)
        ):
            attempts[key] = version
        seen.add(key)
    return attempts


def collect(root, sha, run, destination):
    payload = os.environ.get("GITHUB_EVENT_PATH")
    event = read_json(Path(payload)) if payload else {}
    base = commit(os.environ.get("CI_SIGNALS_BASE")) or base_sha(
        root, sha, os.environ.get("GITHUB_EVENT_NAME"), event
    )
    context = dict(
        base_sha=base, baseline=None, slowest=None, health=None, inherited_attempts={}
    )
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not os.environ.get(
        "GH_TOKEN"
    ):
        return context
    now = datetime.now(timezone.utc)
    if str(run).isdigit():
        try:
            data = actions(repo, f"runs/{run}/jobs", filter="latest", per_page=100)
            context["inherited_attempts"] = inherited_artifact_attempts(
                data, run, os.environ.get("GITHUB_RUN_ATTEMPT", "1")
            )
            context["slowest"] = slowest_job(data)
        except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError):
            pass
    operations = (
        ("base_available", lambda: load_base(root, repo, base)),
        ("baseline", lambda: baseline(repo, base, destination)),
        (
            "health",
            lambda: analyze(
                actions(
                    repo,
                    "workflows/ci.yml/runs",
                    per_page=30,
                    status="completed",
                    created=">=" + (now - timedelta(days=30)).date().isoformat(),
                )["workflow_runs"],
                now,
            ),
        ),
    )
    for key, get in operations:
        try:
            context[key] = get()
        except (OSError, KeyError, TypeError, ValueError, subprocess.SubprocessError):
            context[key] = None
    return context
