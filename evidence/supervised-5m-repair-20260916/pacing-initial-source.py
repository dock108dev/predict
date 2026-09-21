import ipaddress,json,signal,socket,unittest
from unittest.mock import patch
from pathlib import Path
from tests.test_supervised_pacing import TIMESTAMPS
signal.alarm(30)
original=socket.socket.connect
def connect(s,a):
    assert ipaddress.ip_address(a[0]).is_loopback
    return original(s,a)
with patch('socket.socket.connect',connect),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials blocked')):
    r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('tests.test_supervised_pacing'))
Path('evidence/supervised-5m-repair-20260916/pacing.json').write_text(json.dumps(dict(passed=r.wasSuccessful(),timestamps=TIMESTAMPS),indent=2)+'\n')
raise SystemExit(not r.wasSuccessful())
