"""Supervise the web server and a lower-priority retained-results process."""

import signal
import subprocess
import sys
from threading import Event


def main():
    stop = Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    commands = (
        [sys.executable, "-m", "app.dashboard.opportunity_board", *sys.argv[1:]],
        [sys.executable, "-m", "app.research.paper_result_worker"],
    )
    children = []
    try:
        for command in commands:
            children.append(subprocess.Popen(command))
        while not stop.wait(0.5):
            for child in children:
                if child.poll() is not None:
                    return child.returncode or 1
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=4)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    sys.exit(main())
