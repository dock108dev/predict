'use strict';
// Authored contract and simulated DOM checks; no browser timing claim.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {Element}=require('./ev07_dom.cjs');
const source=fs.readFileSync('app/dashboard/opportunity_static/current/current-client.js','utf8');
const copy=v=>JSON.parse(JSON.stringify(v));
const at='2026-10-12T12:00:00Z';
const policy={version:'predict-estimate-policy-2',revision:'owner:1',capital_ceiling_usd:'1000',buffer_rate:'0.005'};
function fixture(){return {schema:'predict-retained-prices-1',mode:'synthetic',runtime_id:'runtime:A',generation_id:'candidate:A',settings_generation:0,estimate_policy:{...policy},status:'pending',input_epoch:null,state_revision:null,error:null,input_clock_at:at,validation_at:at,progress:{discovery_status:'validating_prices',discovered_prices:1,validated_prices:1,total_prices:null,discovered_singles:0,ready_singles:0,pending_singles:null,refused_singles:0,total_singles:null,discovered_pairs:0,ready_pairs:0,pending_pairs:null,refused_pairs:0,total_pairs:null},rows:[{id:'native:NO',revision:2,venue:'kalshi',native:{provider:'kalshi',event_id:'e',market_id:'m',outcome_id:'o',side:'no',quote_side:'ask'},original:{value:'0.64',units:'usd_per_contract',payout:'1',payout_units:'USD',quantity_units:'contracts',role:'comparison',native_value:'0.36',native_units:'usd_per_contract',transformation:'one_minus_native_bid'},times:{source_at:at,received_at:at,projected_at:at,source_time_kind:'provider_quote'},event:{id:'event',title:'Bills at Rams',league:'NFL',start_at:'2026-10-12T20:00:00Z'},market:'winner',period:'full_game',selection:'Bills not win'}],pagination:{page:0,page_size:1,total_rows:1,has_more:false}};}
function ready(){const v=fixture();v.status='ready';v.input_epoch=3;v.state_revision=8;Object.assign(v.progress,{discovery_status:'complete',total_prices:1,total_singles:1,discovered_singles:1,ready_singles:1,pending_singles:0,total_pairs:0,pending_pairs:0});return v;}
const settle=async()=>{for(let i=0;i<100;i++)await Promise.resolve();};
(async()=>{
 const {SizingPolicy,validateRetainedPrices:validate,RetainedPriceBootstrap}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
 const context={settingsGeneration:0,runtimeId:'runtime:A',generationId:'candidate:A'};
 assert.equal(validate(fixture(),context).progress.total_pairs,null,'undiscovered totals stay unknown');
 assert.equal(validate(ready(),context).state_revision,8,'only ready carries committed identity');const zeroEpoch=ready();zeroEpoch.input_epoch=0;validate(zeroEpoch,context);const longNative=fixture();longNative.rows[0].native.market_id='𐀀'.repeat(2048);validate(longNative,context);const hugeDecimal=fixture();hugeDecimal.rows[0].original={...hugeDecimal.rows[0].original,value:'9'.repeat(250)+'e256',units:'decimal_odds'};delete hugeDecimal.rows[0].original.native_value;delete hugeDecimal.rows[0].original.native_units;delete hugeDecimal.rows[0].original.transformation;validate(hugeDecimal,context);const exponent=fixture();exponent.rows[0].original.native_value='+.36e0';exponent.rows[0].original.value='64e-2';validate(exponent,context);
 const unknown=fixture();unknown.rows[0].times.source_at=null;unknown.rows[0].times.source_time_kind='unknown';unknown.rows[0].original.payout=null;unknown.rows[0].original.payout_units=null;validate(unknown,context);
 const invalid=[v=>v.schema='unknown',v=>v.mode='live',v=>v.progress.total_prices=1,v=>v.runtime_id='runtime:B',v=>v.generation_id='candidate:B',v=>v.settings_generation=1,v=>v.input_epoch=3,v=>v.state_revision=8,v=>v.progress.total_singles=0,v=>v.progress.pending_pairs=0,v=>v.progress.validated_prices=2,v=>v.progress.discovered_prices=0,v=>v.pagination.has_more=true,v=>v.pagination.total_rows=16001,v=>v.rows[0].native.outcome_id='',v=>v.rows[0].native.quote_side=null,v=>v.rows[0].revision=0,v=>v.rows[0].original.units='ambiguous',v=>v.rows[0].original.value='NaN',v=>v.rows[0].original.value='1.01',v=>v.rows[0].original.native_value='0.3600000000000000000000000001',v=>v.rows[0].times.source_at='2026-02-30T12:00:00Z',v=>v.rows[0].times.received_at='2026-10-12T12:00:01Z',v=>v.rows[0].times.source_time_kind='unknown',v=>v.input_clock_at='later',v=>v.estimate_policy.buffer_rate='2'];
 for(const change of invalid){const v=fixture();change(v);assert.throws(()=>validate(v,context),/retained price/);}
 for(const status of ['rejected','superseded','stopped']){const v=fixture();v.status=status;v.error='Candidate closed';v.rows=[];v.pagination.total_rows=0;validate(v,context);v.rows=fixture().rows;assert.throws(()=>validate(v,context));}
 const wrong=ready();wrong.progress.pending_singles=1;assert.throws(()=>validate(wrong,context));
 const malformedReady=ready();malformedReady.state_revision=null;assert.throws(()=>validate(malformedReady,context));
 const timers=new Map();let timerId=0;const timerOptions={setTimer:fn=>{timers.set(++timerId,fn);return timerId;},clearTimer:id=>timers.delete(id)};
 const sizing=new SizingPolicy(null),root=new Element('section');document.body.replaceChildren(root);
 let response=fixture(),requests=[];
 const bootstrap=new RetainedPriceBootstrap(root,sizing,{...timerOptions,fetcher:async(url,options)=>{requests.push({url,signal:options.signal});return new Response(JSON.stringify(response));}});
 await bootstrap.read(0);
 assert(root.textContent.includes('0.36 usd per contract'),'original native bid retains its numerical value and units');
 assert(root.textContent.includes('acquisition complement 0.64'),'native bid transformation is explicit');
 assert(root.textContent.includes('pending unknown'),'unknown pending counts never become zero');
 assert(root.textContent.includes('Authored offline'),'authored provenance precedes original numerical prices');assert(root.textContent.includes(at),'original clocks stay visible');assert(root.textContent.includes('Estimates remain withheld'));
 const article=root.querySelector('article'),disclosure=article.querySelector('details'),summary=disclosure.querySelector('summary');disclosure.open=true;summary.focus();
 response=copy(response);response.validation_at='2026-10-12T12:00:01Z';response.progress.discovered_prices=2;
 await bootstrap.read(0,'candidate:A');assert.equal(root.querySelector('article'),article);assert(disclosure.open);assert.equal(document.activeElement,summary,'progress polling preserves focus and disclosures');
 const drift=copy(response);drift.rows[0].original.value='0.65';drift.rows[0].original.native_value='0.35';response=drift;await bootstrap.read(0,'candidate:A');assert(root.textContent.includes('unavailable'),'same-generation price changes fail closed');assert(!root.textContent.includes('0.65'));
 bootstrap.close();assert.equal(timers.size,0,'close releases timeout and polling ownership');
 // A ignored AbortSignal is insufficient: delayed bodies still need a token,
 // exact runtime/settings/generation and post-body cancellation check.
 for(const reason of ['settings','runtime','Stop']){
  const pending=[],state=new SizingPolicy(null),r=new Element('section');
  const b=new RetainedPriceBootstrap(r,state,{...timerOptions,fetcher:(url,options)=>new Promise(resolve=>pending.push({url,signal:options.signal,resolve}))});
  b.refresh();const old=pending.shift();assert(old);
  if(reason==='settings'){state.setSettings('500','0.01');b.refresh();}
  else if(reason==='runtime')b.refresh({runtime_id:'runtime:B'});
  else b.close();
  assert(old.signal.aborted);
  old.resolve(new Response(JSON.stringify(fixture())));await settle();assert(!r.textContent.includes('0.36'),'delayed old body withheld after '+reason);
  if(reason!=='Stop'){
   const latest=pending.shift(),v=fixture();v.settings_generation=state.generation;if(reason==='runtime'){v.runtime_id='runtime:B';v.generation_id='candidate:B';}
   latest.resolve(new Response(JSON.stringify(v)));await settle();assert(r.textContent.includes('0.36'),'current generation accepted after '+reason);
  }
  b.close();assert.equal(timers.size,0);
 }
 // Delayed JSON body completion can outlive a successfully aborted request.
 const pendingBodies=[],bodyRoot=new Element('section'),bodySizing=new SizingPolicy(null);
 const bodyReader=new RetainedPriceBootstrap(bodyRoot,bodySizing,{...timerOptions,fetcher:async()=>new Response(new ReadableStream({start(controller){pendingBodies.push(controller);}}))});
 bodyReader.refresh();await settle();const oldBody=pendingBodies.shift();bodyReader.refresh({runtime_id:'runtime:B'});await settle();
 await settle();assert(!bodyRoot.textContent.includes('0.36'),'aborted delayed body reader is cancelled');assert(!bodyRoot.textContent.includes('0.36'));
 const nextBody=fixture();nextBody.runtime_id='runtime:B';nextBody.generation_id='candidate:B';const newest=pendingBodies.shift();newest.enqueue(new TextEncoder().encode(JSON.stringify(nextBody)));newest.close();await settle();assert(bodyRoot.textContent.includes('0.36'));bodyReader.close();assert.equal(timers.size,0);
 const boundedRoot=new Element('section'),boundedReader=new RetainedPriceBootstrap(boundedRoot,new SizingPolicy(null),{...timerOptions,fetcher:async()=>new Response(' '.repeat(256*1024+1))});
 await boundedReader.read(0);assert(boundedRoot.textContent.includes('exceeds its bound'));boundedReader.close();assert.equal(timers.size,0);
 const timeoutRoot=new Element('section'),timeoutReader=new RetainedPriceBootstrap(timeoutRoot,new SizingPolicy(null),{...timerOptions,fetcher:async()=>new Response(new ReadableStream({start(){}}))});
 timeoutReader.refresh();await settle();assert.equal(timers.size,1);[...timers.values()][0]();await settle();assert(timeoutRoot.textContent.includes('Read timed out'));timeoutReader.close();assert.equal(timers.size,0);
 // Complete admission cannot hide another generation or pretend a pending
 // candidate shares the previous state's epoch/revision.
 const r=new Element('section'),b=new RetainedPriceBootstrap(r,new SizingPolicy(null),timerOptions);
 b.snapshot=fixture();b.render(b.snapshot);b.complete('retained-loading:placeholder',1);assert(!r.hidden);b.complete('runtime:A',8);assert(!r.hidden);
 b.snapshot=ready();b.render(b.snapshot);b.complete('runtime:A',7);assert(!r.hidden);b.complete('runtime:A',8);assert(r.hidden);b.close();
 // The same bounded class drives all ordinary consumers before filter/settings
 // disclosures, leaving the first numerical row room in a narrow document.
 for(const file of ['index.html','ev.html','arbs.html']){const html=fs.readFileSync('app/dashboard/opportunity_static/current/'+file,'utf8');assert(html.indexOf('id="retained-prices"')<html.indexOf('summary>Filters'));}
 for(const file of ['current.js','comparison-view.js']){const code=fs.readFileSync('app/dashboard/opportunity_static/current/'+file,'utf8');assert(code.includes('retainedPrices.refresh(notice)'));assert(code.includes('retainedPrices.close()'));assert(code.includes('retainedPrices.complete('));}
 // All three actual controllers request the additive route while their strict
 // complete endpoint refuses pending financial output.
 const url=s=>'data:text/javascript;base64,'+Buffer.from(s).toString('base64');
 const imports={"'./current-client.js'":url(source),"'./comparison-board.js'":url(fs.readFileSync('app/dashboard/opportunity_static/current/comparison-board.js','utf8')),"'./selected-details.js'":url(fs.readFileSync('app/dashboard/opportunity_static/current/selected-details.js','utf8'))};
 const originals={fetch:global.fetch,setTimeout:global.setTimeout,clearTimeout:global.clearTimeout,setInterval:global.setInterval};
 global.setTimeout=function(...args){assert.equal(this,globalThis,'browser timer receiver');return timerOptions.setTimer(...args);};global.clearTimeout=function(...args){assert.equal(this,globalThis,'browser timer receiver');return timerOptions.clearTimer(...args);};global.setInterval=()=>0;
 global.matchMedia=()=>({matches:false,addEventListener:()=>{}});global.EventSource=class{constructor(){global.lastRetainedStream=this;}close(){}};
 for(const view of ['odds','ev','arbs']){
  document.body=new Element('body');document.body.dataset.view=view;document.addEventListener=()=>{};
  for(const id of ['filters','league','market','period','venue','search','results','basis','sort','freshness','rankings','board','details','flow','resort','limits','test-notice','announcement','settings','count','size-note','retained-prices']){const n=new Element(id==='filters'?'form':'div');n.id=id;document.body.append(n);}
  document.getElementById('period').value='full_game';const events={};global.window={addEventListener:(name,fn)=>events[name]=fn,scrollBy:()=>{}};
  const routes=[];global.fetch=async raw=>{const u=new URL(raw,'http://authored.invalid');routes.push(u.pathname);if(u.pathname==='/api/current/prices'){const v=fixture();v.settings_generation=Number(u.searchParams.get('settings_generation'));return new Response(JSON.stringify(v));}if(view==='odds'&&u.pathname==='/api/current')return{ok:true,json:async()=>({schema:'predict-current-1',runtime_id:'retained-loading:placeholder',state_revision:1,mode:'synthetic',state:'unavailable',source_status:{},events:[],estimate_policy:policy,clock_at:at})};return{ok:false,json:async()=>({reason:'temporal_pending'})};};
  let controller=fs.readFileSync('app/dashboard/opportunity_static/current/'+(view==='odds'?'current.js':'comparison-view.js'),'utf8');for(const [name,path]of Object.entries(imports))controller=controller.replace(name,JSON.stringify(path));
  await import(url(controller+'\n// retained controller '+view));await settle();assert(routes.includes('/api/current/prices'));
  const rawRoot=document.getElementById('retained-prices');assert(rawRoot.textContent.includes('0.36'),view+' shows originals despite strict financial refusal');assert(rawRoot.textContent.includes('Estimates remain withheld'));assert(!document.getElementById(view==='odds'?'board':'rankings').textContent.includes('+$'));
  events.pagehide();assert.equal(timers.size,0,view+' closes its bootstrap reader and polling on handback');
 }
 Object.assign(global,originals);
 console.log('PASS: retained original prices, unknown progress, native units/clocks, identity/count refusals, settings/runtime/Stop delayed bodies, focus, and exact admission gates');
})().catch(error=>{console.error(error);process.exitCode=1;});
