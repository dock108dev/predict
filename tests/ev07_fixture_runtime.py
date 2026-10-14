"""Isolated authored EV07 HTTP/browser fixture; never launches acquisition.

Requires an environment that permits loopback sockets. Uses revised production
assets and routes, plus a separately identified fixed-example inspection page.
"""
import asyncio
from copy import deepcopy
from pathlib import Path
import json
import argparse
import os
import sys
from contextlib import ExitStack
from unittest.mock import patch
from aiohttp import web

from app.collection.current_benchmark import attach
from app.dashboard.current_normalized import catalog_from_normalized
from app.dashboard.current_state import CURRENT_KEY
from app.dashboard.multi_game_server import create_app
from tests.current_fixture import InjectedTestProvider
from tests.test_current_state import owner
from tests.test_ev02_occurrence import rows, envelope
from tests.test_comparison_source_inputs import authored_opposition
from tests.test_ev05_funded import vector, run, bind
from tests.test_ev06_pairs import exact_example
from app.comparison.estimated_pair import evaluate
from app.comparison.funded_explanation import explanation
from app.comparison.estimated_policy import EstimatePolicy

# Authored, immutable fixture policy. Every implicit load in the isolated process
# is redirected to this object for startup, aging, transitions and runtime reset.
FIXTURE_POLICY = EstimatePolicy()


class FixtureBoundary:
    def __init__(self):
        self.calls=[]
        self.mode='default'
        self.stack=ExitStack()
        self.network=[]
        self.tasks=[]
        self.active=False

    def __enter__(self):
        self.active=True
        def audit(event,args):
            if self.active and event=='socket.connect':
                self.network.append(dict(event=event,address=str(args[1])))
        sys.addaudithook(audit)
        original=asyncio.create_task
        def task(coro,*args,**kwargs):
            name=getattr(coro,'__qualname__',type(coro).__name__)
            self.tasks.append(name)
            if any(term in name.lower() for term in ('acquisition','collect','provider','due_worker')):
                coro.close()
                return self.refuse('task:'+name)()
            return original(coro,*args,**kwargs)
        # Recording mocks retain each coroutine/financial call argument graph
        # across the entire retained-slate run. These guards need interception,
        # not an unbounded call history; sanitized task/network evidence is
        # retained explicitly above without retaining calculation inputs.
        self.stack.enter_context(patch('asyncio.create_task',new=task))
        self.stack.enter_context(patch('app.comparison.estimated_policy.load',new=lambda:FIXTURE_POLICY))
        self.stack.enter_context(patch('app.dashboard.current_incremental.load',new=lambda:FIXTURE_POLICY))
        from app.comparison.estimated_consumer import _template_payouts
        def payouts(q,*args,**kwargs):
            values,basis,details=_template_payouts(q,*args,**kwargs)
            if self.mode=='conditional' and q['venue']=='prophetx':
                values['tie']=None
                details['authored_fixture']='Unknown tie payout; decisive-only conditional inspection'
            return values,basis,details
        self.stack.enter_context(patch('app.comparison.estimated_consumer._template_payouts',new=payouts))
        return self

    def __exit__(self,*exc):
        self.active=False
        return self.stack.__exit__(*exc)

    def refuse(self,name):
        def denied(*args,**kwargs):
            self.calls.append(name)
            raise AssertionError('Fixture acquisition/worker dispatch forbidden: '+name)
        return denied


