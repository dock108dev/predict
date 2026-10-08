"""Inherited CI boundary for Python tests and their child interpreters.

Enabled only by the offline runner. Historical acquisition inputs and private
owner state are never test inputs; network tests are restricted to loopback.
"""

import ipaddress
import os
import sys


def install(root):
    root = os.path.realpath(root)
    forbidden = tuple(
        os.path.join(root, name) for name in ("evidence", "examples", ".local")
    )
    permitted = [os.path.realpath(sys.prefix)]
    if os.environ.get("PREDICT_CI_REPORT_ROOT"):
        permitted.append(os.path.realpath(os.environ["PREDICT_CI_REPORT_ROOT"]))

    def check(event, args):
        if event in ("open", "os.listdir", "os.scandir") and args:
            name = args[0]
            if isinstance(name, (str, bytes, os.PathLike)):
                path = os.path.realpath(os.fsdecode(name))
                if any(
                    path == prefix or path.startswith(prefix + os.sep)
                    for prefix in forbidden[:2]
                ):
                    raise PermissionError(
                        "CI cannot access historical evidence/examples; use authored test fixtures"
                    )
                private = forbidden[2]
                if (path == private or path.startswith(private + os.sep)) and not any(
                    path == prefix or path.startswith(prefix + os.sep)
                    for prefix in permitted
                ):
                    raise PermissionError("CI cannot access private owner state")
                filename = os.path.basename(path)
                if (
                    os.path.dirname(path) == root
                    and (filename == ".env" or filename.startswith(".env."))
                    and filename not in (".env.example", ".env.sample", ".env.template")
                ):
                    raise PermissionError("CI cannot access private environment files")
        if event == "socket.connect" and len(args) > 1:
            address = args[1]
            if isinstance(address, tuple):
                try:
                    local = (
                        address[0] == "localhost"
                        or ipaddress.ip_address(address[0]).is_loopback
                    )
                except ValueError:
                    local = False
                if not local:
                    raise PermissionError(
                        "Offline CI permits only loopback network connections"
                    )

    sys.addaudithook(check)


if os.environ.get("PREDICT_CI_ISOLATED_ROOT"):
    install(os.environ["PREDICT_CI_ISOLATED_ROOT"])
