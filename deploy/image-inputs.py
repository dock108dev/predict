"""Print stable input fingerprints for the deployed image roles."""

from hashlib import sha256
import subprocess


ROLES = ("web", "collector", "archive")
BUILD_FILES = {
    b"Dockerfile",
    b".dockerignore",
    b"pyproject.toml",
    b"uv.lock",
    b"deploy/image-inputs.py",
    b"deploy/check-health.py",
}
WEB_FILES = {
    b"deploy/compose.yml",
    b"deploy/predict.Caddyfile",
    b"deploy/release.sh",
    b"deploy/managed-config.py",
    b"deploy/image-cleanup.py",
    b"app/dashboard/opportunity_board.py",
    b"app/dashboard/scanner_client_api.py",
    b"scripts/live_coverage_census.py",
    b"scripts/pipeline_storage_report.py",
    b"scripts/sgo_runtime_census.sql",
}
COLLECTOR_FILES = {
    b"app/collection/ordinary_worker.py",
    b"app/storage/ordinary_owner.py",
}


def fingerprints(tree):
    hashes = {role: sha256() for role in ROLES}
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        _, path = entry.split(b"\t", 1)
        if path in WEB_FILES or path.startswith(b"app/dashboard/opportunity_static/"):
            targets = ("web",)
        elif path in COLLECTOR_FILES:
            targets = ("collector",)
        elif path in BUILD_FILES or path.startswith(b"app/"):
            # Shared code, models and migrations ship together when their
            # runtime or publication compatibility can change.
            targets = ROLES
        else:
            continue
        for role in targets:
            hashes[role].update(entry + b"\0")
    return {role: digest.hexdigest() for role, digest in hashes.items()}


if __name__ == "__main__":
    tree = subprocess.check_output(["git", "ls-tree", "-rz", "--full-tree", "HEAD"])
    for role, fingerprint in fingerprints(tree).items():
        print(role, fingerprint)
