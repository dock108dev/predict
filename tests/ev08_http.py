"""Guarded representative HTTP/browser runtime with authored retained inputs."""
import argparse
import asyncio
from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
import resource
import signal
import sys
from time import perf_counter, time
from unittest.mock import patch

from aiohttp import web
from app.dashboard.current_state import CURRENT_KEY
from app.dashboard.multi_game_server import create_app
from app.dashboard.current_contract import quotes_of, packed
from tests.current_fixture import InjectedTestProvider
from tests.test_current_state import owner
from tests.ev07_fixture_runtime import FixtureBoundary, FIXTURE_POLICY, fixture_app


TIMING_SCRIPT = r"""const report={navigation:'fresh document; filesystem cache uncontrolled',requests:[],frames:[],longTasks:[],width:innerWidth,height:innerHeight};
let requestedGeneration=null,acceptedGeneration=null,resultRevisions=new Set();
const publish=()=>{document.documentElement.dataset.ev08Metrics=JSON.stringify(report);};
const read=window.fetch.bind(window);
window.fetch=async(url,...args)=>{
  const query=new URL(String(url),location.href);if(query.pathname==='/api/comparison')requestedGeneration=query.searchParams.get('request_generation');
  const started=performance.now(),response=await read(url,...args),headers=performance.now();
  const item={url:String(url),started,headers,status:response.status};report.requests.push(item);if(report.requests.length>80)report.requests.shift();
  response.json=async()=>{const start=performance.now(),text=await response.text();item.bodyEnd=performance.now();item.bodyMs=item.bodyEnd-start;const value=JSON.parse(text);item.bodyAndParseEnd=performance.now();item.parseMs=item.bodyAndParseEnd-item.bodyEnd;
    item.runtime=value.runtime_id;item.revision=value.state_revision;item.generation=value.request_generation;
    if(query.pathname==='/api/comparison'&&response.ok&&String(value.request_generation)===String(requestedGeneration)){acceptedGeneration=String(value.request_generation);resultRevisions=new Set([...(value.rows||[]).map(r=>r.funded_estimate?.revision),...(value.funded_pairs||[]).map(p=>p.revision)].filter(Boolean));}
    publish();return value;};publish();return response;
};
const observeContent=()=>{
  const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight&&r.right>0&&r.left<innerWidth;};
  const price=[...document.querySelectorAll('.price-button strong,.ranking-row button>div:nth-child(2) strong')].find(e=>visible(e)&&/^[+−-]?\d/.test(e.textContent.trim()));
  const estimate=[...document.querySelectorAll('.ranking-row .ranking-result')].find(e=>visible(e)&&/[\d][,.\d]*\s*%|\$\s*[\d]/.test(e.textContent)&&!/(pending|recalculating|unavailable|restoring)/i.test(e.textContent)&&resultRevisions.has(e.closest('.ranking-row').dataset.resultRevision)&&acceptedGeneration===String(requestedGeneration));
  const boardEstimate=[...document.querySelectorAll('.price-button .quote-estimate')].find(e=>visible(e)&&/[\d][,.\d]*\s*%|\$\s*[\d]/.test(e.textContent)&&!/(pending|recalculating|unavailable|restoring)/i.test(e.textContent)&&e.closest('button').review?.quote?.calculations?.funded_estimate?.model_available&&(requestedGeneration===null||acceptedGeneration===String(requestedGeneration)&&resultRevisions.has(e.closest('button').review.quote.calculations.funded_estimate.revision)));
  if((price||estimate||boardEstimate)&&!report.paintPending){
    report.paintPending=true;const mutation=performance.now(),generation=requestedGeneration;
    requestAnimationFrame(()=>requestAnimationFrame(()=>{const frame=performance.now(),hasPrice=price?.isConnected&&visible(price),hasEstimate=generation===requestedGeneration&&((estimate?.isConnected&&visible(estimate)&&resultRevisions.has(estimate.closest('.ranking-row').dataset.resultRevision)&&acceptedGeneration===String(requestedGeneration))||(boardEstimate?.isConnected&&visible(boardEstimate)&&boardEstimate.closest('button').review?.quote?.calculations?.funded_estimate?.model_available));if(hasPrice)report.firstPricePaint??=frame;if(hasEstimate)report.firstEstimatePaint??=frame;if(hasPrice||hasEstimate){report.frames.push({mutation,paintedFrame:frame,prices:Boolean(hasPrice),estimates:Boolean(hasEstimate),requestedGeneration,acceptedGeneration,rows:document.querySelectorAll('.price-button,.ranking-row').length});if(report.frames.length>30)report.frames.shift();report.firstUsefulPaint??=frame;}report.paintPending=false;publish();}));
  }
};
const observe=new MutationObserver(observeContent);
document.addEventListener('DOMContentLoaded',()=>{report.domReady=performance.now();observe.observe(document.body,{subtree:true,childList:true,characterData:true});document.addEventListener('scroll',observeContent,{capture:true,passive:true});window.addEventListener('resize',observeContent);observeContent();publish();});
try{new PerformanceObserver(list=>{for(const task of list.getEntries())report.longTasks.push({start:task.startTime,ms:task.duration});report.longTasks=report.longTasks.slice(-50);publish();}).observe({type:'longtask',buffered:true});}catch{}
""".replace('\\\n','\n')


