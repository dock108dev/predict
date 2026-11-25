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
        "prepare": dict(
            result="success",
            outputs=dict(
                state="ready" if branch else "skipped",
                qualification="success" if branch else "skipped",
                reason="Publication is branch-only." if not branch else None,
            ),
        ),
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
                "prepare": {
                    "result": "success",
                    "outputs": {"state": "ready", "qualification": "success"},
                },
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
        qualification="PASS",
        proxy="PASS",
        smoke="FAIL",
        publish="NOT RUN",
        deploy="SKIPPED",
    )
    assert "What was tested and why it matters" in summary.read_text()


@pytest.mark.parametrize(
    ("path", "affected"),
    [
        ("app/dashboard/opportunity_static/current/desk.js", {"web"}),
        ("app/dashboard/opportunity_static/current/predict-icon.png", {"web"}),
        ("app/collection/ordinary_worker.py", {"collector"}),
        ("deploy/compose.yml", {"web"}),
        ("deploy/predict.Caddyfile", {"web"}),
        ("deploy/release.sh", {"web"}),
        ("deploy/managed-config.py", {"web"}),
        ("deploy/image-cleanup.py", {"web"}),
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
    for name in ("compose.yml", "applied-compose.yml"):
        (tmp_path / name).write_text("original-compose\n")
    (tmp_path / "release.sh").write_text("original-release\n")
    (tmp_path / "collection-enabled").touch()
    (tmp_path / "archive.env").touch()
    (tmp_path / "backups").mkdir()
    caddy = tmp_path / "caddy"
    caddy.mkdir()
    (caddy / "Caddyfile").write_text("import /etc/caddy/predict.Caddyfile\n")
    (caddy / "predict.Caddyfile").write_text("original-proxy\n")
    executable = tmp_path / "bin"
    executable.mkdir()
    (executable / "caddy").write_text(
        "#!/bin/sh\nprintf 'caddy %s\\n' \"$*\" >> invocations\n"
    )
    (executable / "systemctl").write_text(
        "#!/bin/sh\nprintf 'systemctl %s\\n' \"$*\" >> invocations\n"
        "if [ -f fail-proxy ]; then rm fail-proxy; exit 1; fi\n"
    )
    for file in executable.iterdir():
        file.chmod(0o755)
    payload = tmp_path / "bundle"
    payload.mkdir()
    for name in ("release.sh", "managed-config.py", "image-cleanup.py"):
        source = ROOT / "deploy" / name
        (payload / name).write_text(
            source.read_text() if source.exists() else "print('fixture cleanup')\n"
        )
    (payload / "compose.yml").write_text("original-compose\n")
    (payload / "predict.Caddyfile").write_text("candidate-proxy\n")

    def configuration():
        def bind(source, target, readonly=False):
            return dict(
                type="bind",
                source=str(tmp_path / source),
                target=target,
                read_only=readonly,
            )

        socket = bind("socket", "/run/predict-postgres", True)
        return dict(
            name="predict",
            volumes=dict(postgres=dict(name="predict_postgres")),
            services=dict(
                db=dict(
                    network_mode="none",
                    volumes=[
                        dict(
                            type="volume",
                            source="postgres",
                            target="/var/lib/postgresql/data",
                        ),
                        bind("socket", "/run/predict-postgres"),
                    ],
                ),
                web=dict(
                    environment=dict(PREDICT_DATABASE_CAP_GIB="4"),
                    ports=[dict(host_ip="127.0.0.1", published="8784", target=8784)],
                    volumes=[bind("state", "/predict/.local"), socket],
                ),
                collector=dict(
                    environment=dict(PREDICT_DATABASE_CAP_GIB="4"),
                    volumes=[
                        bind("state", "/predict/.local"),
                        socket,
                        bind("provider-secrets", "/run/predict-secrets", True),
                    ],
                ),
                archive=dict(
                    network_mode="none", volumes=[socket, bind("archive", "/archive")]
                ),
            ),
        )

    (tmp_path / "previous-compose.json").write_text(json.dumps(configuration()))
    labels = tmp_path / "labels"
    invocations = tmp_path / "invocations"

    def run(
        *,
        changed,
        pending=0,
        bad_web=False,
        bad_label=False,
        legacy=False,
        bad_managed=False,
        bad_archive=False,
        bad_proxy=False,
        managed_changed=False,
        unhealthy_reused="",
        cleanup_failure=False,
        fast=False,
        split_roles=False,
    ):
        import os

        config = configuration()
        if split_roles:
            for role in ROLES:
                service = config["services"][role]
                service.setdefault("environment", {}).update(
                    PREDICT_DB_ROLE="predict_" + role,
                    PREDICT_DB_PASSWORD_FILE="/run/predict-db-password",
                )
                service["volumes"].append(
                    dict(
                        type="bind",
                        source=str(tmp_path / ("postgres-" + role)),
                        target="/run/predict-db-password",
                        read_only=True,
                    )
                )
            # In the unprivileged fake host, skip only the real UID/mode check.
            # PostgreSQL role names and mount isolation still use the validator.
            managed = payload / "managed-config.py"
            managed.write_text(
                managed.read_text()
                .replace("info = Path(source).lstat()", "info = Path(__file__).stat()")
                .replace(
                    "stat.S_IMODE(info.st_mode) == 0o400 and info.st_uid == 10001",
                    "True",
                )
            )
            (tmp_path / "postgres-roles.env").touch()
        if bad_managed:
            config["services"]["db"]["volumes"][0]["source"] = "new-database"
        (tmp_path / "candidate-compose.json").write_text(json.dumps(config))
        if managed_changed:
            (payload / "compose.yml").write_text("candidate-compose\n")
        if bad_proxy:
            (tmp_path / "fail-proxy").touch()
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
        protocol = "predict-images-fast-v1" if fast else "predict-images-v1"
        header = protocol + "\nfixture-user\nfixture-token\n"
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
bad_archive=$6
unhealthy_reused=$7
cleanup_failure=$8
CADDY_DIRECTORY="$PWD/caddy"
cleanup_images() { echo cleanup-images >> invocations; [[ $cleanup_failure == 0 ]]; }
docker() {
    printf '%s\n' "$*" >> invocations
    case "$1 $2" in
        'image inspect') awk -v ref="$5" '$1==ref {print $2, $3}' labels ;;
        'create --network') echo managed-fixture ;;
        'cp '*) cp "bundle/${2##*/}" "$3" ;;
        'rm managed-fixture') ;;
        'inspect --format')
            if [[ $4 == "fixture-$unhealthy_reused" ]]; then echo 'running unhealthy'; else echo 'running healthy'; fi ;;
        --config*) if [[ $3 == login ]]; then cat >/dev/null; fi ;;
        'compose --env-file')
            shift
            compose_path=
            while [[ $1 == --* || $1 == -f ]]; do
                if [[ $1 == -f ]]; then compose_path=$2; fi
                shift 2
            done
            case "$1" in
                config)
                    if [[ $compose_path == *'.release.'* ]]; then cat candidate-compose.json; else cat previous-compose.json; fi ;;
                ps) echo "fixture-${*: -1}" ;;
                exec) echo dump ;;
                run)
                    if [[ $* == *' python -c '* ]]; then
                        if [[ $PREDICT_WEB_IMAGE == "$old_web" ]]; then echo 0; else echo "$pending_fixture"; fi
                    fi
                    ;;
                up)
                    printf 'active %s %s %s\n' "$PREDICT_WEB_IMAGE" "$PREDICT_COLLECTOR_IMAGE" "$PREDICT_ARCHIVE_IMAGE" >> invocations
                    if [[ $bad_web == 1 && $PREDICT_WEB_IMAGE == "$candidate_web" && "${*: -1}" == web ]]; then return 1; fi
                    if [[ $bad_archive == 1 && $PREDICT_ARCHIVE_IMAGE == *'ffffffff' && "${*: -1}" == archive ]]; then return 1; fi
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
                str(int(bad_archive)),
                unhealthy_reused,
                str(int(cleanup_failure)),
            ],
            cwd=tmp_path,
            input=request,
            capture_output=True,
            text=True,
            timeout=10,
            env=dict(
                os.environ, PATH=str(executable) + os.pathsep + os.environ["PATH"]
            ),
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


