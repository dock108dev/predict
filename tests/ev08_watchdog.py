"""External resource gate for owned fixture subprocesses, independent of their loop.

Only the process group created here can be terminated. Samples contain process
IDs and RSS, never command lines, environments or owner application state.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

CAP = 768 * 1024 * 1024


def processes(group):
    output = subprocess.check_output(['ps', '-axo', 'pid=,pgid=,rss='], text=True)
    return {int(pid): int(rss) * 1024 for pid, pgid, rss in
            (line.split() for line in output.splitlines()) if int(pgid) == group}


def run(command, destination, *, cap=CAP, interval=.05):
    if not os.environ.get('PREDICT_CI_ISOLATED_ROOT'):
        raise ValueError('Inherited offline boundary required')
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = dict(cap_bytes=cap, sample_interval_seconds=interval, samples=0,
                  peaks={}, simultaneous_process_tree_peak_bytes=0,
                  violation=None, evidence_class='authored isolated process group')
    # Refuse before starting any operation if process sampling is unavailable.
    processes(-1)
    with (out/'child.log').open('w') as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        report['owned_group'] = child.pid
        try:
            with (out/'rss.jsonl').open('w') as stream:
                while child.poll() is None:
                    rss = processes(child.pid)
                    sample = dict(seconds=time.monotonic()-started, rss_bytes=rss)
                    stream.write(json.dumps(sample)+'\n'); stream.flush()
                    report['samples'] += 1
                    report['simultaneous_process_tree_peak_bytes'] = max(
                        report['simultaneous_process_tree_peak_bytes'], sum(rss.values()))
                    for pid, value in rss.items():
                        report['peaks'][str(pid)] = max(report['peaks'].get(str(pid), 0), value)
                    exceeded = {pid: value for pid, value in rss.items() if value >= cap}
                    if exceeded:
                        report['violation'] = dict(sample, exceeded=exceeded)
                        # This runs outside the blocked calculation process.
                        os.killpg(child.pid, signal.SIGTERM)
                        break
                    time.sleep(interval)
        finally:
            if child.poll() is None:
                try: child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=2)
            remaining = processes(child.pid)
            if remaining:
                os.killpg(child.pid, signal.SIGKILL)
                deadline = time.monotonic()+2
                while remaining and time.monotonic() < deadline:
                    time.sleep(.05); remaining = processes(child.pid)
            report.update(returncode=child.returncode, seconds=time.monotonic()-started,
                          remaining_owned_processes=remaining,
                          cleanup_complete=not remaining,
                          graceful_cleanup=report['violation'] is None and child.returncode == 0 and not remaining)
            (out/'monitor.json').write_text(json.dumps(report, indent=2)+'\n')
    return 1 if report['violation'] or child.returncode or remaining else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command: parser.error('A fixture subprocess command is required')
    raise SystemExit(run(command, args.out))
