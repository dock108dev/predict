"""Own one approved metadata-only execution: 30 seconds plus two for forced cleanup."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
import control
import launch

PACKAGE = Path(__file__).resolve().parent


def main():
    launch.prepared(True)
    identity = json.loads((PACKAGE/'identity.json').read_text())
    began = time.monotonic()
    operations_deadline = began+30
    overall_deadline = began+32
    server = None
    client = None
    result = dict(overall_wall_seconds_cap=32, operation_wall_seconds_cap=30)
    def force_deadline():
        # Own process groups only. Stop both children even if a control read,
        # finalizer or normal cleanup has hung; the allowance remains consumed.
        for child in (client,server):
            if child is not None and child.poll() is None:
                try:
                    os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            control.save('supervisor-deadline.json',dict(
                reason='metadata_diagnostic_supervisor_wall_cap',
                overall_wall_seconds_cap=32,watchdog_seconds=31.5,
                provider_retry_permitted=False,cleanup_verified=False,
                elapsed_seconds=round(time.monotonic()-began,6)))
        finally:
            os._exit(124)
    # Reserve half a second for the small durable failure record before the
    # 32-second hard ceiling. Normal completion cancels this watchdog last.
    watchdog = threading.Timer(31.5,force_deadline)
    watchdog.daemon = True
    # Failure persistence itself must not defer exit beyond the hard ceiling.
    hard_exit = threading.Timer(32,lambda:os._exit(124))
    hard_exit.daemon = True
    hard_exit.start()
    watchdog.start()
    logs = bytearray()
    log_bytes = 0
    log_reader = None
    def drain_logs(stream):
        nonlocal log_bytes
        while True:
            raw = stream.read(4096)
            if not raw:
                return
            log_bytes += len(raw)
            logs.extend(raw[:max(0,65536-len(logs))])
    try:
        # Drain process diagnostics in 4-KiB reads while retaining at most 64 KiB.
        server = subprocess.Popen([sys.executable,str(PACKAGE/'launch.py'),'--serve'],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=launch.ROOT,
                                  start_new_session=True)
        log_reader = threading.Thread(target=drain_logs,args=(server.stdout,),daemon=True)
        log_reader.start()
        readiness = min(operations_deadline-7,time.monotonic()+3)
        while time.monotonic()<readiness:
            if server.poll() is not None:
                raise RuntimeError('Owned server exited before readiness')
            binding = control.request('/probe-binding')
            if binding.get('status') == 200 and binding.get('body') == identity:
                result['readiness_identity_verified'] = True
                break
            time.sleep(.1)
        else:
            raise RuntimeError('Owned server readiness deadline or identity mismatch')
        client = subprocess.Popen([sys.executable,str(PACKAGE/'control.py'),'--run'],
                                  cwd=launch.ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  start_new_session=True)
        try:
            result['control_exit'] = client.wait(timeout=max(.1,min(21,operations_deadline-time.monotonic()-5)))
        except subprocess.TimeoutExpired:
            client.terminate()
            try:
                client.wait(timeout=1)
            except subprocess.TimeoutExpired:
                client.kill()
                client.wait(timeout=1)
            result['control_deadline_exceeded'] = True
        cleanup = min(operations_deadline,time.monotonic()+5)
        while time.monotonic()<cleanup:
            status = control.request('/api/status')
            value = status.get('body',{})
            if status.get('status') == 200 and not value.get('active') and value.get('cleanup_complete'):
                result['settled_status'] = value
                break
            time.sleep(.1)
        else:
            result['cleanup_status_unsettled'] = True
    except BaseException as exc:
        result['failure_class'] = type(exc).__name__
        result['failure_reason'] = str(exc)
        raise
    finally:
        if client is not None and client.poll() is None:
            client.kill()
            client.wait(timeout=1)
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=max(.1,min(2,overall_deadline-time.monotonic())))
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=1)
            result['owned_server_closed'] = server.poll() is not None
        if log_reader is not None:
            log_reader.join(timeout=max(0,min(.1,overall_deadline-time.monotonic())))
        control.save('owned-server-log.json',dict(text=logs.decode('utf-8',errors='replace'),
                                                total_output_bytes=log_bytes,
                                                retained_output_bytes=len(logs),
                                                discarded_output_bytes=max(0,log_bytes-len(logs))))
        result['elapsed_seconds'] = round(time.monotonic()-began,6)
        result['overall_deadline_satisfied'] = result['elapsed_seconds'] <= 32
        control.save('supervisor-result.json', result)
        watchdog.cancel()
        hard_exit.cancel()
    print(json.dumps(dict(control_exit=result.get('control_exit'),
                          owned_server_closed=result.get('owned_server_closed'),
                          elapsed_seconds=result.get('elapsed_seconds'))))


if __name__ == '__main__':
    main()
