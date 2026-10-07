"""OS boot evidence and a suspend-inclusive clock, never wall time alone."""
from datetime import datetime, timezone
import platform
from pathlib import Path
import re
import subprocess
import time


def continuous():
    if platform.system() == 'Darwin':
        return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)
    if hasattr(time, 'CLOCK_BOOTTIME'):
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    return time.monotonic()


def boot_evidence():
    # Read twice to reject an inconsistent OS observation. Unsupported systems
    # have no restart authority; callers must stop rather than guess.
    system=platform.system()
    if system not in ('Darwin','Linux'):
        return None
    try:
        def read():
            if system=='Linux':
                identity=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
                metadata=Path('/proc/stat').read_text()
                if len(metadata)>1024*1024:return None
                found=re.search(r'^btime (\d+)$',metadata,re.MULTILINE)
                if not re.fullmatch(r'[A-Fa-f0-9-]{36}',identity) or not found:return None
                return dict(id=identity,started_at=datetime.fromtimestamp(int(found[1]),timezone.utc).isoformat(),
                            source='Linux boot_id + /proc/stat btime / CLOCK_BOOTTIME')
            result = subprocess.run(['/usr/sbin/sysctl', '-n', 'kern.bootsessionuuid', 'kern.boottime'],
                                    capture_output=True, text=True, timeout=2, check=True).stdout.splitlines()
            identity, start = result
            if not re.fullmatch(r'[A-Fa-f0-9-]{36}', identity):
                return None
            found = re.fullmatch(r'\{ sec = (\d+), usec = (\d+) \}.*', start)
            if not found:
                return None
            started = int(found[1]) + int(found[2])/1_000_000
            return dict(id=identity, started_at=datetime.fromtimestamp(started, timezone.utc).isoformat(),
                        source='Darwin kern.bootsessionuuid + kern.boottime / CLOCK_MONOTONIC_RAW')
        first = read()
        uptime = continuous()
        if first is None or first != read():
            return None
        return dict(first, uptime=uptime)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
