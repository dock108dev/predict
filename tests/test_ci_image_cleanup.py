"""Release cleanup preserves every running, stopped and rollback image."""

from pathlib import Path
from runpy import run_path
from types import SimpleNamespace
import json
import sys

import pytest


cleanup = run_path(str(Path(__file__).resolve().parents[1] / "deploy/image-cleanup.py"))
PREFIX = cleanup["REPOSITORY"]


def image(character, *, digest=None, source=True):
    return dict(
        Id="sha256:" + character * 64,
        RepoDigests=[PREFIX + "@sha256:" + (digest or character) * 64],
        Config=dict(
            Labels={"org.opencontainers.image.source": cleanup["SOURCE"]}
            if source
            else {}
        ),
    )


def test_cleanup_preserves_container_and_distinct_digest_rollback_identities():
    images = [image(c) for c in "abcd"]
    images[1] = image("b", digest="e")
    unrelated = dict(
        Id="sha256:" + "f" * 64, RepoTags=["other-project:latest"], Config={}
    )
    images.append(unrelated)
    result = cleanup["plan"](
        images,
        {images[0]["Id"], images[2]["Id"]},
        {PREFIX + "@sha256:" + "e" * 64},
    )
    assert result["candidates"] == [images[3]["Id"]]
    assert result["missing_references"] == []


def test_missing_rollback_reference_refuses_all_pruning():
    result = cleanup["plan"]([image("a")], set(), {PREFIX + "@sha256:" + "e" * 64})
    assert result["candidates"] == []
    assert result["missing_references"] == [PREFIX + "@sha256:" + "e" * 64]


def test_dangling_predict_image_is_owned_but_other_images_are_preserved():
    own = image("a")
    own["RepoDigests"] = []
    other = dict(Id="sha256:" + "b" * 64, RepoTags=["postgres:16"], Config={})
    assert cleanup["plan"]([own, other], set(), set())["candidates"] == [own["Id"]]


def test_current_and_previous_references_are_complete_and_legacy_is_superseded(
    tmp_path,
):
    refs = []
    for name, characters in (
        ("current-images.env", "abc"),
        ("previous-images.env", "def"),
    ):
        values = [PREFIX + "@sha256:" + c * 64 for c in characters]
        refs.extend(values)
        (tmp_path / name).write_text(
            "".join(
                f"PREDICT_{role}_IMAGE={value}\n"
                for role, value in zip(
                    ("WEB", "COLLECTOR", "ARCHIVE"), values, strict=True
                )
            )
        )
    (tmp_path / "current-image").write_text("obsolete historical format\n")
    assert cleanup["references"](tmp_path) == set(refs)


@pytest.mark.parametrize("body", ["", "PREDICT_WEB_IMAGE=bad\n", "SECRET=hidden\n"])
def test_unavailable_or_incomplete_authority_refuses_cleanup(tmp_path, body):
    (tmp_path / "current-images.env").write_text(body)
    with pytest.raises(ValueError):
        cleanup["references"](tmp_path)


@pytest.mark.parametrize("apply", [False, True])
def test_command_defaults_to_dry_run_and_never_forces_image_removal(
    monkeypatch, tmp_path, apply
):
    namespace = cleanup["main"].__globals__
    commands = []

    def inventory(*args):
        if args[:2] == ("image", "ls"):
            return "sha256:" + "a" * 64 + "\n"
        if args[:2] == ("image", "inspect"):
            return json.dumps([image("a")])
        assert args == ("ps", "--all", "--quiet")
        return ""

    def remove(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setitem(namespace, "references", lambda root: set())
    monkeypatch.setitem(namespace, "docker", inventory)
    monkeypatch.setattr(namespace["subprocess"], "run", remove)
    monkeypatch.setattr(
        sys,
        "argv",
        ["image-cleanup", "--root", str(tmp_path)] + (["--apply"] if apply else []),
    )
    assert cleanup["main"]() == 0
    assert commands == (
        [["docker", "image", "rm", "sha256:" + "a" * 64]] if apply else []
    )
