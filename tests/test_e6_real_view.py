import json
import shutil
import subprocess
import sys
from copy import deepcopy
from decimal import Decimal
import unittest
import tempfile
from pathlib import Path
from aiohttp.test_utils import TestClient, TestServer
from app.dashboard import e6_real as view

class SavedRealView(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)

    def test_evidence_fails_closed(self):
        for i,(name,missing) in enumerate([(view.JOURNAL,False),(view.RUN+"run-spec.json",False),(view.RUN+"saved-observations.json",True)]):
            self.check_evidence(Path(self.temp.name)/str(i),name,missing)

    def test_exact_replay_and_all_cutoffs(self):
        package=view.load_package()
        rows=view.reopen(view.ROOT/view.JOURNAL)['rows']
        assert package['counts']==dict(frames=45,books=44,packets=88,ingress=139)
        assert package['coverage']['native_replay']['exact_packets'] is True
        assert package['coverage']['native_replay']['exact_native_books']=={'kalshi':16,'polymarket_us':28}
        assert len(package['timeline'])==52
        for point in package['timeline']:
            cutoff=next(i for i,r in enumerate(rows) if r.get('ingress_id',view.SID+':finished')==point['id'])
            known=rows[:cutoff+1]
            assert point['known_books']==sum(r['type']=='prediction_book' for r in known)
            for card in point['cards']:
                books=[r for r in known if r['type']=='prediction_book' and r['source']==card['venue']]
                health=[r for r in known if r['type']=='source_health' and r['source']==card['venue']]
                assert card['connection']==(health[-1]['state'] if health else 'idle')
                if not books:
                    assert card['book'] is None and card['age_seconds'] is None
                    continue
                row=books[-1];b=card['book']
                assert b['id']==row['ingress_id']
                assert view.exact_time(b['known_at'])<=view.exact_time(point['at'])
                assert Decimal(card['age_seconds'])==view.exact_time(point['at'])-view.exact_time(b['received_at'])
                quotes={q['side']:q for p in row['packets'] for q in p['normalized']['quotes']}
                for outcome in b['outcomes']:
                    assert outcome['quote']==quotes[outcome['side']]
                    native=next(o for o in row['book']['outcomes'] if o['outcome_id']==outcome['side'])
                    assert outcome['depth']=={s:native[s] for s in ('bids','asks')}
        assert all(c['connection']=='disconnected' for c in package['timeline'][-1]['cards'])
        assert not package['collected_now'] and not package['execution_eligible']

    def test_native_side_economics_remain_exact(self):
        package=view.load_package()
        for point in package['timeline']:
            for card in point['cards']:
                if not card['book']:continue
                outcomes={o['side']:o for o in card['book']['outcomes']}
                if card['venue']=='kalshi':
                    assert outcomes['yes']['team']=='Buffalo Bills'
                    for side,opposite in [('yes','no'),('no','yes')]:
                        q=outcomes[side]['quote'];other=outcomes[opposite]['quote']
                        assert Decimal(q['ask'])==Decimal(1)-Decimal(other['bid'])
                        assert q['ask_size']==other['bid_size']
                else:
                    assert outcomes['1315440']['team']=='Detroit Lions'
                    short=outcomes['1315441']
                    assert short['team']=='Buffalo Bills'
                    assert all(short['quote'][k] is None for k in ('bid','ask','bid_size','ask_size'))
                    assert short['depth']=={'bids':None,'asks':None}

    def test_identity_mapping_independent_of_array_order(self):
        rows=deepcopy(view.reopen(view.ROOT/view.JOURNAL)['rows'])
        spec=json.loads((view.ROOT/(view.RUN+'run-spec.json')).read_text())
        for r in rows:
            if r['type']=='market_selected' and r['source']=='polymarket_us':
                raw=r['market']['raw'];n=json.loads(raw['json_text'])
                for e in n['events']:
                    for m in e['markets']:m['marketSides'].reverse()
                raw['json_text']=json.dumps(n)
        view.validate_mapping(rows,spec)
        spec['sources']['kalshi']['market_id']='wrong'
        with self.assertRaises(ValueError):view.validate_mapping(rows,spec)

    def check_evidence(self,tmp_path,name,missing):
        pins=json.loads((view.ROOT/'app/dashboard/e6_real_identity.json').read_text())
        for n in pins:
            p=tmp_path/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(view.ROOT/n,p)
        if missing:(tmp_path/name).unlink()
        else:(tmp_path/name).write_text('{}')
        with self.assertRaises((ValueError,OSError)):view.load_package(tmp_path)

    async def test_http_error_and_read_only(self):
        tmp_path=Path(self.temp.name)
        async with TestClient(TestServer(view.create_app(tmp_path))) as client:
            r=await client.get('/api/package')
            assert r.status==422 and 'No observations' in (await r.json())['error']
            assert (await client.post('/api/package')).status==405
            assert (await client.get('/api/package',headers={'Host':'unrelated.example'})).status==403


    def test_startup_isolation(self):
        from textwrap import dedent
        code=dedent('''
    import asyncio,json,socket,psycopg
    from app.dashboard.e6_real import isolate_process,load_package,create_app
    from aiohttp import web
    isolate_process()
    p=load_package()
    async def startup():
     r=web.AppRunner(create_app());await r.setup();s=web.TCPSite(r,'127.0.0.1',0);await s.start();await r.cleanup()
    asyncio.run(startup())
    for action in [lambda:socket.getaddrinfo('example.invalid',443),lambda:socket.socket().connect(('127.0.0.1',1)),lambda:open('.env'),lambda:psycopg.connect('')]:
     try:action()
     except PermissionError:pass
     else:raise AssertionError('isolation failed')
    print(json.dumps({'startup':'file-only','books':p['counts']['books'],'guards':4}))
    ''')
        r=subprocess.run([sys.executable,'-c',code],cwd=view.ROOT,env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,check=True)
        assert json.loads(r.stdout)=={'startup':'file-only','books':44,'guards':4}
