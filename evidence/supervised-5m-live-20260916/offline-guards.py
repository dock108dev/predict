import sys,socket,ipaddress,signal,resource,json,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path.cwd()))
from app.collection.supervised_live import identity
from app.collection.continuous import rss
signal.alarm(180)
resource.setrlimit(resource.RLIMIT_CPU,(180,180))
original=socket.socket.connect
def connect(sock,address):
    if not isinstance(address,tuple) or not ipaddress.ip_address(address[0]).is_loopback:raise AssertionError('external network blocked')
    return original(sock,address)
before=identity()
with patch('socket.socket.connect',connect),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials blocked')):
    r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(sys.argv[2:]))
Path(sys.argv[1]).write_text(json.dumps(dict(passed=r.wasSuccessful(),tests=r.testsRun,failures=len(r.failures),errors=len(r.errors),rss=rss(),candidate=before,source_unchanged=identity()==before),indent=2)+'\n')
sys.exit(0 if r.wasSuccessful() else 1)
