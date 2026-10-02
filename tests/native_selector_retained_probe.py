"""Ordinary probe transport replay of original supported NFL bodies, no game edits."""
import asyncio
import base64
import json
from pathlib import Path
from aiohttp import web
from tests.native_selector_runtime import Fixture as Base,check
from tests.test_native_selectors import supported

class Fixture(Base):
    classification='OFFLINE retained NFL response bytes through ordinary probe; empty responses for other sports are synthetic controls, not absence evidence; no game substitutions'
    async def rest(self,req):
        q=dict(req.query);self.queries.append((req.path,q));rows=supported()
        if req.path=='/v2/leagues':return web.json_response(dict(leagues=[]))
        if req.path.endswith('/events'):
            nfl=q.get('series_ticker')=='KXNFLGAME' or q.get('tagSlug')=='nfl'
            if not nfl:return web.json_response(dict(events=[],cursor=''))
            row=next(r for r in rows if r['path']==req.path and str(r['params'].get('offset',r['params'].get('cursor','')))==q.get('offset',q.get('cursor','')))
        elif req.path.endswith('/markets'):
            row=next(r for r in rows if r['path']==req.path and all(str(r['params'].get(k))==str(v) for k,v in q.items() if k in ('gameId','event_ticker')))
        else:raise AssertionError('Unexpected request '+req.path)
        return web.Response(body=base64.b64decode(row['body_b64']),status=row['status'])

if __name__=='__main__':
    import sys
    p=Path(sys.argv[1]);p.mkdir(exist_ok=False);asyncio.run(check(p,True,Fixture))
