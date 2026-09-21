import asyncio
from copy import deepcopy
import hashlib,json,os,signal,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from app.collection.recovery import inspect,index,reopen_index
from app.collection.transport_session import ObservationJournal,reopen
from app.dashboard.e6_live import validate_saved,verify_all
from app.reference.records import packed

ROOT=Path(__file__).resolve().parents[1]

def crash(directory,phase):
    directory.mkdir(parents=True)
    log=(directory/'worker.log').open('wb')
    p=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-m','tests.e6_recovery_crash_worker',str(directory),phase],cwd=ROOT,stdout=log,stderr=log,env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1'})
    try:
        for _ in range(2000):
            if (directory/'ready.json').exists():break
            if p.poll() is not None:raise RuntimeError((directory/'worker.log').read_text())
            time.sleep(.01)
        else:raise RuntimeError('local fixture readiness deadline')
        ready=json.loads((directory/'ready.json').read_text())
        # Reader must refuse the actual live writer, including a quiet one.
        try:inspect(ready['journal'])
        except BlockingIOError:pass
        else:raise AssertionError('active owner accepted')
        p.kill();p.wait(timeout=5)
        assert p.returncode==-signal.SIGKILL
        (directory/'crash.json').write_text(json.dumps(dict(**ready,exit_code=p.returncode,method='parent SIGKILL after fixture checkpoint',no_graceful_shutdown=True),indent=2))
        return Path(ready['journal'])
    finally:
        if p.poll() is None:p.kill();p.wait(timeout=5)
        log.close()

class Recovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.source=crash(cls.root/'books','books')
        cls.original=cls.source.read_bytes()
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def copy(self,name,body=None):
        path=self.root/name;path.write_bytes(body if body is not None else self.original);return path
    def rewrite(self,name,rows):
        path=self.root/name
        with path.open('wb') as f:
            h='0'*64
            for r in rows:
                n=hashlib.sha256((h+packed(r)).encode()).hexdigest();f.write((packed(dict(previous=h,sha256=n,row=r))+'\n').encode());h=n
        return path
    def test_intact_prefix_exact_replay_and_accounting(self):
        r,s=inspect(self.source)
        self.assertEqual(r['status'],'interrupted');self.assertEqual(r['excluded_trailing_bytes'],0)
        self.assertGreater(r['replay']['total_books'],0);self.assertTrue(r['replay']['exact_packets'])
        self.assertIsNone(r['accounting']['delivered']);self.assertIsNone(r['accounting']['crash_time'])
        self.assertEqual(self.source.read_bytes(),self.original)
    def test_torn_last_record_and_changed_source(self):
        path=self.copy('torn.jsonl',self.original+b'{"row":')
        r=index(path,self.root/'torn-index.json');self.assertEqual(r['excluded_trailing_bytes'],7)
        self.assertEqual(reopen_index(self.root/'torn-index.json',r['recovery_identity'])[0],r)
        with path.open('ab') as f:f.write(b' ')
        with self.assertRaises(ValueError):reopen_index(self.root/'torn-index.json')
    def test_invalid_complete_interior_and_terminal_lines(self):
        for name,body in [('interior',self.original.replace(b'\n',b'\n{bad}\n',1)),('last',self.original+b'{bad}\n'),('cr',self.original.replace(b'\n',b'\rBAD\n',1))]:
            with self.subTest(name=name),self.assertRaises(ValueError):inspect(self.copy(name,body))
    def test_chain_identity_and_dependency_fail_closed(self):
        with self.assertRaises(ValueError):inspect(self.copy('chain',self.original.replace(b'"previous":"0',b'"previous":"1',1)))
        rows=reopen(self.source)['rows']
        bad=deepcopy(rows);bad[-1]['session_id']='00000000-0000-0000-0000-000000000000'
        with self.assertRaises(ValueError):inspect(self.rewrite('identity',bad))
        for kind in ('market_selected','prediction_command','prediction_frame'):
            with self.subTest(kind=kind),self.assertRaises((ValueError,KeyError)):
                inspect(self.rewrite(kind,[r for r in rows if r['type']!=kind]))
    def test_before_image_reconnect_and_finalization(self):
        for phase in ('before_image','reconnect','finalization','torn'):
            with self.subTest(phase=phase):
                path=crash(self.root/phase,phase);r,s=inspect(path)
                if phase=='before_image':self.assertEqual(r['counts']['books'],0)
                if phase=='reconnect':self.assertIn('controlled_interruption',[x['type'] for x in s['rows']])
                if phase=='finalization':self.assertTrue(r['terminal_record_present']);self.assertEqual(r['status'],'interrupted_finalization')
                if phase=='torn':self.assertGreater(r['excluded_trailing_bytes'],0)
    def test_completed_behavior_and_live_guard_unchanged(self):
        folder=ROOT/'evidence/e6/live-watch/sessions/2a1fa76c-46a3-4fb8-9d55-403b3b5313b7'
        guard=folder.parent/'attempt.json';before=guard.read_bytes()
        self.assertEqual(validate_saved(folder)['counts']['books'],36)
        self.assertEqual(verify_all(folder/'observations.jsonl')['total_packets'],72)
        from app.dashboard.e6_live import Owner
        owner=Owner(folder.parent)
        with self.assertRaises(ValueError):asyncio.run(owner.start())
        self.assertEqual(guard.read_bytes(),before)

class ReadOnlySurface(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_reopen_no_activation_and_identity_error(self):
        from aiohttp.test_utils import TestClient,TestServer
        from app.dashboard.e6_recovery import Reader,load_saved,card_source,CATALOG
        from app.dashboard.e6_live import create_app
        from unittest.mock import patch
        with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('credentials')):
            app=create_app(owner=Reader(CATALOG),saved_loader=load_saved,assets=ROOT/'app/dashboard/e6_recovery_static',card_source=card_source())
            async with TestClient(TestServer(app)) as c:
                r=await c.get('/api/status');status=await r.json()
                self.assertFalse(status['start_available']);self.assertFalse(status['active'])
                sid=status['saved'][0]
                r=await c.get('/api/saved/'+sid);p=await r.json();self.assertIn('recovery',p)
                self.assertEqual((await c.get('/api/saved/'+sid+'?hash=wrong')).status,422)
                origin=str(c.make_url('/')).rstrip('/')
                self.assertEqual((await c.post('/api/start',headers={'Origin':origin,'Content-Type':'application/json'},data='{}')).status,422)
                self.assertFalse((await (await c.get('/api/status')).json())['active'])
    def test_offline_guarded_reopening(self):
        code="""
from app.dashboard.e5_preview import isolate_process
from app.dashboard.e6_recovery import CATALOG,load_saved
isolate_process()
for p in CATALOG.glob('*/recovery.json'):
 v=load_saved(p.parent);assert not v['live'];assert v['recovery']['accounting']['crash_time'] is None
print('all recovery indexes reopened with outbound, credential-file, database and subprocess guards active')
"""
        r=subprocess.run([sys.executable,'-c',code],cwd=ROOT,capture_output=True,text=True,env={'PATH':'/usr/bin:/bin'},check=True)
        self.assertIn('guards active',r.stdout)
