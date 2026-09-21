"""Fail-fast guarded focused verification, explicit temporary-output test selection."""
import argparse
import json
import resource
import signal
import time
import unittest

from tests.delivery_fixture import NetworkGuard

SUITES={
    'focused':['tests.test_delivery_capture'],
    'regressions':['tests.test_kalshi_expiry','tests.test_supervised.Bounds','tests.test_finalization_resources.Receipt'],
    'retained':['tests.test_supervised.Retained'],
    'math':['tests.test_math_reconciliation'],
}


def main():
    p=argparse.ArgumentParser();p.add_argument('suite',choices=SUITES);a=p.parse_args()
    seconds=60 if a.suite=='retained' else 180
    resource.setrlimit(resource.RLIMIT_CPU,(seconds,seconds));signal.alarm(seconds)
    started=time.monotonic()
    with NetworkGuard():
        result=unittest.TextTestRunner(verbosity=2,failfast=True).run(unittest.defaultTestLoader.loadTestsFromNames(SUITES[a.suite]))
    usage=resource.getrusage(resource.RUSAGE_SELF)
    peak=usage.ru_maxrss*(1 if __import__('sys').platform=='darwin' else 1024)
    print(json.dumps(dict(suite=a.suite,tests=result.testsRun,passed=result.wasSuccessful(),
        wall_seconds=time.monotonic()-started,cpu_seconds=usage.ru_utime+usage.ru_stime,peak_rss_bytes=peak,
        external_and_keyring_guard=True,memory_pass=peak<256*1024**2)))
    raise SystemExit(not result.wasSuccessful() or peak>=256*1024**2)


if __name__=='__main__':main()