def authored_fixture(mode='default'):
    records=[]
    for venue in ('kalshi','polymarket_us','novig','prophetx'):
        records.extend(rows(venue,'authored:ev07:'+venue,binary=venue in ('kalshi','polymarket_us')))
    # Independent explicit alternative: same native meaning, different instrument.
    alternative=deepcopy(records[0]);alternative['quote']['source']['native_outcome_id']+=':alternative'
    alternative['quote']['original']['value']='0.42';records.append(alternative)
    reference_seed=rows('the_odds_api','authored:ev07:reference',venue='novig',binary=False)[0]
    refs=authored_opposition(reference_seed)
    for ref in refs:
        ref['quote']['times']=dict(records[0]['quote']['times'])
        ref['quote']['original']['value']='2'
    # USD stake for aggregate stake venue models; original YES/NO/LONG/SHORT stay distinct.
    for record in records:
        if record['quote']['venue'] in ('novig','prophetx'):
            record['quote']['original'].update(value='2',units='decimal_odds',quantity_units='USD_stake')
        record['comparison_source_metadata']=dict(phase='pregame',overtime='included',native_key=[record['quote']['venue'],*[record['quote']['source'][k] for k in ('native_event_id','native_market_id','native_outcome_id','native_side')]])
    attach(records,refs)
    from app.comparison.occurrence_matching import OccurrenceResolver
    from app.comparison.event_links import EventLinks
    raw=catalog_from_normalized(dict(envelope(),runtime_id='synthetic:ev07:bills-rams'),records,reference_records=refs,occurrence_resolver=OccurrenceResolver(links=EventLinks()))
    # Explicit authored profiles on the admitted native contracts. This does not
    # promote any real-provider membership or account applicability.
    from dataclasses import replace
    from app.comparison.current_dependencies import KINDS, VERSION
    from app.comparison.estimated_content import attach as content_attach
    from app.comparison.source_inputs import _selection
    from app.comparison.domain import Scope, ExactNumber, NativeProvenance, ScorePredicate, Price
    from app.comparison.pinnacle import ReferenceOutcome, ReferenceSet
    from app.comparison.shared_templates import ProfilePool
    from app.dashboard.current_contract import quotes_of,stamp
    profiles={}
    originals={r['quote']['source']['native_outcome_id']:r for r in records}
    for event in raw['events']:
        for group in event['groups']:
            for outcome in group['outcomes']:
                for q in quotes_of(outcome):
                    record=deepcopy(originals[q['source']['native_outcome_id']])
                    record['market_identity']['event']=['predict-occurrence-1'];record['event']['game_id']=event['id']
                    ctx=dict(event=event,group=group,outcome=outcome,quote=q)
                    attached=dict(profiles={},comparison_input_refs=dict(version=VERSION,refs=dict.fromkeys(KINDS),phase='pregame'),
                        gaps={k:dict(status='absent',reason=k+'_authored_unknown') for k in KINDS})
                    content_attach(attached,record,ctx,at=stamp(raw['clock_at']))
                    q['comparison_input_refs']=attached['comparison_input_refs'];q['comparison_input_status']=attached['gaps']
                    profiles.update(attached['profiles'])
                    selected,_=_selection(record,ctx,Scope('full_game','included','conditional_completed_result'))
                    bind(q,profiles,'identity',dict(selection=selected.to_dict(),current_selection_binding=deepcopy(q['binding']['selection'])))
                    refs=[]
                    weights=('0.5','0.5') if mode=='zero' else ('0.47','0.53')
                    for participant,operator,probability in ((selected.event.home_id,'gt',weights[0]),(selected.event.away_id,'lt',weights[1])):
                        from decimal import Decimal, localcontext
                        with localcontext() as precision:
                            precision.prec=50
                            odds=ExactNumber(format(Decimal(1)/Decimal(probability),'f'))
                        native=NativeProvenance('pinnacle','authored:ev07:reference','authored:ev07:reference-market',participant,'bookmaker_outcome',participant,selected.native.evidence)
                        selection=replace(selected,participant_id=participant,predicate=ScorePredicate('home_margin',operator,ExactNumber('0')),native=native,price=Price(odds,'decimal_odds','usd_per_usd_stake','USD'))
                        refs.append(ReferenceOutcome(selection,odds,raw['clock_at'],None,raw['clock_at'],'authored:ref:'+participant))
                    reference=ReferenceSet(tuple(refs),'a'*64,'decisive_win_loss')
                    bind(q,profiles,'reference',dict(outcomes=[r.to_dict() for r in refs],receipt_sha256=reference.receipt_sha256,conditioning='decisive_win_loss',partition_evidence_sha256=None,source_at=[r.source_at for r in refs]))
                    bind(q,profiles,'quantity',dict(grid=dict(minimum_native='1',increment_native='1'),grid_qualification='authored_fixture_grid'))
                    if q['binding']['selection']['predicate']=='win':
                        from app.dashboard.current_contract import identity
                        odds=[r.decimal_odds.original for r in refs]
                        index=0 if selected.participant_id==selected.event.home_id else 1
                        q['sharp_reference']=dict(bookmaker='pinnacle',version='pinnacle-proportional-no-vig-1',
                            selection_digest=identity('binding',q['binding']['selection']),odds=odds,selected=index,
                            selected_odds=odds[index],source_at=[r.source_at for r in refs],received_at=raw['clock_at'],
                            sha256='a'*64,maximum_age_seconds=1800)
                    if mode=='supported' and q['venue']=='prophetx':
                        q['depth']=[dict(price='2',quantity='200'),dict(price='1.9',quantity='300')]
    raw['comparison_profiles']=ProfilePool(profiles,compact=True).finish()
    return raw