def instrument(app, out, records):
    active = set()
    @web.middleware
    async def timing(req, handler):
        start=perf_counter();entered=time();peak_before=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        active.add(id(req))
        with (out/'phases.jsonl').open('a') as stream:
            store=app[CURRENT_KEY]
            stream.write(json.dumps(dict(phase='request_enter',path=req.path,query=dict(req.query),
                active_handlers=len(active),published_groups=sum(len(e['groups']) for e in store._state['events']),
                cache_bytes=0 if store._comparison_body_cache is None else len(store._comparison_body_cache[2]),
                encoded_owner_metrics=dict(store.encoded_bodies.metrics),
                live_encoded_file_bytes=sum(o.size for o in store.encoded_bodies.owners),
                live_encoded_owners=len(store.encoded_bodies.owners),live_encoded_readers=len(store.encoded_bodies.readers),
                peak_bytes=peak_before,at=entered))+'\n')
        try:response=await handler(req)
        finally:active.discard(id(req))
        if req.path in ('/','/ev','/arbs') and isinstance(response,web.FileResponse):
            filename={'/':'index.html','/ev':'ev.html','/arbs':'arbs.html'}[req.path]
            html=Path('app/dashboard/opportunity_static/current',filename).read_text()
            response=web.Response(text=html.replace('</head>','<script src="/__ev08/timing.js"></script></head>'),content_type='text/html',headers=dict(response.headers))
        if req.path.startswith('/api/') or req.path=='/__ev08/selected-context':
            sent=req.headers.get('X-EV08-Sent-At')
            dispatched=req.headers.get('X-EV08-Dispatch-Monotonic')
            records.append(dict(path=req.path,query=dict(req.query),status=response.status,
                handler_seconds=perf_counter()-start,dispatch_monotonic=None if dispatched is None else float(dispatched),
                entry_monotonic=start,queue_seconds=None if dispatched is None else start-float(dispatched),dispatch_to_handler_seconds=None if sent is None else entered-float(sent),
                peak_before_bytes=peak_before,peak_after_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                response_bytes=response.content_length if isinstance(response,web.Response) else None))
            records[:]=records[-150:]
            (out/'server-requests.json').write_text(json.dumps(records,indent=2)+'\n')
        return response
    app.middlewares.insert(0,timing)
    async def script(req):return web.Response(text=TIMING_SCRIPT,content_type='text/javascript')
    app.router.add_get('/__ev08/timing.js',script)


