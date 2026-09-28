import json
from pathlib import Path
import tempfile
import unittest
from scripts.supervise_comparison import Supervisor, Evidence, LocalApp


class App:
    def __init__(self):
        self.status = dict(active=False, start_available=True, session=None, cleanup_complete=True)
        self.posts = 0
        self.fail_status = False
        self.fail_dashboard = False
        self.saved = dict(state='saved', comparisons=[{'price': '0.42', 'quantity': '100.25'}])

    def request(self, route, *, stop=False):
        if route == '/api/status':
            if self.fail_status:
                raise TimeoutError('status transport lost')
            return dict(self.status)
        if stop:
            self.posts += 1
            self.status.update(active=False, stop_reason='manual_stop', cleanup_complete=True)
            return dict(self.status)
        if self.fail_dashboard:
            raise ValueError('dashboard failed')
        return dict(self.saved)


class Supervision(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root/'run'
        self.output.mkdir()
        self.clock = 1000.
        self.app = App()
        self.messages = []
        self.evidence = Evidence(self.root/'observer')
        self.monitor = Supervisor(self.app,self.output,'test-attempt',self.evidence,
                                  clock=lambda:self.clock,announce=lambda text,**kw:self.messages.append(text))

    def start(self):
        (self.output/'b3-attempt.json').write_text(json.dumps(dict(attempt_id='test-attempt',started_monotonic=1000.)))
        self.app.status.update(active=True,start_available=False,session='test-attempt',cleanup_complete=False)

    def close(self, elapsed=120.):
        self.app.status.update(active=False,cleanup_complete=True,stop_reason='manual_stop')
        (self.output/'network-closed.json').write_text(json.dumps(dict(attempt_id='test-attempt',monotonic=1000.+elapsed)))

    def test_navigation_has_no_browser_dependency_and_reminders_follow_consumed_marker(self):
        self.monitor.ready();self.start()
        # No browser exists: API observations remain usable through any page navigation.
        for elapsed in [0,30,89,90,109,110,119,120]:
            self.clock=1000+elapsed;self.monitor.tick()
        self.assertEqual([x['due_seconds'] for x in self.monitor.guidance],[90,110,120])
        self.assertEqual(self.app.posts,0)
        self.close();self.monitor.tick()
        r=json.loads((self.evidence.folder/'result.json').read_text())
        self.assertTrue(r['saved_comparisons_exact'])
        self.assertIn('verify operator',r['stop_classification'])
        self.assertTrue(self.monitor.finished)

    def test_missed_manual_point_is_separately_labeled_safety_stop(self):
        self.monitor.ready();self.start();self.monitor.tick();self.clock=1140;self.monitor.tick()
        self.assertEqual(self.app.posts,1)
        self.close(140);self.monitor.tick()
        result=json.loads((self.evidence.folder/'result.json').read_text())
        self.assertIn('NOT manual Stop',result['stop_classification'])

    def test_status_transport_failure_attempts_stop_from_previously_bound_session(self):
        def sleep(_):
            if self.monitor.started is None:self.start()
            else:self.app.fail_status=True
        with self.assertRaises(TimeoutError):self.monitor.run(sleep=sleep)
        self.assertEqual(self.app.posts,1)
        self.assertTrue((self.evidence.folder/'failure.json').exists())

    def test_evidence_failure_still_closes_intake(self):
        original=self.evidence.save
        def save(name,value):
            if name=='status-samples.json':raise OSError('disk failure')
            original(name,value)
        self.evidence.save=save
        with self.assertRaisesRegex(OSError,'disk failure'):
            self.monitor.run(sleep=lambda _:self.start())
        self.assertEqual(self.app.posts,1)
        self.assertIn('NOT manual Stop',self.monitor.safety['kind'])

    def test_wrong_session_is_not_stopped(self):
        def sleep(_):self.start();self.app.status['session']='another-attempt'
        with self.assertRaisesRegex(ValueError,'identity changed'):self.monitor.run(sleep=sleep)
        self.assertEqual(self.app.posts,0)

    def test_consumed_readiness_is_rejected_without_interfering(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'consumed'):self.monitor.run()
        self.assertEqual(self.app.posts,0)

    def test_saved_mismatch_cannot_be_reported_as_success(self):
        self.monitor.ready();self.start();self.monitor.tick();self.close()
        original=self.app.request;n=0
        def request(route,**kw):
            nonlocal n
            value=original(route,**kw)
            if route.startswith('/api/dashboard'):
                n+=1;value['comparisons']=[{'version':n}]
            return value
        self.app.request=request
        with self.assertRaisesRegex(ValueError,'mismatch'):self.monitor.tick()
        self.assertFalse(self.monitor.finished)

    def test_evidence_cap_reserves_stop_report(self):
        e=Evidence(self.root/'small',limit=70000)
        with self.assertRaisesRegex(RuntimeError,'cap'):e.save('observations.json','x'*5000)
        e.save('safety-stop.json',{'stopped':True})
        self.assertTrue((e.folder/'safety-stop.json').exists())

    def test_local_requests_cannot_access_providers_or_start(self):
        for url in ['https://external-api.kalshi.com','http://localhost:8820','http://127.0.0.1:8820/provider','http://user@127.0.0.1']:
            with self.assertRaises(ValueError):LocalApp(url)
        with self.assertRaises(ValueError):LocalApp().request('/api/start')


if __name__=='__main__':unittest.main()