def example_reviews(include_extra=False):
    q,p,ctx=vector();single=run(q,p,ctx,details=True);single['explanation']=explanation(single)
    q['calculations']={'funded_estimate':single};q['display']={'american':'+100'}
    one=dict(event=ctx['event'],group=ctx['group'],outcome={'label':'Example 8.1 — fixed authored trade'},quote=q,mode='synthetic')
    legs,p,event=exact_example();pair=evaluate(legs,quantities=('1010','1010'),details=True);pair['explanation']=explanation(pair,pair=True)
    two=dict(event=event,quote=legs[0].q,pair=pair,leg_quotes={leg.q['id']:leg.q for leg in legs},mode='synthetic')
    q,p,ctx=vector();q['depth']=[dict(price='2',quantity='200'),dict(price='1.9',quantity='300')]
    supported=run(q,p,ctx,policy=FIXTURE_POLICY,details=True);supported['explanation']=explanation(supported)
    supported['supported_size_result']['explanation']=explanation(supported['supported_size_result'])
    q['calculations']={'funded_estimate':supported}
    three=dict(event=ctx['event'],group=ctx['group'],outcome={'label':'Observed-depth supported-size example — authored 200 @ 2 + 300 @ 1.9'},quote=q,mode='synthetic')
    q,p,ctx=vector('novig','0.5');zero=run(q,p,ctx,policy=EstimatePolicy(buffer_rate='0'),details=True);zero['explanation']=explanation(zero)
    q['calculations']={'funded_estimate':zero}
    four=dict(event=ctx['event'],group=ctx['group'],outcome={'label':'Zero example — authored fair Novig / buffer 0%'},quote=q,mode='synthetic')
    q,p,ctx=vector();conditional=run(q,p,ctx,policy=FIXTURE_POLICY,native_quantity='1000',state_cashflows=dict(home_win='0',away_win='2000',tie=None,terminal_noncompletion='1000'),details=True);conditional['explanation']=explanation(conditional)
    q['calculations']={'funded_estimate':conditional}
    five=dict(event=ctx['event'],group=ctx['group'],outcome={'label':'Conditional example — unknown tie, decisive home or away win'},quote=q,mode='synthetic')
    legs,p,event=exact_example()
    for leg in legs:
        leg.funding['state_cashflows'].update(tie='506',terminal_noncompletion='506')
        leg.cache.clear()
    positive=evaluate(legs,quantities=('1010','1010'),details=True)
    positive['explanation']=explanation(positive,pair=True)
    six=dict(event=dict(event,title='Authored positive across all modeled outcomes'),quote=legs[0].q,pair=positive,leg_quotes={leg.q['id']:leg.q for leg in legs},mode='synthetic')
    from dataclasses import replace
    legs,p,event=exact_example()
    zero_prior=evaluate(legs,quantities=('1010','1010'),policy=replace(FIXTURE_POLICY,tie='0',terminal_noncompletion='0'),details=True)
    zero_prior['explanation']=explanation(zero_prior,pair=True)
    seven=dict(event=dict(event,title='Authored zero-prior feasible loss — still Estimated hedge'),quote=legs[0].q,pair=zero_prior,leg_quotes={leg.q['id']:leg.q for leg in legs},mode='synthetic')
    return [one,two,three,four,five,six,seven] if include_extra else [one,two]


