"""Report the manual release stages using the workflow's actual outcomes."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform

from reporting import STATUS, behavior_table, run_reference, safe, step_status


STAGES = {
    "proxy": (
        "Public proxy routes and Admin authentication",
        "Keeps Admin behind its authentication boundary",
    ),
    "smoke": (
        "Build and smoke-test all three service images",
        "Checks the web, collector and archive roles together before publication",
    ),
    "publish": (
        "Publish the tested images by digest",
        "Binds the release to the images exercised by the smoke tests",
    ),
    "deploy": (
        "Deploy the published digests",
        "Verifies that the selected commit is still the branch tip before handing off to the host",
    ),
}


def evaluate(needs, *, branch, publish_only, deploy_enabled):
    image = step_status(needs, "release-image", "result")
    deploy = step_status(needs, "deploy-hetzner", "result")
    skip_reason = (
        "Publication is branch-only."
        if not branch
        else "Publish-only dispatch."
        if publish_only
        else "The repository deployment variable is disabled."
        if not deploy_enabled
        else "Image verification and publication did not succeed."
        if image != "PASS"
        else None
    )
    steps = {}
    for name in STAGES:
        job = "deploy-hetzner" if name == "deploy" else "release-image"
        outcome = deploy if name == "deploy" else image
        entry = needs.get(job) if isinstance(needs, dict) else None
        outputs = entry.get("outputs") if isinstance(entry, dict) else None
        value = outputs.get(name) if isinstance(outputs, dict) else None
        status = STATUS.get(value, "NOT RUN") if isinstance(value, str) else "NOT RUN"
        if status == "NOT RUN" and outcome in ("CANCELLED", "SKIPPED"):
            status = outcome
        steps[name] = status
    if not branch and image == deploy == "SKIPPED":
        overall = "SKIPPED"
    elif image == "CANCELLED" or deploy == "CANCELLED":
        overall = "CANCELLED"
    elif (
        branch
        and image == "PASS"
        and all(steps[name] == "PASS" for name in ("proxy", "smoke", "publish"))
        and (
            deploy == "SKIPPED" if skip_reason else deploy == steps["deploy"] == "PASS"
        )
    ):
        overall = "PASS"
    else:
        overall = "FAIL"
    return overall, steps, skip_reason, image, deploy


def main():
    try:
        needs = json.loads(os.environ.get("RELEASE_OUTCOMES", "{}"))
    except ValueError:
        needs = None
    overall, steps, skip_reason, image, deploy = evaluate(
        needs,
        branch=os.environ.get("GITHUB_REF_TYPE") == "branch",
        publish_only=os.environ.get("RELEASE_PUBLISH_ONLY") == "true",
        deploy_enabled=os.environ.get("RELEASE_DEPLOY_ENABLED") == "true",
    )
    result = dict(
        schema=1,
        overall=overall,
        tested_sha=os.environ.get("GITHUB_SHA"),
        ref=os.environ.get("GITHUB_REF"),
        event=os.environ.get("GITHUB_EVENT_NAME"),
        run_id=os.environ.get("GITHUB_RUN_ID"),
        run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
        run_url=os.environ.get("CI_RUN_URL"),
        timestamp=datetime.now(timezone.utc).isoformat(),
        image_job=image,
        deploy_job=deploy,
        deployment_skip_reason=skip_reason if deploy == "SKIPPED" else None,
        steps=steps,
    )
    text = f"## Release result · {overall}\n\n" + behavior_table(
        [
            (
                title,
                steps[name],
                purpose,
                skip_reason
                if name == "deploy" and deploy == "SKIPPED" and skip_reason
                else f"Release step {name}",
            )
            for name, (title, purpose) in STAGES.items()
        ],
        "The Compose smoke uses disposable state. The deploy result records the host handoff. Installed provider activity and owner acceptance require their own evidence.",
    )
    text += (
        f"Candidate `{safe(result['tested_sha'])}`. Ref `{safe(result['ref'])}`. "
        f"Event {safe(result['event'])}, attempt {safe(result['run_attempt'])}. "
        f"Ubuntu 24.04 runner · summary Python {platform.python_version()}. {run_reference()}.\n"
    )
    if overall in ("FAIL", "CANCELLED"):
        text += f"\nInspect the first failed or unreached stage in the run. Image job {image}. Deployment job {deploy}.\n"
    output = Path("test-results/release")
    output.mkdir(parents=True, exist_ok=True)
    (output / "metrics.json").write_text(json.dumps(result, indent=2) + "\n")
    (output / "summary.md").write_text(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(text)
    print(f"Release result: {overall}")
    return int(overall in ("FAIL", "CANCELLED"))


if __name__ == "__main__":
    raise SystemExit(main())
