"""Provision one persistent owner cookie without changing the existing login."""

import argparse
import json
import os
from pathlib import Path
import secrets
import stat
import tempfile


SESSION_FILE = "predict-owner-session.Caddyfile"
COOKIE_NAME = "__Host-predict_owner"
MAX_AGE = 31536000


def private_file(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o137:
        raise ValueError("Owner authentication files must be regular and private")
    return info


def configure(directory, *, rotate=False):
    directory = Path(directory).absolute()
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & stat.S_IWOTH:
        raise ValueError("Owner authentication directory must be a safe directory")
    auth = directory / "predict-auth"
    auth_info = private_file(auth)
    target = directory / SESSION_FILE
    try:
        existing = private_file(target)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if existing.st_uid != auth_info.st_uid:
            raise ValueError("Owner authentication file ownership does not match")
        if not rotate:
            return False

    token = secrets.token_urlsafe(32)
    cookie = (
        f"{COOKIE_NAME}={token}; Path=/; Max-Age={MAX_AGE}; "
        "Secure; HttpOnly; SameSite=Lax"
    )
    body = (
        "(predict_owner_session) {\n"
        f'\t@needsOwnerAuth expression `{{http.request.cookie.{COOKIE_NAME}}} != "{token}"`\n'
        "\troute @needsOwnerAuth {\n"
        "\t\tbasicauth {\n"
        f"\t\t\timport {json.dumps(str(auth))}\n"
        "\t\t}\n"
        f'\t\theader +Set-Cookie "{cookie}"\n'
        "\t}\n"
        "}\n"
    )
    descriptor, temporary = tempfile.mkstemp(
        prefix=".predict-owner-session-", dir=directory
    )
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), auth_info.st_uid, auth_info.st_gid)
            os.fchmod(stream.fileno(), 0o640)
        if rotate:
            os.replace(temporary, target)
        else:
            try:
                os.link(temporary, target)
            except FileExistsError:
                current = private_file(target)
                if current.st_uid != auth_info.st_uid:
                    raise ValueError(
                        "Owner authentication file ownership does not match"
                    )
                return False
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default="/etc/caddy")
    parser.add_argument("--rotate", action="store_true")
    options = parser.parse_args(argv)
    changed = configure(options.directory, rotate=options.rotate)
    print(
        "Remembered owner login configured."
        if changed
        else "Existing remembered owner login preserved."
    )


if __name__ == "__main__":
    main()
