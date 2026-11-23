"""Cached image verification and personal deployment after focused checks pass."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time


REPOSITORY = "ghcr.io/dock108dev/predict"
ROLES = ("web", "collector", "archive")
DIGEST = re.compile(re.escape(REPOSITORY) + r"@sha256:[a-f0-9]{64}")


def remaining(started, *, now=None):
    return 120 - ((time.time() if now is None else now) - started)


def require_time(started, minimum, stage):
    if remaining(started) < minimum:
        raise RuntimeError(
            "Two-minute budget has insufficient time for "
            + stage
            + "; existing server was not changed"
        )


def image_digest(values):
    matches = {value for value in values if DIGEST.fullmatch(value)}
    if len(matches) != 1:
        raise ValueError("A role must have exactly one verified repository digest")
    return matches.pop()


class Release:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.started = int(os.environ.get("PREDICT_CICD_STARTED", time.time()))
        self.sha = os.environ["RELEASE_SHA"]
        self.publish_only = os.environ.get("RELEASE_PUBLISH_ONLY") == "true"
        self.phases = {}
        self.result = dict(
            schema=1,
            sha=self.sha,
            publish_only=self.publish_only,
            status="FAIL",
            deployed=False,
            phases=self.phases,
        )

    def run(self, command, *, name, env=None, stdin=None, check=True, cwd=None):
        log = self.directory / (name + ".log")
        with log.open("ab") as errors:
            process = subprocess.run(
                command,
                input=stdin,
                stdout=subprocess.PIPE,
                stderr=errors,
                env=env,
                cwd=cwd,
                timeout=max(1, remaining(self.started)),
                text=True,
            )
        if check and process.returncode:
            print(log.read_text(errors="replace")[-12000:])
            raise RuntimeError(name + " failed with exit " + str(process.returncode))
        return process

    def phase(self, name, fn):
        start = time.monotonic()
        print("Starting " + name, flush=True)
        try:
            return fn()
        finally:
            self.phases[name] = round(time.monotonic() - start, 3)
            print(name + " took " + str(self.phases[name]) + " seconds", flush=True)

    def current(self):
        tip = self.run(
            [
                "gh",
                "api",
                "repos/" + os.environ["GITHUB_REPOSITORY"] + "/git/ref/heads/main",
                "--jq",
                ".object.sha",
            ],
            name="main-tip",
        ).stdout.strip()
        return tip == self.sha

    def proxy(self):
        cached = Path(".local/ci-tools/caddy").resolve()
        binary = str(cached) if cached.is_file() else shutil.which("caddy")
        if not binary:
            package = self.directory / "caddy"
            package.mkdir()
            if self.run(
                ["apt-get", "download", "caddy"],
                name="caddy-download",
                cwd=package,
                check=False,
            ).returncode:
                self.run(["sudo", "apt-get", "update", "-qq"], name="caddy-index")
                self.run(
                    ["apt-get", "download", "caddy"], name="caddy-download", cwd=package
                )
            deb = next(package.glob("*.deb"))
            self.run(["dpkg-deb", "-x", str(deb), str(package)], name="caddy-extract")
            binary = str(package / "usr/bin/caddy")
            cached.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(binary, cached)
            binary = str(cached)
        self.run(
            ["bash", "deploy/smoke-proxy.sh"],
            name="private-proxy",
            env=dict(os.environ, CADDY_BIN=binary),
        )

    def build(self, role, fingerprint):
        tag = REPOSITORY + ":" + role + "-inputs-" + fingerprint
        cache = REPOSITORY + ":" + role + "-build-cache"
        hit = (
            self.run(
                ["docker", "pull", tag], name=role + "-lookup", check=False
            ).returncode
            == 0
        )
        if not hit:
            self.run(["docker", "pull", cache], name=role + "-cache", check=False)
            self.run(
                [
                    "docker",
                    "build",
                    "--target",
                    role,
                    "--build-arg",
                    "BUILDKIT_INLINE_CACHE=1",
                    "--cache-from",
                    cache,
                    "--label",
                    "org.opencontainers.image.source=https://github.com/dock108dev/predict",
                    "--label",
                    "org.opencontainers.image.revision=" + self.sha,
                    "--label",
                    "dev.dock108.predict.role=" + role,
                    "--label",
                    "dev.dock108.predict.inputs=" + fingerprint,
                    "-t",
                    tag,
                    "-t",
                    cache,
                    ".",
                ],
                name=role + "-build",
            )
        label = self.run(
            [
                "docker",
                "image",
                "inspect",
                "--format",
                '{{index .Config.Labels "dev.dock108.predict.role"}} {{index .Config.Labels "dev.dock108.predict.inputs"}}',
                tag,
            ],
            name=role + "-label",
        ).stdout.strip()
        if label != role + " " + fingerprint:
            raise ValueError("Cached image role/input identity mismatch")
        return dict(role=role, tag=tag, cache=cache, inputs=fingerprint, cache_hit=hit)

    def publish(self, image):
        if not image["cache_hit"]:
            self.run(["docker", "push", image["tag"]], name=image["role"] + "-publish")
            self.run(
                ["docker", "push", image["cache"]],
                name=image["role"] + "-cache-publish",
            )
        value = self.run(
            [
                "docker",
                "image",
                "inspect",
                "--format",
                "{{json .RepoDigests}}",
                image["tag"],
            ],
            name=image["role"] + "-digest",
        ).stdout
        return dict(image, digest=image_digest(json.loads(value)))

    def execute(self):
        if not re.fullmatch(r"[a-f0-9]{40}", self.sha):
            raise ValueError("Exact release SHA required")
        actual = self.run(["git", "rev-parse", "HEAD"], name="checkout").stdout.strip()
        if actual != self.sha:
            raise ValueError("Checkout does not match the checked release SHA")
        if not self.publish_only and not self.current():
            self.result.update(status="SKIPPED", reason="Main advanced before build")
            return
        require_time(self.started, 45, "image verification")
        self.run(
            [
                "docker",
                "login",
                "ghcr.io",
                "-u",
                os.environ["GITHUB_ACTOR"],
                "--password-stdin",
            ],
            name="registry-login",
            stdin=os.environ["GH_TOKEN"],
        )
        output = self.run(
            ["python", "deploy/image-inputs.py"], name="image-inputs"
        ).stdout
        inputs = dict(line.split() for line in output.splitlines())
        with ThreadPoolExecutor(max_workers=4) as pool:
            proxy = pool.submit(self.phase, "proxy", self.proxy)
            images = self.phase(
                "build",
                lambda: list(
                    pool.map(lambda role: self.build(role, inputs[role]), ROLES)
                ),
            )
            environment = dict(
                os.environ,
                **{"PREDICT_" + i["role"].upper() + "_IMAGE": i["tag"] for i in images},
            )
            # Candidate publication can overlap the disposable smoke: neither
            # authorizes server changes. Both must succeed before SSH handoff.
            publication = pool.submit(
                self.phase, "publish", lambda: list(pool.map(self.publish, images))
            )
            self.phase(
                "compose_smoke",
                lambda: self.run(
                    ["bash", "deploy/smoke.sh"], name="compose-smoke", env=environment
                ),
            )
            images = publication.result()
            proxy.result()
        self.result["images"] = images
        if self.publish_only:
            self.result.update(status="PASS", reason="Published only; no server access")
            return
        if os.environ.get("HETZNER_DEPLOY_ENABLED") != "true":
            self.result.update(status="SKIPPED", reason="Server deployment is disabled")
            return
        if not self.current():
            self.result.update(
                status="SKIPPED", reason="Main advanced before server handoff"
            )
            return
        require_time(self.started, 25, "server handoff")
        host = os.environ["SSH_HOST"]
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]+", host):
            raise ValueError("Invalid deployment host")
        key, known = self.directory / "key", self.directory / "known_hosts"
        for path, value in (
            (key, os.environ["SSH_KEY"]),
            (known, os.environ["SSH_KNOWN_HOSTS"]),
        ):
            if not value.strip():
                raise ValueError("Existing restricted SSH configuration is required")
            path.write_text(value + "\n")
            path.chmod(0o600)
        manifest = "".join(i["digest"] + " " + i["inputs"] + "\n" for i in images)
        request = (
            "predict-images-fast-v1\n"
            + os.environ["GITHUB_ACTOR"]
            + "\n"
            + os.environ["GH_TOKEN"]
            + "\n"
            + manifest
        )
        self.phase(
            "deploy",
            lambda: self.run(
                [
                    "ssh",
                    "-i",
                    str(key),
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "IdentitiesOnly=yes",
                    "-o",
                    "StrictHostKeyChecking=yes",
                    "-o",
                    "UserKnownHostsFile=" + str(known),
                    "-o",
                    "ConnectTimeout=10",
                    "predict-deploy@" + host,
                ],
                name="server-release",
                stdin=request,
            ),
        )
        self.result.update(status="PASS", deployed=True)

    def report(self):
        self.result.update(
            elapsed_seconds=round(time.time() - self.started, 3),
            budget_seconds=120,
            observed_at=datetime.now(timezone.utc).isoformat(),
        )
        output = Path("test-results/release")
        output.mkdir(parents=True, exist_ok=True)
        (output / "metrics.json").write_text(json.dumps(self.result, indent=2) + "\n")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as summary:
                summary.write("\n## Personal release " + self.result["status"] + "\n\n")
                summary.write(
                    "Revision `"
                    + self.sha
                    + "`; runner elapsed "
                    + str(self.result["elapsed_seconds"])
                    + " seconds. Queue time is separate.\n\n"
                )
                summary.write("| Stage | Seconds |\n| --- | ---: |\n")
                for name, value in self.phases.items():
                    summary.write("| " + name + " | " + str(value) + " |\n")
                if self.result.get("reason"):
                    summary.write("\n" + self.result["reason"] + "\n")
        print(json.dumps(self.result, sort_keys=True), flush=True)


def main():
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="predict-release-") as directory:
        release = Release(directory)
        try:
            release.execute()
        except Exception as error:
            release.result["reason"] = type(error).__name__ + ": " + str(error)
            raise
        finally:
            release.report()


if __name__ == "__main__":
    main()
