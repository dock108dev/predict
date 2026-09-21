"""Independent deadline/parent-liveness watchdog; never needs the collector loop."""
from dataclasses import dataclass
import os
import resource
import signal
import time

from .delivery_budget import Clock


def limit_cpu(ceiling=600):
    soft,hard=resource.getrlimit(resource.RLIMIT_CPU)
    hard=ceiling if hard==resource.RLIM_INFINITY else min(ceiling,hard)
    soft=hard if soft==resource.RLIM_INFINITY else min(soft,hard)
    resource.setrlimit(resource.RLIMIT_CPU,(soft,hard))


def usage():
    value=resource.getrusage(resource.RUSAGE_SELF)
    return dict(cpu_seconds=value.ru_utime+value.ru_stime,
                rss=value.ru_maxrss*(1 if __import__('sys').platform=='darwin' else 1024))


@dataclass
class Deadlines:
    start: float
    closed: float | None = None
    stop_sent: bool = False

    def action(self, now):
        if now-self.start>=660:return 'outer_cutoff'
        if self.closed is not None:
            return 'finalization_cutoff' if now-self.closed>=300 else None
        if now-self.start>=300:return 'independent_cutoff'
        if not self.stop_sent and now-self.start>=240:return 'direct_stop'
        return None


def alive(pid):
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False


def terminate(pid):
    """Same TERM, one-second grace, KILL escalation as the retained supervisor."""
    try:os.kill(pid,signal.SIGTERM)
    except ProcessLookupError:return
    until=time.monotonic()+1
    while alive(pid) and time.monotonic()<until:time.sleep(.02)
    if alive(pid):
        try:os.kill(pid,signal.SIGKILL)
        except ProcessLookupError:pass


def watch(pid, parent_pid, pipe, start, *, clock=None):
    # A controlled clock is supplied by process tests only; the CLI never supplies one.
    limit_cpu()
    clock=clock or time.monotonic
    limits=Deadlines(start);last_heartbeat=time.monotonic();began=last_heartbeat;collecting=False
    try:
        pipe.send(dict(event='armed',clock=Clock().anchor()))
        while True:
            now=clock()
            while pipe.poll():
                message=pipe.recv()
                action=message['action']
                if action=='heartbeat':last_heartbeat=time.monotonic()
                elif action=='collecting':collecting=True
                elif action=='closed':
                    value=message['mono']
                    if limits.closed is None and limits.start<=value<=now:limits.closed=value
                elif action=='finished':return
                else:raise ValueError('watchdog_control')
            reason=None
            if os.getppid()!=parent_pid or time.monotonic()-last_heartbeat>5:reason='supervisor_lost'
            if usage()['rss']>=256*1024**2:reason=reason or 'watchdog_rss'
            if not collecting and now-start>=60:reason=reason or 'startup_cutoff'
            action=limits.action(now)
            if action=='direct_stop':
                pipe.send(dict(event='scheduled_stop_due',clock=Clock().anchor()))
                limits.stop_sent=True
            elif action:reason=reason or action
            if reason:
                terminate(pid)
                try:pipe.send(dict(event=reason,clock=Clock().anchor(),worker=pid))
                except (BrokenPipeError,EOFError,OSError):pass
                return
            if not alive(pid):return
            if time.monotonic()-began>=660:
                terminate(pid);return
            time.sleep(.02)
    except (EOFError,BrokenPipeError,OSError,ValueError):
        terminate(pid)
    finally:
        try:pipe.send(dict(event='watchdog_resources',**usage()))
        except (OSError,EOFError):pass
        pipe.close()
