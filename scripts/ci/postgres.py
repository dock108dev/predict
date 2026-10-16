"""Storage qualification against an isolated, temporary PostgreSQL 16 cluster."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def postgres_tools(pg_config, allow_other=False):
    """Resolve one installation and reject accidental compatibility-only runs."""
    binary = Path(
        subprocess.check_output([pg_config, "--bindir"], text=True, timeout=15).strip()
    )
    version = subprocess.check_output(
        [str(binary / "postgres"), "--version"], text=True, timeout=15
    ).strip()
    match = re.search(r"PostgreSQL\) (\d+)", version)
    if not match:
        raise ValueError(f"Cannot determine PostgreSQL major from {version!r}")
    major = int(match[1])
    if major != 16 and not allow_other:
        raise ValueError(
            f"PostgreSQL 16 is required for primary SQL qualification; selected {version} "
            f"via {pg_config}. Set PG_CONFIG to PostgreSQL 16's pg_config. "
            "Use --allow-other-postgres only for an intentional compatibility run. "
            "No cluster was initialized."
        )
    return binary, version, major


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-config", default=os.environ.get("PG_CONFIG", "pg_config"))
    parser.add_argument(
        "--report-dir",
        default=os.environ.get(
            "PREDICT_CI_POSTGRES_REPORT_DIR", "test-results/postgres"
        ),
    )
    parser.add_argument("--allow-other-postgres", action="store_true")
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        raise ValueError(
            "Run as an ordinary user; never use a root-owned or owner cluster"
        )
    try:
        binary, version, major = postgres_tools(
            args.pg_config, args.allow_other_postgres
        )
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    output = Path(args.report_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    identity = {
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "postgres": version,
        "postgres_major": major,
        "pg_config": args.pg_config,
        "postgres_bin": str(binary),
        "qualification": (
            "primary"
            if major == 16 and sys.version_info[:2] == (3, 14)
            else "compatibility"
        ),
        "report_dir": str(output),
    }
    (output / "toolchain.json").write_text(json.dumps(identity, indent=2) + "\n")
    print(json.dumps(identity, indent=2), flush=True)
    with tempfile.TemporaryDirectory(prefix="predict-pg-", dir="/tmp") as directory:
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
            code = 'from pathlib import Path; import app.storage.store as s; s.ROOT=Path(__import__("sys").argv[1]); import pytest; raise SystemExit(pytest.main(["-q", "integration_tests", "tests/test_d03_current_rows.py", "tests/test_current_row_financial_roundtrip.py", "tests/test_current_row_occurrence_roundtrip.py", "--junitxml="+__import__("sys").argv[2]]))'
            environment = os.environ.copy()
            # Tests also spawn pg_dump/pg_restore; they must match this server.
            environment["PATH"] = str(binary) + os.pathsep + environment.get("PATH", "")
            environment["PREDICT_CI_ISOLATED_ROOT"] = str(
                Path(__file__).resolve().parents[2]
            )
            environment["PREDICT_CI_REPORT_ROOT"] = str(output)
            environment["PYTHONPATH"] = (
                str(Path(__file__).resolve().parent)
                + os.pathsep
                + environment.get("PYTHONPATH", "")
            )
            subprocess.run(
                [sys.executable, "-c", code, str(root), str(output / "junit.xml")],
                env=environment,
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