def test_split_database_profile_does_not_activate_an_unconfigured_archive(release_host):
    previous, _, installed, image_env, run = release_host
    (installed.parent / "archive.env").unlink()
    result, commands = run(changed=set(), split_roles=True)
    assert result.returncode == 0, result.stderr
    probes = [
        line for line in commands if line.endswith("python -m app.storage verify-role")
    ]
    assert [line.split()[-5] for line in probes] == ["web", "collector"]
    assert all("--env-file postgres-roles.env" in line for line in probes)
    assert not any(" up " in line and line.endswith(" archive") for line in commands)
    assert (installed.parent / "applied-postgres-roles-env").is_file()
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
    assert "-Fc -Z1" in commands[backup]
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


def test_managed_bundle_refuses_a_different_owner_database_before_rollout(release_host):
    previous, _, installed, image_env, run = release_host
    result, commands = run(changed={"web"}, bad_managed=True)
    assert result.returncode != 0
    assert "Managed host configuration validation failed" in result.stderr
    assert not any(" up " in line or " stop " in line for line in commands)
    assert installed.read_text() == image_env(previous)
    assert (installed.parent / "compose.yml").read_text() == "original-compose\n"
    assert (
        installed.parent / "caddy/predict.Caddyfile"
    ).read_text() == "original-proxy\n"


