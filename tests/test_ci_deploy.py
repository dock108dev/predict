from pathlib import Path
from runpy import run_path
import subprocess
import sys
import json

import pytest

from tests.ci_support import load


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "deploy/release.sh"
ROLES = ("web", "collector", "archive")
DIGEST_PREFIX = "ghcr.io/dock108dev/predict@sha256:"


@pytest.mark.parametrize(
    (
        "image",
        "stages",
        "deploy",
        "deploy_step",
        "publish_only",
        "enabled",
        "branch",
        "result",
        "reason",
    ),
    [
        (
            "success",
            ("success",) * 3,
            "success",
            "success",
            False,
            True,
            True,
            "PASS",
            None,
        ),
        (
            "success",
            ("success",) * 3,
            "skipped",
            None,
            True,
            True,
            True,
            "PASS",
            "Publish-only",
        ),
        (
            "success",
            ("success",) * 3,
            "skipped",
            None,
            False,
            False,
            True,
            "PASS",
            "deployment variable",
        ),
        (
            "failure",
            ("success", "failure", "skipped"),
            "skipped",
            None,
            False,
            True,
            True,
            "FAIL",
            "did not succeed",
        ),
        ("success", ("success",) * 3, "skipped", None, False, True, True, "FAIL", None),
        ("success", ("success",) * 3, "success", None, False, True, True, "FAIL", None),
        (
            "cancelled",
            (),
            "skipped",
            None,
            False,
            True,
            True,
            "CANCELLED",
            "did not succeed",
        ),
        ("skipped", (), "skipped", None, False, True, False, "SKIPPED", "branch-only"),
    ],
)
def test_release_summary_uses_observed_stages_and_intentional_skips(
    image, stages, deploy, deploy_step, publish_only, enabled, branch, result, reason
):
    report = load("release_report")
    needs = {
        "release-image": dict(
            result=image, outputs=dict(zip(("proxy", "smoke", "publish"), stages))
        ),
        "deploy-hetzner": dict(result=deploy, outputs={"deploy": deploy_step}),
    }
    overall, steps, skipped, _, _ = report.evaluate(
        needs, branch=branch, publish_only=publish_only, deploy_enabled=enabled
    )
    assert overall == result
    if reason:
        assert reason in skipped
    else:
        assert skipped is None
    if deploy == "skipped":
        assert steps["deploy"] == "SKIPPED"


def test_release_workflow_report_preserves_failed_stage_and_retains_artifact(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("GITHUB_REF_TYPE", "branch")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("RELEASE_DEPLOY_ENABLED", "true")
    monkeypatch.setenv("RELEASE_PUBLISH_ONLY", "false")
    summary = tmp_path / "job-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv(
        "RELEASE_OUTCOMES",
        json.dumps(
            {
                "release-image": {
                    "result": "failure",
                    "outputs": {"proxy": "success", "smoke": "failure"},
                },
                "deploy-hetzner": {"result": "skipped"},
            }
        ),
    )
    process = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci/release_report.py")],
        cwd=tmp_path,
        timeout=10,
    )
    assert process.returncode == 1
    result = json.loads((tmp_path / "test-results/release/metrics.json").read_text())
    assert result["tested_sha"] == "a" * 40
    assert result["steps"] == dict(
        proxy="PASS", smoke="FAIL", publish="NOT RUN", deploy="SKIPPED"
    )
    assert "What was tested and why it matters" in summary.read_text()


@pytest.mark.parametrize(
    ("path", "affected"),
    [
        ("app/dashboard/opportunity_static/current/desk.js", {"web"}),
        ("app/dashboard/opportunity_static/current/predict-icon.png", {"web"}),
        ("app/collection/ordinary_worker.py", {"collector"}),
        ("app/dashboard/snapshot_api.py", set(ROLES)),
        ("app/storage/migrations/093_shared.sql", set(ROLES)),
        ("uv.lock", set(ROLES)),
        ("docs/hetzner.md", set()),
    ],
)
def test_role_fingerprints_route_shared_and_role_only_changes(path, affected):
    fingerprints = run_path(str(ROOT / "deploy/image-inputs.py"))["fingerprints"]
    before = fingerprints(b"100644 blob old\t" + path.encode() + b"\0")
    after = fingerprints(b"100644 blob new\t" + path.encode() + b"\0")
    assert {role for role in ROLES if before[role] != after[role]} == affected