async def main(args):
    if not os.environ.get('PREDICT_CI_ISOLATED_ROOT') or not os.environ.get('PREDICT_CI_REPORT_ROOT'):
        raise ValueError('Inherited outbound/private-state guard required')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    task=asyncio.current_task()
    # A disposable browser listener has an explicit graceful fixture shutdown.
    for sig in (signal.SIGINT,signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig,task.cancel)
    records=[];started=perf_counter();phases={};lags=[];stop=False
    with ExitStack() as stack, FixtureBoundary() as boundary:
        for target in ('app.dashboard.current_incremental.load','app.comparison.current_metrics.load_estimate_policy'):
            stack.enter_context(patch(target,new=lambda:FIXTURE_POLICY))
        if args.profile:
            from tests.ev08_seams import instrument_seams
            instrument_seams(stack,out)
        if args.retained:
            tick=perf_counter();body=Path(args.retained).read_bytes();phases['read_seconds']=perf_counter()-tick
            phases['input_sha256']=sha256(body).hexdigest()
            tick=perf_counter();raw=json.loads(body);del body;phases['decode_seconds']=perf_counter()-tick
            injected=InjectedTestProvider(dict(raw,events=[],comparison_profiles={}))
            fixture_owner=owner();fixture_owner.start.side_effect=boundary.refuse('owner.start')
            app=create_app(owner=fixture_owner,sessions={},current_provider=injected)
            store=app[CURRENT_KEY];store.monotonic=lambda:0;store._age_origin=0
            raw['state_revision']=2;tick=perf_counter();store.commit(raw);phases['admission_seconds']=perf_counter()-tick
            phases.update(games=len(store._state['events']),quotes=len(store.index(store._state)),state_bytes=len(packed(store._state)),
                peak_after_admission_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                pairs=sum(len(e['funded_pairs']) for e in store._state['events']),
                funded=sum(q['calculations']['funded_estimate']['model_available'] for e in store._state['events'] for g in e['groups'] for o in g['outcomes'] for q in quotes_of(o)),
                clock='explicit paused authored evaluation clock; ordinary aging covered separately')
            del raw
        else:app=fixture_app(boundary,out/'fixture');store=app[CURRENT_KEY]
        instrument(app,out,records)
        async def selected_context(req):
            # Test-only context discovery is measured separately. It cannot
            # acquire or renew clocks, and does not weaken pinned Details.
            store.refresh_age();state=store._state
            pair=next((p for e in state['events'] for p in e.get('funded_pairs',[])),None)
            qid=pair['legs'][0]['quote_id'] if pair else next(iter(store.index(state)))
            params=dict(runtime_id=state['runtime_id'],state_revision=state['state_revision'],quote_id=qid)
            if pair:
                a,b=pair['legs']
                params.update(pair_id=pair['id'],pair_revision=pair['revision'],objective=pair['objective'],
                    quote_revision=str(a['quote_revision']),opposing_quote_id=b['quote_id'],
                    opposing_quote_revision=str(b['quote_revision']))
            return web.json_response(params)
        app.router.add_get('/__ev08/selected-context',selected_context)
        if args.advancing_clock:
            store.monotonic=perf_counter;store._age_origin=perf_counter()
            phases['clock']='authored evaluation clock advancing from retained as-of; original observations unchanged'
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0)
        async def pulse():
            previous=perf_counter()
            while not stop:
                await asyncio.sleep(.01);now=perf_counter();lags.append(max(0,now-previous-.01));previous=now
                if len(lags)>20000:del lags[:10000]
        try:
            await site.start();port=site._server.sockets[0].getsockname()[1];url='http://127.0.0.1:'+str(port)
            phases.update(url=url,listener_ready_seconds=perf_counter()-started,cold_filesystem=False,cold_application=True)
            (out/'startup.json').write_text(json.dumps(phases,indent=2)+'\n');print('EV08_URL='+url,flush=True)
            pulse_task=asyncio.create_task(pulse())
            if args.serve_only:
                await asyncio.Event().wait()
            pair=next((p for e in store._state['events'] for p in e.get('funded_pairs',[])),None)
            from urllib.parse import urlencode
            quote_id=pair['legs'][0]['quote_id'] if pair else next(iter(store.index(store._state)))
            params=dict(runtime_id=store._state['runtime_id'],state_revision=store._state['state_revision'],quote_id=quote_id)
            if pair:params.update(pair_id=pair['id'],pair_revision=pair['revision'],objective=pair['objective'])
            details='/api/current/details?'+urlencode(params)
            command=[sys.executable,'-m','tests.ev08_httpclient','--url',url,'--details',details,'--out',str(out/'client-measurements.json')]
            if args.retained:command.append('--burst')
            if args.advancing_clock:command.append('--fresh-details')
            process=await asyncio.create_subprocess_exec(*command)
            if await process.wait():raise ValueError('Isolated HTTP client failed')
            measurements=json.loads((out/'client-measurements.json').read_text())
            measurements.update(concurrency=[1,4,3],event_loop_lag_seconds=lags,server_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                server_kernel_high_water_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                calculation_jobs=store.comparison_jobs.metrics,
                common_monotonic_boundary='same-host perf_counter CLOCK_MONOTONIC; separate client and server processes',
                retained_comparison_cache_bytes=0 if store._comparison_body_cache is None else len(store._comparison_body_cache[2]),
                encoded_owner_metrics=dict(store.encoded_bodies.metrics),
                live_encoded_file_bytes=sum(o.size for o in store.encoded_bodies.owners),
                live_encoded_owners=len(store.encoded_bodies.owners),live_encoded_readers=len(store.encoded_bodies.readers),
                ordinary_runtime_restarted=False,evidence_class='authored retained HTTP; no source/account qualification')
            (out/'http-measurements.json').write_text(json.dumps(measurements,indent=2)+'\n')
            if measurements['server_peak_rss_bytes']>=768*1024*1024:raise ValueError('Server process memory cap')
            print('HTTP_MEASUREMENTS_COMPLETE',flush=True)
            if args.serve:await asyncio.Event().wait()
        finally:
            stop=True
            if 'pulse_task' in locals():pulse_task.cancel();await asyncio.gather(pulse_task,return_exceptions=True)
            await runner.cleanup()
            (out/'lag-and-stop.json').write_text(json.dumps(dict(
                event_loop_lag_seconds=lags,calculation_jobs=store.comparison_jobs.metrics,
                encoded_owner_metrics=store.encoded_bodies.metrics,
                remaining_encoded_owners=len(store.encoded_bodies.owners),
                remaining_encoded_readers=len(store.encoded_bodies.readers),
                actual_driver_done=store.comparison_jobs.driver is None or store.comparison_jobs.driver.done(),
                remaining_active=store.comparison_jobs.active is not None,
                remaining_pending=store.comparison_jobs.pending is not None,
                evidence_class='fixture application cleanup; watchdog group cleanup is separate'))+'\n')
            (out/'shutdown.json').write_text(json.dumps(dict(cleanup_complete=True,provider_requests=0,forbidden_dispatches=boundary.calls,
                outgoing_connects=[v for v in boundary.network if '127.0.0.1' not in v['address']],peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);parser.add_argument('--retained');parser.add_argument('--serve',action='store_true');parser.add_argument('--serve-only',action='store_true');parser.add_argument('--profile',action='store_true');parser.add_argument('--advancing-clock',action='store_true')
    asyncio.run(main(parser.parse_args()))
