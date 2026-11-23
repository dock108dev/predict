"""Fast releases refuse stale, misidentified and over-budget server handoffs."""

from pathlib import Path
from runpy import run_path
from types import SimpleNamespace
import time

import pytest


module = run_path(str(Path(__file__).resolve().parents[1] / "deploy/fast-release.py"))
SHA = "a" * 40
REPOSITORY = module["REPOSITORY"]


@pytest.fixture
def release(tmp_path, monkeypatch):
    for key, value in dict(
        RELEASE_SHA=SHA,
        GITHUB_REPOSITORY="dock108dev/predict",
        GITHUB_ACTOR="fixture",
        GH_TOKEN="fixture-token",
        HETZNER_DEPLOY_ENABLED="true",
        SSH_HOST="fixture.invalid",
        SSH_KEY="fixture-key",
        SSH_KNOWN_HOSTS="fixture-known-host",
    ).items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("PREDICT_CICD_STARTED", raising=False)
    monkeypatch.delenv("RELEASE_PUBLISH_ONLY", raising=False)

    class Fixture(module["Release"]):
        def __init__(self):
            super().__init__(tmp_path)
            self.commands = []
            self.requests = []
            self.tips = [SHA, SHA]
            self.checkout = SHA

        def run(self, command, **kwargs):
            self.commands.append(command)
            if command[0] == "ssh":
                self.requests.append(kwargs["stdin"])
            if command[:2] == ["git", "rev-parse"]:
                value = self.checkout
            elif command[:2] == ["gh", "api"]:
                value = self.tips.pop(0)
            elif command == ["python", "deploy/image-inputs.py"]:
                value = "\n".join(role + " " + "b" * 64 for role in module["ROLES"])
            elif command == ["python", "scripts/ci/fast_checks.py"]:
                value = "focused checks passed"
            else:
                assert (
                    command[:2] in (["docker", "login"], ["bash", "deploy/smoke.sh"])
                    or command[0] == "ssh"
                )
                value = ""
            return SimpleNamespace(returncode=0, stdout=value)

        def proxy(self):
            pass

        def build(self, role, fingerprint):
            return dict(role=role, tag=role, inputs=fingerprint)

        def publish(self, image):
            return dict(image, digest=REPOSITORY + "@sha256:" + "c" * 64)

    return Fixture()


def test_checked_revision_must_match_checkout_before_any_release(release):
    release.checkout = "b" * 40
    with pytest.raises(ValueError, match="Checkout"):
        release.execute()
    assert len(release.commands) == 1


@pytest.mark.parametrize("tips", [["b" * 40], [SHA, "b" * 40]])
def test_main_advancing_before_build_or_handoff_never_contacts_server(release, tips):
    release.tips = tips
    release.execute()
    assert release.result["status"] == "SKIPPED"
    assert not release.result["deployed"]
    assert not any(command[0] == "ssh" for command in release.commands)


def test_publish_only_has_no_server_or_main_requirement(release):
    release.publish_only = True
    release.execute()
    assert release.result["status"] == "PASS"
    assert not release.result["deployed"]
    assert not any(command[0] in ("ssh", "gh") for command in release.commands)
    assert ["python", "scripts/ci/fast_checks.py"] in release.commands


def test_current_checked_revision_hands_only_pinned_manifest_to_server(release):
    release.execute()
    assert release.result["status"] == "PASS" and release.result["deployed"]
    assert sum(command[0] == "ssh" for command in release.commands) == 1
    assert len(release.result["images"]) == 3
    assert release.requests[0].startswith("predict-images-fast-v1\n")


@pytest.mark.parametrize("stage", ["proxy", "publish"])
def test_parallel_candidate_failure_never_contacts_server(release, stage):
    def fail(*args, **kwargs):
        raise RuntimeError("candidate failed")

    setattr(release, stage, fail)
    with pytest.raises(RuntimeError, match="candidate failed"):
        release.execute()
    assert not release.requests
    assert not release.result["deployed"]


def test_failed_focused_checks_never_send_a_server_request(release):
    original_run = release.run

    def run(command, **kwargs):
        if command == ["python", "scripts/ci/fast_checks.py"]:
            release.commands.append(command)
            raise RuntimeError("focused checks failed")
        return original_run(command, **kwargs)

    release.run = run
    with pytest.raises(RuntimeError, match="focused checks failed"):
        release.execute()
    assert not release.requests
    assert not release.result["deployed"]
    assert "checks" in release.phases


def test_budget_exhaustion_refuses_before_starting_image_work(release):
    release.started = int(time.time()) - 100
    with pytest.raises(RuntimeError, match="existing server was not changed"):
        release.execute()
    assert not any(command[0] in ("docker", "ssh") for command in release.commands)


def test_cached_role_input_mismatch_refuses_reuse(release):
    release.run = lambda command, **kwargs: SimpleNamespace(
        returncode=0, stdout="wrong-role wrong-inputs"
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        module["Release"].build(release, "web", "b" * 64)


@pytest.mark.parametrize(
    "values",
    [
        [],
        ["other.invalid@sha256:" + "a" * 64],
        [REPOSITORY + "@sha256:" + c * 64 for c in "ab"],
    ],
)
def test_only_one_exact_repository_digest_can_authorize_a_role(values):
    with pytest.raises(ValueError, match="exactly one"):
        module["image_digest"](values)


def test_elapsed_budget_uses_runner_start_including_setup():
    assert module["remaining"](100, now=125) == 85
