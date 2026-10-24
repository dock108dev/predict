"""Export the alternate runtime lock for auditing only; never install or resolve."""

from pathlib import Path
import re
import tomllib


def requirements(lock):
    rows = []
    for package in lock["package"]:
        source = package["source"]
        if source == {"editable": "."} and package["name"] == "prediction-arb":
            continue
        if source != {"registry": "https://pypi.org/simple"}:
            raise ValueError("Unreviewed runtime lock source")
        name, version = package["name"], package["version"]
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", name) or not re.fullmatch(
            r"[a-zA-Z0-9_.+!-]+", version
        ):
            raise ValueError("Invalid locked package identity")
        artifacts = package.get("wheels", []) + (
            [package["sdist"]] if "sdist" in package else []
        )
        hashes = sorted({artifact["hash"] for artifact in artifacts})
        if not hashes or any(
            not re.fullmatch(r"sha256:[a-f0-9]{64}", h) for h in hashes
        ):
            raise ValueError("Missing or invalid runtime lock hashes")
        rows.append(f"{name}=={version} " + " ".join("--hash=" + h for h in hashes))
    if not rows:
        raise ValueError("Empty runtime lock")
    return "\n".join(sorted(rows)) + "\n"


if __name__ == "__main__":
    output = Path("test-results/quality/uv-requirements.txt")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(requirements(tomllib.loads(Path("uv.lock").read_text())))
