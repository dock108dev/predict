"""Explicit isolated UI-state verifier. Never imported by the review preview."""
import asyncio
from urllib.parse import urlparse,parse_qs
from aiohttp import web
from app.dashboard.e5_preview import create_app,isolate_process
@web.middleware
async def state_fixture(request,handler):
    if request.path=='/api/package':
        state=parse_qs(urlparse(request.headers.get('Referer','')).query).get('state',[''])[0]
        if state=='empty':return web.json_response({'mode':'Synthetic','cases':[],'estimates':[]})
        if state=='invalid':return web.json_response({'error':'Saved evidence validation failed','reason':'TEST ONLY: changed dependency identity'},status=422)
        if state=='loading':await asyncio.sleep(8)
    return await handler(request)
if __name__=='__main__':
    isolate_process();app=create_app();app.middlewares.insert(0,state_fixture)
    web.run_app(app,host='127.0.0.1',port=8776)
