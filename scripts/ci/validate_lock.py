"""Reject incomplete/out-of-date combined locks before editable backend import."""

import re
from pathlib import Path
import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def validate(root):
    project = tomllib.loads((root / "pyproject.toml").read_text())
    roots = [
        *project["project"]["dependencies"],
        *project["project"]["optional-dependencies"]["stream"],
        *project["build-system"]["requires"],
    ]
    roots += [
        line.strip()
        for line in (root / "requirements-ci.in").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    lock = (root / "requirements-ci.txt").read_text()
    versions = {
        canonicalize_name(name): version
        for name, version in re.findall(r"^([a-zA-Z0-9_.-]+)==([^\s\\;]+)", lock, re.M)
    }
    errors = []
    for text in roots:
        requirement = Requirement(text)
        version = versions.get(canonicalize_name(requirement.name))
        if version is None or version not in requirement.specifier:
            errors.append(requirement.name)
    if errors:
        raise ValueError(
            "Combined CI lock missing/conflicting roots: "
            + ", ".join(errors)
            + ". Regenerate from pyproject.toml AND requirements-ci.in, preserving hashes."
        )
    browser_versions = {
        canonicalize_name(name): version
        for name, version in re.findall(
            r"^([a-zA-Z0-9_.-]+)==([^\s\\;]+)",
            (root / "requirements-browser.txt").read_text(),
            re.M,
        )
    }
    for text in (root / "requirements-browser.in").read_text().splitlines():
        if not text.strip() or text.lstrip().startswith("#"):
            continue
        requirement = Requirement(text)
        version = browser_versions.get(canonicalize_name(requirement.name))
        if version is None or version not in requirement.specifier:
            raise ValueError(
                "Browser lock missing/conflicting root: " + requirement.name
            )
    print("PASS runtime, stream, backend, CI and browser root constraints")


if __name__ == "__main__":
    validate(Path(__file__).resolve().parents[2])
