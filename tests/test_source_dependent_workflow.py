"""One ordinary mixed-source workflow over current numeric loopback controls."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from aiohttp import web
from app.collection.source_bindings import required_cells
from app.collection.native_payload import TRANSPORT_CONTRACT
from app.dashboard.session_history import load
from app.dashboard.session_projection import stable
from tests.test_source_session import UnifiedFixture, settings
from tests.test_ordinary_native_transport import configuration


class WorkflowFixture(UnifiedFixture):
    """Exact selector replies; empty synthetic scopes are not provider absence."""
    async def rest(self,request):
        if request.path=='/trade-api/v2/series/KXNFLGAME':
            return web.json_response(dict(series=dict(ticker='KXNFLGAME',fee_type='quadratic',fee_multiplier=1)))
        if request.path=='/trade-api/v2/series/fee_changes':
            return web.json_response(dict(series_fee_change_arr=[]))
        if request.path=='/trade-api/v2/events/fee_changes':
            return web.json_response(dict(event_fee_changes=[],cursor=''))
        if request.path=='/v2/leagues':return web.json_response(dict(leagues=[]))
        if request.path=='/trade-api/v2/events' and request.query.get('series_ticker','KXNFLGAME')!='KXNFLGAME':
            self.rest_calls.append((request.path,dict(request.query)))
            return web.json_response(dict(events=[],milestones=[],cursor=''))
        if request.path=='/v1/events':
            self.rest_calls.append((request.path,dict(request.query)))
            if request.query.get('tagSlug','nfl')!='nfl':return web.json_response(dict(events=[]))
            from tests.test_coverage import pe
            event=pe('p');event.update(gameId=1,startTime=self.schedule,active=True,closed=False,
                                      markets=[self.us_market('p'+str(i)) for i in range(self.us_markets)])
            return web.json_response(dict(events=[event]))
        return await super().rest(request)


class IntegratedWorkflow(unittest.IsolatedAsyncioTestCase):
    async def test_ordinary_v2_updates_details_sizes_watch_failure_recovery_stop_download_reopen(self):
        from app.collection.engineering_authorization import source_manifest,digest
        initial_implementation=digest(source_manifest())
        with tempfile.TemporaryDirectory() as root:
            f=WorkflowFixture();owner=await f.boot(root)
            def workflow_spec():
                value=configuration();value['prediction']['discovery_requests']=48
                return value
            owner.spec_factory=workflow_spec
            config=settings(native_scopes={'kalshi':'required-63-v1','polymarket_us':'required-63-v1'},
                            correspondence_policy='source-correspondence-1')
            try:
                with patch('app.collection.venue_access.load_credentials',side_effect=AssertionError('offline credential boundary')):
                    await f.start_route(config);await f.native_images()
                    await f.wait(lambda:bool(owner.session.projection.aggregates))
                    client=f.client
                    initial=await (await client.get('/api/dashboard?view=feed')).json()
                    self.assertTrue(initial['comparisons'])
                    self.assertEqual(len(initial['aggregate_coverage']),63)
                    native=next(r for r in initial['comparisons'] if not r.get('aggregated'))
                    aggregated=next(r for r in initial['comparisons'] if r.get('aggregated'))
                    self.assertEqual({l['venue'] for r in initial['comparisons'] for l in r['legs']},
                                     {'kalshi','polymarket_us','novig','prophetx'})
                    self.assertEqual({r['origin_id'] for r in initial['references']},
                                     {'pinnacle','draftkings','betmgm'})
                    query=urlencode({k:aggregated[k] for k in ('session','hash','cutoff')})
                    detail=await (await client.get('/api/calculate?'+query)).json()
                    self.assertTrue(detail['aggregated'])
                    response=await client.post('/api/decision-sizes',json=dict(
                        session=aggregated['session'],hash=aggregated['hash'],cutoff=aggregated['cutoff'],sizes=['1']),headers=f.origin)
                    self.assertEqual(response.status,422)
                    native_size=await client.post('/api/decision-sizes',json=dict(
                        session=native['session'],hash=native['hash'],cutoff=native['cutoff'],sizes=['1'],ceiling='10',scenario='unknown'),headers=f.origin)
                    self.assertEqual(native_size.status,200,await native_size.text())
                    definition=dict(name='Source workflow',metric='raw_gap',threshold='0',quantity='1',filters={})
                    self.assertEqual((await client.post('/api/watchlists',json=[definition],headers=f.origin)).status,200)
                    before=stable(owner.current_snapshot()['aggregate_comparisons'])
                    f.quote='2.5'
                    await f.wait(lambda:stable(owner.current_snapshot()['aggregate_comparisons'])!=before)
                    await f.send(next(c for c in f.active() if c['venue']=='kalshi'))
                    f.error=True
                    await f.wait(lambda:owner.session.aggregate.health=='unavailable')
                    self.assertEqual(owner.session.state,'running')
                    await f.send(next(c for c in f.active() if c['venue']=='polymarket_us'))
                    f.error=False
                    await f.wait(lambda:owner.session.aggregate.health=='waiting')
                    prior=len(f.connections)
                    await next(c for c in f.active() if c['venue']=='kalshi')['socket'].close()
                    await f.wait(lambda:len(f.connections)>prior and len(f.active())==2)
                    await f.send(next(c for c in f.active() if c['venue']=='kalshi'))
                    await owner.session.queue.join()
                    ledger=await (await client.get('/api/source-bindings?capture='+owner.session.sid)).json()
                    self.assertEqual(ledger['source_cell_count'],252)
                    signals=await (await client.get('/api/signals')).json()
                    self.assertFalse(any(i['active'] for i in signals['items']))
                    await f.stop_route()
                    self.assertIsNone(owner.error)
                    self.assertTrue(owner.session.cleanup_complete)
                    stopped_feed=await (await client.get('/api/dashboard?view=feed')).json()
                    self.assertEqual(stopped_feed['capture'],owner.session.sid)
                    self.assertEqual(detail,await (await client.get('/api/calculate?'+query)).json())
                    from app.dashboard.opportunity_history import build_history
                    with patch('app.dashboard.opportunity_history.build_history',wraps=build_history) as rebuild:
                        report=await (await client.get('/api/opportunity-history?capture='+owner.session.sid)).json()
                        exported=await (await client.get('/api/opportunity-history?capture='+owner.session.sid+'&download=true')).json()
                        self.assertEqual(rebuild.call_count,1)
                    self.assertEqual(report,exported)
                    self.assertFalse(any(i['active'] for i in (await (await client.get('/api/signals')).json())['items']))
                    saved=load(owner.session.output)
                    self.assertEqual(len(saved['aggregate_coverage']),63)
                    self.assertEqual(saved['source_session_version'],'unified-source-session-1')
                    child=await asyncio.to_thread(subprocess.run,[str(Path.cwd()/'.venv/bin/python'),'-c',
                        'from app.dashboard.session_history import load; from app.dashboard.session_projection import stable; import sys; print(stable(load(sys.argv[1])))',
                        str(owner.session.output)],capture_output=True,text=True,check=True)
                    self.assertEqual(child.stdout.strip(),stable(saved))
                    limits=json.loads((owner.session.output/'aggregate-limits.json').read_text())
                    self.assertEqual(limits['native_transport'],TRANSPORT_CONTRACT)
                    count=len(f.odds_calls);await asyncio.sleep(.1)
                    self.assertEqual(len(f.odds_calls),count)
                    self.assertEqual(digest(source_manifest()),initial_implementation)
                    retained=os.environ.get('PREDICT_WORKFLOW_EVIDENCE')
                    if retained:
                        destination=Path(retained);destination.mkdir(parents=True,exist_ok=False)
                        copied_output=destination/'sessions'/owner.session.sid
                        shutil.copytree(owner.session.output,copied_output)
                        self.assertEqual(stable(load(copied_output)),child.stdout.strip())
                        for name,value in dict(initial_feed=initial,aggregate_detail=detail,
                            opportunity_history=report,selected_source_ledger=ledger,
                            verification=dict(evidence_mode='synthetic_numeric_loopback',provider_requests=0,
                                implementation_sha256=initial_implementation,
                                session_relative_path='sessions/'+owner.session.sid,
                                real_credentials=0,source_cells=252,required_cells=63,
                                cleanup_complete=owner.session.cleanup_complete,fresh_process_digest=child.stdout.strip(),
                                history_download_exact=True,saved_detail_exact=True,
                                aggregate_calls=len(f.odds_calls),native_connections=len(f.connections))).items():
                            (destination/(name+'.json')).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
            finally:await f.close()


if __name__=='__main__':unittest.main()
