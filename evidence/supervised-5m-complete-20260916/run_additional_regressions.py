"""Bounded extra D2 regressions; source/evidence never rewritten."""
import ipaddress,json,resource,signal,socket,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tests.run_supervised_qualification import identity
from app.collection.continuous import rss
root=Path('evidence/supervised-5m-complete-20260916');mode=sys.argv[1]
out=root/mode;out.mkdir(exist_ok=False);(out/'tmp').mkdir();tempfile.tempdir=str(out/'tmp')
seconds=60 if mode=='retained' else 180;file_limit=(64 if mode=='retained' else 224)*1024**2
signal.alarm(seconds);resource.setrlimit(resource.RLIMIT_CPU,(seconds,seconds));resource.setrlimit(resource.RLIMIT_FSIZE,(file_limit,file_limit))
before=identity();original=socket.socket.connect;destinations=[]
def connect(s,a):
    assert isinstance(a,tuple) and ipaddress.ip_address(a[0]).is_loopback,'external blocked'
    if a[0] not in destinations:destinations.append(a[0])
    return original(s,a)
with patch('socket.socket.connect',connect),patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials blocked')):
    names={'d2':['tests.test_continuous'],'d2-repair':['tests.test_d2_repair'],'retained':['tests.test_supervised.Retained','tests.test_segmented.SavedCalculations']}[mode]
    suite=unittest.defaultTestLoader.loadTestsFromNames(names)
    r=unittest.TextTestRunner(verbosity=2).run(suite)
result=dict(passed=r.wasSuccessful() and rss()<=256*1024**2,tests=r.testsRun,failures=len(r.failures),errors=len(r.errors),rss_peak=rss(),candidate=before,source_unchanged=identity()==before,connected_addresses=destinations)
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
raise SystemExit(not result['passed'])