def test_fast_release_refuses_pending_schema_before_touching_services(release_host):
    previous, _, installed, image_env, run = release_host
    result, commands = run(changed={"web"}, pending=1, fast=True)
    assert result.returncode != 0
    assert "Schema maintenance required; current services unchanged" in result.stderr
    assert not any(
        " up " in line or " stop " in line or " pg_dump " in line for line in commands
    )
    assert installed.read_text() == image_env(previous)
    assert (installed.parent / "compose.yml").read_text() == "original-compose\n"
    assert not any(line.startswith("systemctl") for line in commands)


def test_fast_release_of_unchanged_schema_uses_no_backup(release_host):
    _, _, _, _, run = release_host
    result, commands = run(changed={"web"}, fast=True)
    assert result.returncode == 0, result.stderr
    assert not any(
        " pg_dump " in line or "app.storage migrate" in line for line in commands
    )


def test_success_installs_managed_configuration_after_all_service_health(release_host):
    _, _, installed, _, run = release_host
    result, commands = run(changed={"web"})
    assert result.returncode == 0, result.stderr
    inspected = [
        i for i, line in enumerate(commands) if line.startswith("inspect --format")
    ]
    reload = next(
        i for i, line in enumerate(commands) if line == "systemctl reload caddy"
    )
    assert len(inspected) == 4 and max(inspected) < reload
    assert (
        installed.parent / "caddy/predict.Caddyfile"
    ).read_text() == "candidate-proxy\n"
    assert (installed.parent / "release.sh").read_text() == RELEASE.read_text()
    assert (installed.parent / "release.sh").stat().st_mode & 0o777 == 0o755
    assert commands[-1] == "cleanup-images"


def test_proxy_reload_failure_restores_files_and_rolls_back_changed_web(release_host):
    previous, _, installed, image_env, run = release_host
    result, commands = run(changed={"web"}, bad_proxy=True)
    assert result.returncode != 0
    assert "inspect configuration recovery" in result.stderr
    assert installed.read_text() == image_env(previous)
    assert (installed.parent / "compose.yml").read_text() == "original-compose\n"
    assert (installed.parent / "release.sh").read_text() == "original-release\n"
    assert (
        installed.parent / "caddy/predict.Caddyfile"
    ).read_text() == "original-proxy\n"
    assert sum(line == "systemctl reload caddy" for line in commands) == 2
    assert sum(" up " in line and line.endswith(" web") for line in commands) == 2
    assert "cleanup-images" not in commands


