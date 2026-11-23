"""Prune obsolete Predict images after a healthy release under deploy.lock.

The default is a read-only plan. Never force removal, delete another project's
images, or infer a missing rollback image's identity. Docker also refuses to
remove images referenced by a container created after the inventory.
"""

import argparse
import json
from pathlib import Path
import re
import subprocess


REPOSITORY = "ghcr.io/dock108dev/predict"
SOURCE = "https://github.com/dock108dev/predict"
IMAGE_ID = re.compile(r"sha256:[a-f0-9]{64}")
REFERENCE = re.compile(re.escape(REPOSITORY) + r"@sha256:[a-f0-9]{64}")
KEYS = {"PREDICT_WEB_IMAGE", "PREDICT_COLLECTOR_IMAGE", "PREDICT_ARCHIVE_IMAGE"}


def references(root):
    root = Path(root)
    current = root / "current-images.env"
    files = (
        [current, root / "previous-images.env"]
        if current.exists()
        else [root / "current-image"]
    )
    result = set()
    for path in files:
        if not path.exists():
            if path == current or path.name == "current-image":
                raise ValueError("Installed image references are unavailable")
            continue
        values = {}
        for line in path.read_text().splitlines():
            if path.name == "current-image":
                key, value = "legacy", line
            else:
                key, separator, value = line.partition("=")
                if not separator or key not in KEYS or key in values:
                    raise ValueError("Invalid protected image reference file")
            if not REFERENCE.fullmatch(value):
                raise ValueError("Invalid protected image digest")
            values[key] = value
        if set(values) != ({"legacy"} if path.name == "current-image" else KEYS):
            raise ValueError("Incomplete protected image references")
        result.update(values.values())
    return result


def plan(images, container_images, protected_references):
    protected = set(container_images)
    matched = set()
    owned = set()
    for image in images:
        identity = image["Id"]
        if not IMAGE_ID.fullmatch(identity):
            raise ValueError("Invalid Docker image identity")
        aliases = set(image.get("RepoDigests") or ()) | set(image.get("RepoTags") or ())
        aliases.add(identity)
        matching = protected_references & aliases
        if matching:
            protected.add(identity)
            matched.update(matching)
        labels = (image.get("Config") or {}).get("Labels") or {}
        if labels.get("org.opencontainers.image.source") == SOURCE or any(
            name.startswith((REPOSITORY + "@", REPOSITORY + ":")) for name in aliases
        ):
            owned.add(identity)
    missing = protected_references - matched
    return dict(
        protected_images=sorted(protected),
        missing_references=sorted(missing),
        candidates=sorted(owned - protected) if not missing else [],
    )


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Remove planned images; caller must hold deploy.lock",
    )
    args = parser.parse_args()
    refs = references(args.root)
    identities = sorted(
        set(docker("image", "ls", "--all", "--quiet", "--no-trunc").split())
    )
    images = json.loads(docker("image", "inspect", *identities)) if identities else []
    containers = docker("ps", "--all", "--quiet").split()
    active = (
        docker("inspect", "--format", "{{.Image}}", *containers).split()
        if containers
        else []
    )
    result = plan(images, active, refs)
    result.update(applied=args.apply, removed=[], failed=[])
    if args.apply:
        for identity in result["candidates"]:
            process = subprocess.run(
                ["docker", "image", "rm", identity],
                capture_output=True,
                text=True,
                timeout=30,
            )
            result["removed" if process.returncode == 0 else "failed"].append(identity)
    print(json.dumps(result, sort_keys=True))
    return int(bool(result["missing_references"] or result["failed"]))


if __name__ == "__main__":
    raise SystemExit(main())