@pytest.fixture
def release_host(tmp_path):
    previous = [DIGEST_PREFIX + value * 64 for value in "abc"]
    candidate = [DIGEST_PREFIX + value * 64 for value in "def"]
    installed = tmp_path / "current-images.env"

    def image_env(images):
        return "".join(
            f"PREDICT_{role.upper()}_IMAGE={image}\n"
            for role, image in zip(ROLES, images, strict=True)
        )

    installed.write_text(image_env(previous))
    for file in (
        "compose.yml",
        "applied-compose.yml",
        "collection-enabled",
        "archive.env",
    ):
        (tmp_path / file).touch()
    (tmp_path / "backups").mkdir()
    labels = tmp_path / "labels"
    invocations = tmp_path / "invocations"

    def run(*, changed, pending=0, bad_web=False, bad_label=False, legacy=False):
        old_inputs = [value * 64 for value in "123"]
        new_inputs = [
            "9" * 64 if role in changed else old_inputs[index]
            for index, role in enumerate(ROLES)
        ]
        labels.write_text(
            "".join(
                f"{image} {role} {key}\n"
                for images, keys in ((previous, old_inputs), (candidate, new_inputs))
                for role, image, key in zip(ROLES, images, keys, strict=True)
                if not (bad_label and image == candidate[0])
            )
        )
        if legacy:
            installed.unlink()
            (tmp_path / "current-image").write_text(previous[0] + "\n")
        header = "predict-images-v1\nfixture-user\nfixture-token\n"
        request = header + "".join(
            f"{image} {key}\n" for image, key in zip(candidate, new_inputs, strict=True)
        )
        result = subprocess.run(
            [
                "bash",
                "-c",
                r"""
source "$1"
pending_fixture=$2
bad_web=$3
candidate_web=$4
old_web=$5
docker() {
    printf '%s\n' "$*" >> invocations
    case "$1 $2" in
        'image inspect') awk -v ref="$5" '$1==ref {print $2, $3}' labels ;;
        --config*) if [[ $3 == login ]]; then cat >/dev/null; fi ;;
        'compose --env-file')
            shift 7
            case "$1" in
                ps) echo running ;;
                exec) echo dump ;;
                run)
                    if [[ $* == *' python -c '* ]]; then
                        if [[ $PREDICT_WEB_IMAGE == "$old_web" ]]; then echo 0; else echo "$pending_fixture"; fi
                    fi
                    ;;
                up)
                    printf 'active %s %s %s\n' "$PREDICT_WEB_IMAGE" "$PREDICT_COLLECTOR_IMAGE" "$PREDICT_ARCHIVE_IMAGE" >> invocations
                    if [[ $bad_web == 1 && $PREDICT_WEB_IMAGE == "$candidate_web" && "${*: -1}" == web ]]; then return 1; fi
                    ;;
            esac
            ;;
    esac
}
release
""",
                "fixture",
                str(RELEASE),
                str(pending),
                str(int(bad_web)),
                candidate[0],
                previous[0],
            ],
            cwd=tmp_path,
            input=request,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result, invocations.read_text().splitlines()

    return previous, candidate, installed, image_env, run


@pytest.mark.parametrize("role", ROLES)
def test_rolls_only_the_service_with_changed_inputs(release_host, role):
    previous, candidate, installed, image_env, run = release_host
    result, commands = run(changed={role})
    assert result.returncode == 0, result.stderr
    assert [
        line.rsplit(" ", 1)[-1]
        for line in commands
        if "compose " in line and " up " in line
    ] == ["db", role]
    assert not any(" stop " in line for line in commands)
    assert any(" up -d --wait --no-recreate db" in line for line in commands)
    assert [line.rsplit(" ", 1)[-1] for line in commands if " pull " in line] == [
        candidate[ROLES.index(role)]
    ]
    active = [
        candidate[i] if name == role else previous[i] for i, name in enumerate(ROLES)
    ]
    assert installed.read_text() == image_env(active)


def test_rebuilding_the_same_inputs_reuses_all_installed_images(release_host):
    previous, _, installed, image_env, run = release_host
    result, commands = run(changed=set())
    assert result.returncode == 0, result.stderr
    assert not any(" pull " in line or " up -d --no-deps " in line for line in commands)
    assert installed.read_text() == image_env(previous)


def test_archive_settings_change_does_not_recreate_web(release_host):
    previous, _, installed, image_env, run = release_host
    (installed.parent / "archive.env").write_text("PREDICT_ODDS_ARCHIVE_CAPTURE=1\n")
    (installed.parent / "applied-archive-env").write_text("prior checkout\n")
    result, commands = run(changed=set())
    assert result.returncode == 0, result.stderr
    assert [line.rsplit(" ", 1)[-1] for line in commands if " up " in line] == [
        "db",
        "collector",
        "archive",
    ]
    assert installed.read_text() == image_env(previous)


def test_failed_web_rolls_back_web_only(release_host):
    previous, _, installed, image_env, run = release_host
    result, commands = run(changed={"web"}, bad_web=True)
    assert result.returncode != 0
    assert "Restored the previous images" in result.stderr
    assert sum(" up " in line and line.endswith(" web") for line in commands) == 2
    assert not any(
        " up " in line and line.endswith((" collector", " archive"))
        for line in commands
    )
    assert installed.read_text() == image_env(previous)


def test_forward_migration_backs_up_and_releases_together(release_host):
    _, candidate, installed, image_env, run = release_host
    result, commands = run(changed=set(ROLES), pending=1)
    assert result.returncode == 0, result.stderr
    stops = [i for i, command in enumerate(commands) if " stop " in command]
    backup = next(i for i, command in enumerate(commands) if " pg_dump " in command)
    migrate = next(
        i
        for i, command in enumerate(commands)
        if command.endswith("app.storage migrate")
    )
    rollout = next(
        i for i, command in enumerate(commands) if command.endswith("180 web collector")
    )
    assert len(stops) == 2 and max(stops) < backup < migrate < rollout
    assert not any("stop db" in line for line in commands)
    assert installed.read_text() == image_env(candidate)


def test_wrong_image_label_fails_before_compose(release_host):
    previous, _, installed, image_env, run = release_host
    result, commands = run(changed={"web"}, bad_label=True)
    assert result.returncode != 0
    assert not any(command.startswith("compose ") for command in commands)
    assert installed.read_text() == image_env(previous)


def test_first_split_release_accepts_existing_single_image_state(release_host):
    previous, candidate, installed, image_env, run = release_host
    result, _ = run(changed=set(ROLES), legacy=True)
    assert result.returncode == 0, result.stderr
    assert installed.read_text() == image_env(candidate)
    assert installed.with_name("previous-images.env").read_text() == image_env(
        [previous[0]] * 3
    )