def fixture_transition(store, action, pair_id=None):
    """Explicit test-only new synthetic observations; original snapshots stay frozen."""
    from app.dashboard.current_contract import snapshot_inputs,quotes_of,stamp
    from app.comparison.estimated_pair import native_key
    from datetime import timedelta
    from uuid import uuid4
    if action=='expire_second_leg':
        store._clock_origin+=timedelta(seconds=2 if any(q['age_seconds']>=899 for value in store.index(store._state).values() for q in [value['quote']]) else 901)
        store.refresh_age()
        return dict(runtime_id=store._state['runtime_id'],state_revision=store._state['state_revision'],action=action,clocks='original source/receipt clocks unchanged; evaluation clock advanced')
    if action=='reset_runtime':
        raw=authored_fixture();raw['runtime_id']='synthetic:ev07:reset:'+str(uuid4());raw['state_revision']=1
    else:
        pair=next((p for p in store._state['events'][0]['funded_pairs'] if pair_id is None or p['id']==pair_id),None)
        if pair is None:raise ValueError('Exact authored pair unavailable; reset the fixture')
        target=pair['legs'][1]['quote_id'];raw=snapshot_inputs(store._state);raw['state_revision']+=1
        if action=='prepare_second_leg_expiry':
            raw=authored_fixture();raw['runtime_id']='synthetic:ev07:expiry:'+str(uuid4());raw['state_revision']=1
            selected_native=native_key(store.index(store._state)[target]['quote'])
            for event in raw['events']:
                for group in event['groups']:
                    for outcome in group['outcomes']:
                        for q in quotes_of(outcome):
                            if native_key(q)==selected_native:q['times']['source_at']=(stamp(raw['clock_at'])-timedelta(seconds=899)).isoformat()
            store.commit(raw)
            return dict(runtime_id=store._state['runtime_id'],state_revision=1,action=action,quote_id=target)
        if action not in ('change_second_leg','remove_second_leg','expire_second_leg','remove_reference'):
            raise ValueError('Unknown authored fixture action')
        for event in raw['events']:
            for group in event['groups']:
                for outcome in group['outcomes']:
                    if action=='remove_second_leg':
                        for venue,q in list(outcome['quotes'].items()):
                            if q['id']==target:outcome['quotes'].pop(venue)
                        for venue,qs in list(outcome.get('alternatives',{}).items()):
                            remaining=[q for q in qs if q['id']!=target]
                            if remaining and venue not in outcome['quotes']:outcome['quotes'][venue]=remaining.pop(0)
                            if remaining:outcome['alternatives'][venue]=remaining
                            else:outcome['alternatives'].pop(venue)
                    else:
                        for q in quotes_of(outcome):
                            if action=='remove_reference':
                                if q.get('sharp_reference') is not None:q['revision']+=1
                                q['comparison_input_refs']['refs']['reference']=None
                                q['comparison_input_status']['reference']=dict(status='absent',reason='authored_reference_removed')
                                q.pop('sharp_reference',None)
                            elif q['id']==target:
                                q['revision']+=1
                                if action=='change_second_leg':q['original']['value']='1.9' if q['original']['units']=='decimal_odds' else '0.45'
                                else:q['times']['source_at']=(stamp(raw['clock_at'])-timedelta(seconds=901)).isoformat()
    if not store.commit(raw):raise ValueError('Authored transition did not commit')
    return dict(runtime_id=store._state['runtime_id'],state_revision=store._state['state_revision'],action=action)


EXAMPLE_SCRIPT="""import {renderFundedDetails} from '/current/assets/comparison-board.js';
const reviews=await(await fetch('/__fixture/examples')).json();
for(const [index,review] of reviews.entries()){const pane=document.createElement('section');pane.id='fixed-example-'+index;pane.className='details';document.getElementById('examples').append(pane);renderFundedDetails(pane,review,()=>{});}
"""
CONTROL_SCRIPT="""const status=document.getElementById('fixture-status');
for(const button of document.querySelectorAll('[data-action]'))button.addEventListener('click',async()=>{try{const response=await fetch('/__fixture/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:button.dataset.action,pair_id:document.getElementById('fixture-pair').value||null,path:document.getElementById('fixture-path').value,query:JSON.parse(document.getElementById('fixture-query').value)})});const value=await response.json();status.textContent=JSON.stringify(value,null,2);}catch(error){status.textContent=error.message;}});
"""


