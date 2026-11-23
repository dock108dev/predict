"""Validate and atomically install the fixed Predict host configuration bundle."""

from pathlib import Path
import os
import re
import stat
import subprocess
import sys


FILES = ("compose.yml", "predict.Caddyfile", "release.sh", "managed-config.py", "image-cleanup.py")
MAX_FILE_BYTES = 256 * 1024


def bundle(directory):
    directory = Path(directory)
    for name in FILES:
        path = directory / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_FILE_BYTES:
            raise ValueError("Invalid managed configuration file: " + name)


def mount(service, target):
    matches = [item for item in service.get("volumes", []) if item.get("target") == target]
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous persistent mount: " + target)
    item = matches[0]
    return item.get("type"), item.get("source"), bool(item.get("read_only"))


def validate_compose(candidate, previous, root):
    """A release may change code/configuration, never select a new owner store."""
    root = str(Path(root).resolve())
    services = candidate.get("services", {})
    old = previous.get("services", {})
    if candidate.get("name") != "predict" or set(services) != {"db", "web", "collector", "archive"}:
        raise ValueError("The host must remain the dedicated Predict Compose project")
    if services["db"].get("network_mode") != "none":
        raise ValueError("PostgreSQL must remain network isolated")
    if services["db"].get("ports"):
        raise ValueError("PostgreSQL must not expose a host port")
    if services["archive"].get("network_mode") != "none":
        raise ValueError("The archive must remain network isolated")
    ports = services["web"].get("ports", [])
    if len(ports) != 1 or any(
        str(ports[0].get(key)) != expected
        for key, expected in (("host_ip", "127.0.0.1"), ("published", "8784"), ("target", "8784"))
    ):
        raise ValueError("Predict web must remain on the private loopback port")
    protected = {
        "db": ("/var/lib/postgresql/data", "/run/predict-postgres"),
        "web": ("/predict/.local", "/run/predict-postgres"),
        "collector": ("/predict/.local", "/run/predict-postgres", "/run/predict-secrets"),
        "archive": ("/run/predict-postgres", "/archive"),
    }
    for role, targets in protected.items():
        if role not in old:
            raise ValueError("The current protected service is missing: " + role)
        for target in targets:
            if mount(services[role], target) != mount(old[role], target):
                raise ValueError("A release cannot relocate protected state: " + role + target)
    volume = mount(services["db"], "/var/lib/postgresql/data")
    if volume != ("volume", "postgres", False) or (
        candidate.get("volumes", {}).get("postgres", {}).get("name") != "predict_postgres"
        or candidate["volumes"]["postgres"] != previous.get("volumes", {}).get("postgres")
    ):
        raise ValueError("The existing PostgreSQL volume must remain unchanged")
    for role in ("web", "collector"):
        if mount(services[role], "/predict/.local") != ("bind", root + "/state", False):
            raise ValueError("The existing private owner state must remain mounted")
        if str(services[role].get("environment", {}).get("PREDICT_DATABASE_CAP_GIB")) != "4":
            raise ValueError("The existing SQL storage guard must remain configured")
    if mount(services["collector"], "/run/predict-secrets") != ("bind", root + "/provider-secrets", True):
        raise ValueError("Provider credentials must remain read-only and collector-only")
    for role in ("web", "archive"):
        if any(item.get("target") == "/run/predict-secrets" for item in services[role].get("volumes", [])):
            raise ValueError("Provider credentials cannot be mounted into " + role)


def stage_caddy(main, site, destination):
    source = Path(main).read_text()
    pattern = r"(?m)^([ \t]*)import[ \t]+/etc/caddy/predict\.Caddyfile[ \t]*(?:#[^\n]*)?$"
    source, count = re.subn(pattern, lambda match: match[1] + 'import "' + str(Path(site).resolve()) + '"', source)
    if count != 1:
        raise ValueError("Caddy must import the managed Predict site exactly once")
    Path(destination).write_text(source)


def atomic_write(path, body, mode, owner=None):
    path = Path(path)
    temporary = path.with_name(path.name + ".release-" + str(os.getpid()))
    try:
        with temporary.open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        if owner is not None:
            os.chown(temporary, *owner)
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def install(directory, root, caddy_directory):
    """Restore all prior files if validation/reload refuses the candidate."""
    directory, root, caddy_directory = map(Path, (directory, root, caddy_directory))
    bundle(directory)
    targets = ((root / "compose.yml", "compose.yml", 0o644),
               (caddy_directory / "predict.Caddyfile", "predict.Caddyfile", 0o644),
               (root / "release.sh", "release.sh", 0o755))
    originals = []
    for path, _, _ in targets:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Managed host destinations must be existing regular files")
        originals.append((path, path.read_bytes(), stat.S_IMODE(info.st_mode), (info.st_uid, info.st_gid)))
    try:
        for (path, name, mode), (_, _, _, owner) in zip(targets[:2], originals[:2], strict=True):
            atomic_write(path, (directory / name).read_bytes(), mode, owner)
        subprocess.run(["caddy", "validate", "--config", str(caddy_directory / "Caddyfile"),
                        "--adapter", "caddyfile"], check=True)
        subprocess.run(["systemctl", "reload", "caddy"], check=True)
        path, name, mode = targets[2]
        atomic_write(path, (directory / name).read_bytes(), mode, originals[2][3])
    except BaseException:
        for path, body, mode, owner in originals:
            atomic_write(path, body, mode, owner)
        subprocess.run(["systemctl", "reload", "caddy"], check=False)
        raise


def main():
    import json

    action, *args = sys.argv[1:]
    if action == "validate-compose":
        candidate, previous, root = args
        validate_compose(json.loads(Path(candidate).read_text()), json.loads(Path(previous).read_text()), root)
    elif action == "stage-caddy":
        stage_caddy(*args)
    elif action == "install":
        install(*args)
    elif action == "bundle":
        bundle(*args)
    else:
        raise ValueError("Unknown managed configuration action")


if __name__ == "__main__":
    main()
