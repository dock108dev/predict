"""Dedicated credential files for the Linux collector and Keychain on macOS."""

import os
from pathlib import Path
import stat


def read_file(name):
    directory = os.environ.get('PREDICT_SECRET_DIRECTORY')
    if directory is None:
        return None
    with os.fdopen(os.open(Path(directory) / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Invalid service credential permissions')
        value = stream.read(65537)
    if len(value) > 65536:
        raise ValueError('Service credential file too large')
    return value.decode('utf-8')


def keychain_or_file(name, service, account):
    value = read_file(name)
    if value is not None:
        return value
    from keyring.backends.macOS import Keyring
    return Keyring().get_password(service, account)
