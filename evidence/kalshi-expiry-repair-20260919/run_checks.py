"""Affected offline tests; temporary output only, external sockets/credentials denied."""
import ipaddress
import socket
import sys
import unittest
from unittest.mock import patch
import keyring

original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex

def guarded(method):
    def call(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            try: allowed = ipaddress.ip_address(address[0]).is_loopback
            except ValueError: allowed = False
            if not allowed: raise AssertionError('offline checks prohibit external connections')
        return method(sock, address)
    return call

if __name__ == '__main__':
    names = sys.argv[1:] or [
        'tests.test_kalshi_expiry', 'tests.test_kalshi', 'tests.test_kalshi_live_replay',
        'tests.test_polymarket_us_stream', 'tests.test_continuous',
        'tests.test_d2_repair', 'tests.test_segmented_collector',
        'tests.test_supervised', 'tests.test_supervised_live',
        'tests.test_supervised_pacing', 'tests.test_finalization_resources',
        'tests.test_math_reconciliation', 'tests.test_fees', 'tests.test_depth',
        'tests.test_arbitrage']
    with patch.object(socket.socket, 'connect', guarded(original_connect)), \
         patch.object(socket.socket, 'connect_ex', guarded(original_connect_ex)), \
         patch.object(keyring, 'get_password', side_effect=AssertionError('credential access forbidden')), \
         patch.object(keyring, 'set_password', side_effect=AssertionError('credential access forbidden')):
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    sys.exit(not result.wasSuccessful())
