"""Install reviewed release binaries after checking repository-pinned SHA256."""

import hashlib
from io import BytesIO
from pathlib import Path
import platform
import tarfile
import urllib.request

TOOLS = {
    "actionlint": (
        "rhysd/actionlint",
        "1.7.12",
        {
            "Linux": (
                "linux_amd64",
                "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8",
            ),
            "Darwin": (
                "darwin_arm64",
                "aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f",
            ),
        },
    ),
}


def main():
    target = Path(".local/ci-tools")
    target.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    expected_arch = "arm64" if system == "Darwin" else "x86_64"
    if platform.machine() != expected_arch:
        raise ValueError(
            "Unsupported tool platform; add reviewed release checksum first"
        )
    for name, (repo, version, releases) in TOOLS.items():
        suffix, digest = releases[system]
        url = f"https://github.com/{repo}/releases/download/v{version}/{name}_{version}_{suffix}.tar.gz"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"Invalid release digest: {name}")
        with tarfile.open(fileobj=BytesIO(data), mode="r:gz") as archive:
            member = archive.getmember(name)
            if not member.isfile():
                raise ValueError("Expected ordinary binary")
            (target / name).write_bytes(archive.extractfile(member).read())
        (target / name).chmod(0o755)


if __name__ == "__main__":
    main()