def test_archive_health_failure_is_a_failed_release_even_after_rollback(release_host):
    previous, _, installed, image_env, run = release_host
    result, commands = run(changed={"archive"}, bad_archive=True)
    assert result.returncode != 0
    assert "candidate archive failed its health check" in result.stderr
    assert "Restored the previous images" in result.stderr
    rollouts = [
        line for line in commands if " up " in line and line.endswith(" archive")
    ]
    assert len(rollouts) == 2
    assert all("--wait --wait-timeout 180" in line for line in rollouts)
    assert installed.read_text() == image_env(previous)
    assert not any(line.startswith("systemctl") for line in commands)


def test_reused_unhealthy_service_cannot_produce_success(release_host):
    previous, _, installed, image_env, run = release_host
    result, commands = run(changed=set(), unhealthy_reused="web")
    assert result.returncode != 0
    assert "Configured service is not healthy: web" in result.stderr
    assert installed.read_text() == image_env(previous)
    assert not any(line.startswith("systemctl") for line in commands)
    assert "cleanup-images" not in commands


def test_compose_change_quiesces_writers_before_database_reconfiguration(release_host):
    _, _, installed, _, run = release_host
    result, commands = run(changed=set(), managed_changed=True)
    assert result.returncode == 0, result.stderr
    stops = [i for i, line in enumerate(commands) if " stop " in line]
    db = next(
        i for i, line in enumerate(commands) if " up " in line and line.endswith(" db")
    )
    assert len(stops) == 2 and max(stops) < db
    assert (installed.parent / "compose.yml").read_text() == "candidate-compose\n"


def test_cleanup_failure_is_a_maintenance_warning_after_verified_install(release_host):
    _, _, installed, _, run = release_host
    result, commands = run(changed={"web"}, cleanup_failure=True)
    assert result.returncode == 0, result.stderr
    assert "Maintenance warning" in result.stderr
    assert (
        installed.parent / "caddy/predict.Caddyfile"
    ).read_text() == "candidate-proxy\n"
    assert commands[-1] == "cleanup-images"


def test_managed_caddy_staging_requires_one_known_import(tmp_path):
    stage = run_path(str(ROOT / "deploy/managed-config.py"))["stage_caddy"]
    main, site, destination = (
        tmp_path / name for name in ("Caddyfile", "site", "candidate")
    )
    site.touch()
    main.write_text(
        "{\n    email owner@example.invalid\n}\nimport /etc/caddy/predict.Caddyfile\n"
    )
    stage(main, site, destination)
    assert 'import "' + str(site) + '"' in destination.read_text()
    main.write_text("import /etc/caddy/unmanaged.Caddyfile\n")
    with pytest.raises(ValueError, match="exactly once"):
        stage(main, site, destination)


def test_release_reporting_distinguishes_stale_skip_from_missing_ci_gate():
    report = load("release_report")
    needs = dict(
        prepare=dict(
            result="success",
            outputs=dict(
                state="skipped", qualification="skipped", reason="Main advanced"
            ),
        ),
        **{
            "release-image": dict(result="skipped"),
            "deploy-hetzner": dict(result="skipped"),
        },
    )
    assert (
        report.evaluate(needs, branch=True, publish_only=False, deploy_enabled=True)[0]
        == "SKIPPED"
    )
    del needs["prepare"]
    assert (
        report.evaluate(needs, branch=True, publish_only=False, deploy_enabled=True)[0]
        == "FAIL"
    )


def test_successful_publication_reports_a_stale_pre_ssh_skip_without_claiming_deploy():
    report = load("release_report")
    needs = {
        "prepare": dict(
            result="success", outputs=dict(state="ready", qualification="success")
        ),
        "release-image": dict(
            result="success",
            outputs=dict(proxy="success", smoke="success", publish="success"),
        ),
        "deploy-hetzner": dict(
            result="success",
            outputs=dict(
                deploy="skipped", eligible="false", skip_reason="Main advanced"
            ),
        ),
    }
    overall, steps, reason, _, _ = report.evaluate(
        needs, branch=True, publish_only=False, deploy_enabled=True
    )
    assert (
        overall == "PASS" and steps["deploy"] == "SKIPPED" and reason == "Main advanced"
    )
