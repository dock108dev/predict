"""Fail-fast, guarded, 180-second launcher checks; no major lifecycle command."""
import json
import resource
import signal
import time
import unittest

from tests.delivery_fixture import NetworkGuard


def main():
    resource.setrlimit(resource.RLIMIT_CPU,(180,180));signal.alarm(180)
    began=time.monotonic()
    with NetworkGuard():
        result=unittest.TextTestRunner(verbosity=2,failfast=True).run(
            unittest.defaultTestLoader.loadTestsFromName('tests.test_delivery_launcher'))
    r=resource.getrusage(resource.RUSAGE_SELF)
    peak=r.ru_maxrss*(1 if __import__('sys').platform=='darwin' else 1024)
    print(json.dumps(dict(tests=result.testsRun,passed=result.wasSuccessful(),wall_seconds=time.monotonic()-began,
        cpu_seconds=r.ru_utime+r.ru_stime,peak_rss_bytes=peak,guard=True)))
    raise SystemExit(not result.wasSuccessful() or peak>=256*1024**2)


if __name__=='__main__':main()
