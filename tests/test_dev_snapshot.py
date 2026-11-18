"""Snapshot transfer failures cannot select partial input or target another cluster."""

import importlib.machinery
import importlib.util
from pathlib import Path
import subprocess
from unittest.mock import patch
import pytest


def snapshot_tool():
    path = Path(__file__).resolve().parents[1] / "scripts/dev-snapshot"
    loader = importlib.machinery.SourceFileLoader("predict_dev_snapshot", str(path))
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_loader(loader.name, loader)
    )
    loader.exec_module(module)
    return module


def test_failed_pull_keeps_partial_private_and_never_restores(tmp_path):
    module = snapshot_tool()

    def interrupted(*args, stdout, **kwargs):
        stdout.write(b"partial dump")
        raise subprocess.CalledProcessError(255, args)

    with (
        patch.object(module, "BASE", tmp_path),
        patch.object(module, "run", side_effect=interrupted),
        patch.object(module, "restore") as restore,
    ):
        with pytest.raises(subprocess.CalledProcessError):
            module.pull()
    assert not list(tmp_path.glob("*.dump"))
    partial = next(tmp_path.glob("*.partial"))
    assert partial.read_bytes() == b"partial dump"
    assert partial.stat().st_mode & 0o777 == 0o600
    restore.assert_not_called()


def test_successful_pull_restores_only_the_completed_dump(tmp_path):
    module = snapshot_tool()

    def completed(*args, stdout, **kwargs):
        stdout.write(b"completed dump")

    with (
        patch.object(module, "BASE", tmp_path),
        patch.object(module, "run", side_effect=completed),
        patch.object(module, "restore") as restore,
    ):
        module.pull()
    dump = next(tmp_path.glob("*.dump"))
    assert dump.read_bytes() == b"completed dump"
    assert not list(tmp_path.glob("*.partial"))
    restore.assert_called_once_with(dump)


def test_revaluation_rejects_a_non_snapshot_socket_before_connecting():
    module = snapshot_tool()
    with patch("app.storage.store.connect") as connect:
        with pytest.raises(SystemExit, match="Snapshot socket required"):
            module.revalue_snapshot(
                {"socket": "/tmp/owner-database", "cluster": "/tmp/owner"}
            )
    connect.assert_not_called()