def fixture_app(boundary, evidence_dir):
    raw=authored_fixture();provider=InjectedTestProvider(raw)
    fixture_owner=owner()
    for name in ('start','refresh','refresh_aggregate','request_due','force_due'):
        getattr(fixture_owner,name).side_effect=boundary.refuse('owner.'+name)
    # Injected provider has no acquisition startup. Observe and refuse dispatch,
    # rather than treating a literal zero as an acquisition measurement.
    provider.start=None
    for name in ('refresh_aggregate','recover','pause'):
        setattr(provider,name,boundary.refuse('provider.'+name))
    app=create_app(owner=fixture_owner,sessions={},current_provider=provider,
        watch_path=evidence_dir/'disposable-watchlists.json')
    store=app[CURRENT_KEY];store.monotonic=lambda:0;store._age_origin=0
    audit=[];injection=[];intercepted=[]
    @web.middleware
    async def fixture_audit(req,handler):
        entry=None
        if not req.path.startswith(('/current/assets/','/__fixture/')):
            entry=dict(method=req.method,path=req.path,query=dict(req.query),user_agent=req.headers.get('User-Agent'))
            audit.append(entry)
        if req.method!='GET' and not req.path.startswith('/__fixture/'):
            return web.json_response({'reason':'Fixture rejects acquisition and all ordinary mutations'},status=403)
        identity=dict(path=req.path,query=dict(req.query),runtime_id=store._state['runtime_id'],state_revision=store._state['state_revision'])
        rule=next((r for r in injection if req.path==r['path'] and all(req.query.get(k)==v for k,v in r['query'].items())),None)
        if rule:
            injection.remove(rule)
            intercepted.append(dict(identity,action=rule['action'],token=rule['token']))
            if rule['action']=='fail_next_read':
                return web.json_response({'reason':'Authored recalculation failure','fixture_token':rule['token']},status=503)
            await asyncio.sleep(2)
        result=await handler(req)
        if req.path=='/__fixture/category-comparison' and result.status==200:
            # Separately labeled fixed financial vectors exercise the ordinary
            # ranking controller. They never replace the Bills–Rams runtime.
            from app.comparison.effective_policy import effective_policy
            from app.comparison.estimated_pair import Leg
            from app.dashboard.u0_display import quote_display
            body=result.body
            try:value=json.loads(result.text)
            finally:
                if hasattr(body,'release'):body.release()
            policy=effective_policy(FIXTURE_POLICY.to_dict(),ceiling=req.query.get('ceiling'),buffer=req.query.get('buffer'))
            pairs=[];category_rows=[]
            for positive in (False,True):
                legs,profiles,event=exact_example()
                title='Authored all-state positive ranking' if positive else 'Authored estimated hedge ranking'
                rebuilt=[]
                for index,leg in enumerate(legs):
                    q=deepcopy(leg.q);q['id']='authored:ev07:category:'+str(positive)+':'+str(index)
                    funding=deepcopy(leg.funding)
                    if positive:funding['state_cashflows'].update(tie='506',terminal_noncompletion='506')
                    owned=Leg(q,leg.group,profiles,event,leg.at,funding=funding)
                    owned.conditions=deepcopy(leg.conditions);rebuilt.append(owned)
                    category_rows.append(dict(id=q['id'],quote=q,selection='Original '+q['source']['native_side']+' / '+q['binding']['selection']['predicate']+' contract',venue_odds=quote_display(q['original']['value'],q['original']['units']).get('american'),venue=q['venue']))
                pair=evaluate(rebuilt,policy=policy,quantities=('1010','1010'))
                for leg in pair['legs']:leg['venue']=next(q.q['venue'] for q in rebuilt if q.q['id']==leg['quote_id'])
                pair.update(event_id=event['id'],title=title,league='NFL',market='winner',period='full_game')
                pairs.append(pair)
            value.update(rows=category_rows,funded_pairs=pairs,funded_pair_searches=[])
            result=web.json_response(value)
        if entry is not None:
            entry.update(status=result.status,runtime_id=identity['runtime_id'],state_revision=identity['state_revision'])
        return result
    app.middlewares.insert(0,fixture_audit)
    async def audit_data(req):
        return web.json_response(dict(evidence_class='authored isolated HTTP fixture',requests=audit,
            dispatch_attempts=boundary.calls,dispatch_assertions=dict(owner=fixture_owner.mock_calls.__str__(),provider_type=type(provider).__name__,provider_start=provider.start),
            acquisition_mutations=[r for r in audit if r['method']!='GET'],intercepted=intercepted,armed=injection,
            observed_socket_connects=boundary.network,observed_task_dispatches=boundary.tasks,
            guard={k:os.environ.get(k) for k in ('PREDICT_CI_ISOLATED_ROOT','PREDICT_CI_REPORT_ROOT')},
            policy=FIXTURE_POLICY.to_dict(),mode=boundary.mode))
    async def examples(req):return web.json_response(example_reviews(include_extra=True))
    async def examples_script(req):return web.Response(text=EXAMPLE_SCRIPT,content_type='text/javascript')
    async def controls_script(req):return web.Response(text=CONTROL_SCRIPT,content_type='text/javascript')
    async def fixture_style(req):return web.Response(text='.fixture-examples .details{position:static;max-height:none;overflow:visible;margin:16px 0}.fixture-controls button{margin:8px}',content_type='text/css')
    async def examples_page(req):return web.Response(text='''<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>EV07 fixed independent examples</title><link rel="stylesheet" href="/current/assets/comparison.css"><link rel="stylesheet" href="/__fixture/style.css"><script type="module" src="/__fixture/examples.js"></script></head><body class="current-app fixture-examples"><main><h1>Authored fixed examples — separate from optimizer output</h1><p>No authentic provider coverage or owner acceptance.</p><div id="examples"></div></main></body></html>''',content_type='text/html')
    async def categories_page(req):
        page=Path('app/dashboard/opportunity_static/current/arbs.html').read_text()
        page=page.replace('Opposing allocations','Authored category rankings — fixed allocations')
        page=page.replace('/current/assets/arbs.js','/__fixture/categories.js')
        return web.Response(text=page,content_type='text/html')
    async def categories_script(req):
        return web.Response(text="const read=window.fetch.bind(window);window.fetch=(url,...args)=>read(typeof url==='string'&&url.startsWith('/api/comparison')?url.replace('/api/comparison','/__fixture/category-comparison'):url,...args);await import('/current/assets/arbs.js');",content_type='text/javascript')
    async def categories_data(req):
        matched=await app.router.resolve(req.clone(rel_url='/api/comparison'+('?' + req.query_string if req.query_string else '')))
        return await matched.handler(req)
    async def controls_page(req):
        controls=''.join('<button type="button" data-action="'+action+'">'+label+'</button>' for action,label in [('change_second_leg','Change second leg'),('remove_second_leg','Remove second leg'),('prepare_second_leg_expiry','Prepare second-leg expiry scenario'),('expire_second_leg','Advance evaluation clock to expiry'),('remove_reference','Remove Pinnacle reference'),('delay_next_read','Delay next read by 2 seconds'),('fail_next_read','Fail next recalculation read'),('reset_runtime','Reset authored runtime'),('supported','Observed-depth supported-size scenario'),('zero','Fair-price zero scenario (use buffer 0)'),('conditional','Unknown-tie conditional scenario')])
        controls+=''.join('<button type="button" data-action="'+action+'">'+label+'</button>' for action,label in [('matching_conflict','Authored matching conflict'),('prepare_kickoff','Prepare authored kickoff'),('prepare_content_expiry','Prepare authored content expiry'),('advance_boundary','Advance authored boundary by 3 seconds')])
        return web.Response(text='<html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/current/assets/comparison.css"><link rel="stylesheet" href="/__fixture/style.css"><script type="module" src="/__fixture/controls.js"></script><title>EV07 authored fixture controls</title></head><body class="current-app fixture-controls"><main><h1>Authored fixture controls</h1><p>Test-only synthetic transitions. Keep the ordinary board open in another tab. No production or provider operations.</p><label>Exact selected pair ID (optional)<input id="fixture-pair" autocomplete="off"></label><label>Intercept path<input id="fixture-path" value="/api/comparison"></label><label>Exact query JSON<input id="fixture-query" value="{}"></label><div>'+controls+'</div><pre id="fixture-status" role="status"></pre><a href="/__fixture/audit">Read request audit</a></main></body></html>',content_type='text/html')
    async def action(req):
        body=await req.json()
        try:
            from tests.ev08_fixture import ACTIONS,transition
            if body.get('action') in ACTIONS:
                return web.json_response(transition(store,boundary,body['action']))
            if body.get('action') in ('delay_next_read','fail_next_read'):
                from uuid import uuid4
                if body.get('path') not in ('/api/comparison','/api/current/details') or not isinstance(body.get('query'),dict) or not body['query'] or any(not isinstance(v,str) for v in body['query'].values()):
                    raise ValueError('Exact path and nonempty string query matcher required')
                rule=dict(action=body['action'],path=body['path'],query=body['query'],token=str(uuid4()))
                injection.append(rule)
                return web.json_response(dict(rule,armed=True))
            if body.get('action') in ('supported','zero','conditional','reset_runtime'):
                from uuid import uuid4
                boundary.mode=body['action'] if body['action']!='reset_runtime' else 'default'
                raw=authored_fixture(boundary.mode);raw['runtime_id']='synthetic:ev07:'+boundary.mode+':'+str(uuid4())
                store.commit(raw)
                return web.json_response(dict(action=body['action'],runtime_id=store._state['runtime_id'],state_revision=store._state['state_revision'],policy=store._state['estimate_policy']))
            return web.json_response(fixture_transition(store,body.get('action'),body.get('pair_id')))
        except ValueError as exc:return web.json_response({'reason':str(exc)},status=409)
    app.router.add_get('/__fixture/audit',audit_data);app.router.add_get('/__fixture/examples',examples);app.router.add_get('/__fixture/examples.html',examples_page)
    app.router.add_get('/__fixture/examples.js',examples_script);app.router.add_get('/__fixture/style.css',fixture_style)
    app.router.add_get('/__fixture/categories.html',categories_page)
    app.router.add_get('/__fixture/categories.js',categories_script);app.router.add_get('/__fixture/category-comparison',categories_data)
    app.router.add_get('/__fixture/controls.html',controls_page);app.router.add_get('/__fixture/controls.js',controls_script);app.router.add_post('/__fixture/action',action)
    return app


