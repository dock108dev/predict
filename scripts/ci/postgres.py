"""Historical storage qualification against an isolated, temporary PostgreSQL cluster."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    if os.geteuid() == 0:
        raise ValueError(
            "Run as an ordinary user; never use a root-owned or owner cluster"
        )
    binary = Path(subprocess.check_output(["pg_config", "--bindir"], text=True).strip())
    print(
        subprocess.check_output([str(binary / "postgres"), "--version"], text=True),
        flush=True,
    )
    output = Path("test-results/postgres").resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="predict-pg-") as directory:
        root = Path(directory)
        socket = root / ".local/pgsocket"
        socket.mkdir(parents=True)
        subprocess.run(
            [
                str(binary / "initdb"),
                "-D",
                str(root / "db"),
                "-U",
                "prediction_arb",
                "--auth=trust",
                "--no-locale",
                "--encoding=UTF8",
            ],
            check=True,
            timeout=60,
            stdout=subprocess.DEVNULL,
        )
        running = False
        try:
            subprocess.run(
                [
                    str(binary / "pg_ctl"),
                    "-D",
                    str(root / "db"),
                    "-l",
                    str(root / "postgres.log"),
                    "-o",
                    f'-k {socket} -p 55432 -h ""',
                    "-w",
                    "-t",
                    "30",
                    "start",
                ],
                check=True,
                timeout=40,
            )
            running = True
            subprocess.run(
                [
                    str(binary / "createdb"),
                    "-h",
                    str(socket),
                    "-p",
                    "55432",
                    "-U",
                    "prediction_arb",
                    "prediction_arb",
                ],
                check=True,
                timeout=20,
            )
            # The application connects only to its checkout-specific socket. Redirect
            # that root inside this test process, never alter application configuration.
            code = 'from pathlib import Path; import app.storage.store as s; s.ROOT=Path(__import__("sys").argv[1]); import pytest; raise SystemExit(pytest.main(["-q", "integration_tests", "--junitxml="+__import__("sys").argv[2]]))'
            subprocess.run(
                [sys.executable, "-c", code, str(root), str(output / "junit.xml")],
                check=True,
                timeout=300,
            )
        finally:
            if running or (root / "db/postmaster.pid").exists():
                subprocess.run(
                    [
                        str(binary / "pg_ctl"),
                        "-D",
                        str(root / "db"),
                        "-w",
                        "-t",
                        "30",
                        "-m",
                        "immediate",
                        "stop",
                    ],
                    check=True,
                    timeout=40,
                )


if __name__ == "__main__":
    main()
