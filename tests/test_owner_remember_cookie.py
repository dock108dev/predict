"""Owner cookie provisioning preserves credentials and remembered sessions."""

from http.cookies import SimpleCookie
import os
from pathlib import Path
import re
from runpy import run_path
import stat

import pytest


module = run_path(str(Path(__file__).resolve().parents[1] / "deploy/remember-owner.py"))
configure = module["configure"]


@pytest.fixture
def directory(tmp_path):
    auth = tmp_path / "predict-auth"
    auth.write_text("fixture owner-password-hash\n")
    auth.chmod(0o640)
    return tmp_path


def cookie(directory):
    body = (directory / module["SESSION_FILE"]).read_text()
    value = re.search(r'header \+Set-Cookie "([^"]+)"', body).group(1)
    return SimpleCookie(value)[module["COOKIE_NAME"]]


def test_creation_uses_persistent_host_cookie_and_existing_login(directory):
    assert configure(directory)
    path = directory / module["SESSION_FILE"]
    info = path.stat()
    assert stat.S_IMODE(info.st_mode) == 0o640
    if os.geteuid() == 0:
        auth = (directory / "predict-auth").stat()
        assert (info.st_uid, info.st_gid) == (auth.st_uid, auth.st_gid)
    value = cookie(directory)
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", value.value)
    assert value["path"] == "/" and value["domain"] == ""
    assert value["max-age"] == "31536000"
    assert value["secure"] and value["httponly"]
    assert value["samesite"] == "Lax"
    body = path.read_text()
    assert f'!= "{value.value}"' in body
    assert "basicauth {" in body
    assert 'import "' + str(directory / "predict-auth") + '"' in body
    assert "owner-password-hash" not in body


def test_repeated_provisioning_does_not_replace_the_owner_session(
    directory, monkeypatch
):
    configure(directory)
    path = directory / module["SESSION_FILE"]
    before = path.read_bytes(), path.stat().st_ino

    def unexpected(*args, **kwargs):
        raise AssertionError("Existing session must not generate or replace a token")

    monkeypatch.setattr(configure.__globals__["secrets"], "token_urlsafe", unexpected)
    assert not configure(directory)
    assert (path.read_bytes(), path.stat().st_ino) == before


def test_explicit_rotation_replaces_cookie_without_changing_password(directory):
    auth = directory / "predict-auth"
    original = auth.read_bytes()
    configure(directory)
    before = cookie(directory).value
    assert configure(directory, rotate=True)
    assert cookie(directory).value != before
    assert auth.read_bytes() == original
    assert stat.S_IMODE((directory / module["SESSION_FILE"]).stat().st_mode) == 0o640


@pytest.mark.parametrize("name", ["predict-auth", module["SESSION_FILE"]])
def test_symbolic_link_cannot_select_an_authentication_file(directory, name):
    other = directory / "untouched"
    other.write_text("unchanged")
    other.chmod(0o640)
    path = directory / name
    path.unlink(missing_ok=True)
    path.symlink_to(other)
    with pytest.raises(ValueError, match="regular and private"):
        configure(directory)
    assert other.read_text() == "unchanged"


@pytest.mark.parametrize("name", ["predict-auth", module["SESSION_FILE"]])
def test_public_or_writable_authentication_file_is_refused(directory, name):
    if name == module["SESSION_FILE"]:
        configure(directory)
    path = directory / name
    path.chmod(0o666)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="regular and private"):
        configure(directory, rotate=True)
    assert path.read_bytes() == before


def test_missing_password_file_does_not_create_a_session(tmp_path):
    with pytest.raises(FileNotFoundError):
        configure(tmp_path)
    assert not (tmp_path / module["SESSION_FILE"]).exists()


def test_command_does_not_print_the_credential(directory, capsys):
    module["main"](["--directory", str(directory)])
    value = cookie(directory).value
    output = capsys.readouterr()
    assert value not in output.out + output.err
    assert "configured" in output.out
    assert list(directory.glob(".predict-owner-session-*")) == []
