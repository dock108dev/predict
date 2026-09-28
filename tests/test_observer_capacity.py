"""Recorder capacity and current-state guidance regressions; no provider access."""
import gzip
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from scripts.supervise_comparison import Evidence,current_status

ROOT=Path(__file__).resolve().parents[1]
RETAINED=ROOT/'evidence/supervised-observation-1e700bf5-dc41-4c73-9474-05754787c7de'

class Capacity(unittest.TestCase):
    def test_full_responses_are_lossless_and_count_compressed_bytes(self):
        with tempfile.TemporaryDirectory() as t:
            e=Evidence(Path(t)/'observer');payload={'native':('exact metadata and quantities 100.25; '*100000),'price':'0.4200','unknown':None}
            raw=(json.dumps(payload,indent=2,sort_keys=True)+'\n').encode()
            for i in range(38):e.save(f'dashboard-{i:03d}.json',payload)
            files=list(e.folder.glob('*.gz'));self.assertEqual(len(files),38)
            self.assertTrue(all(gzip.decompress(p.read_bytes())==raw for p in files))
            self.assertLess(e.used,32*1024*1024-65536)

    @unittest.skipUnless(RETAINED.exists(),'local retained actual response fixture')
    def test_retained_live_payloads_cover_full_ceiling_under_unchanged_cap(self):
        payloads=[json.loads(p.read_text()) for p in sorted(RETAINED.glob('dashboard-*.json'))]
        self.assertTrue(payloads)
        largest=max(payloads,key=lambda v:len(json.dumps(v)))
        with tempfile.TemporaryDirectory() as t:
            e=Evidence(Path(t)/'observer')
            # 37 five-second checkpoints through 180s plus two terminal responses.
            raw=(json.dumps(largest,indent=2,sort_keys=True)+'\n').encode()
            for i in range(39):e.save(f'dashboard-{i:03d}.json',largest)
            statuses=json.loads((RETAINED/'status-samples.json').read_text())
            e.save('status-samples.json',(statuses*4)[:181])
            e.save('saved-dashboard.json',largest)
            e.save('browser-checkpoint-reservation.json','x'*(1024*1024))
            e.save('result.json',{'exact':True})
            for p in e.folder.glob('*.gz'):self.assertEqual(gzip.decompress(p.read_bytes()),raw)
            result={'raw_dashboard_bytes':len(raw),'compressed_dashboard_bytes':(e.folder/'dashboard-000.json.gz').stat().st_size,'full_ceiling_recorded_bytes':e.used,'limit':e.limit,'exact_decompression':True,'scope':'Retained inputs only, no provider or browser access'}
            self.assertLess(e.used,e.limit-65536)
            print('CAPACITY_RESULT='+json.dumps(result))

    def test_finished_app_overrides_old_active_sample_and_failure_is_explicit(self):
        class App:
            def request(self,route):return {'session':'a','active':False,'cleanup_complete':True}
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'status-samples.json').write_text('[{"active":true}]');(p/'failure.json').write_text('{}');(p/'safety-stop.json').write_text('{}')
            s=current_status(App(),'a',p)
            self.assertFalse(s['guidance_allowed']);self.assertFalse(s['current_app_status']['active'])
            self.assertTrue(s['automatic_safety_stop']);self.assertTrue(s['monitor_failed'])

    def test_stale_monitor_never_allows_timed_guidance_even_if_app_active(self):
        class App:
            def request(self,route):return {'session':'a','active':True}
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);f=p/'status-samples.json';f.write_text('[]');old=time.time()-30;os.utime(f,(old,old))
            self.assertFalse(current_status(App(),'a',p)['guidance_allowed'])
            with self.assertRaisesRegex(ValueError,'different attempt'):current_status(App(),'b',p)

if __name__=='__main__':unittest.main()