async def main(evidence_dir):
    if not os.environ.get('PREDICT_CI_ISOLATED_ROOT') or not os.environ.get('PREDICT_CI_REPORT_ROOT'):
        raise ValueError('Fixture requires the inherited offline/private-state CI guard')
    evidence_dir=Path(evidence_dir).resolve()
    if evidence_dir.name in ('ev05','ev06','ev07') or 'test-results/ev07/' in str(evidence_dir):
        raise ValueError('Immutable original evidence destination refused')
    evidence_dir.mkdir(parents=True,exist_ok=True)
    with FixtureBoundary() as boundary:
        app=fixture_app(boundary,evidence_dir)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0)
        try:
            await site.start();port=site._server.sockets[0].getsockname()[1]
            evidence_dir.joinpath('fixture.json').write_text(json.dumps(dict(url='http://127.0.0.1:'+str(port),evidence_class='authored isolated loopback fixture; no provider coverage',ordinary_runtime_restarted=False,policy=FIXTURE_POLICY.to_dict()),indent=2)+'\n')
            print('EV07_AUTHORED_FIXTURE_URL=http://127.0.0.1:'+str(port),flush=True)
            await asyncio.Event().wait()
        finally:await runner.cleanup()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--evidence-dir',required=True)
    args=parser.parse_args()
    asyncio.run(main(args.evidence_dir))
