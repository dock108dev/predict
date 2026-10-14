'use strict';
// Independent delayed-body/newer-notice regression; simulated DOM only.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {Element}=require('./ev07_dom.cjs');
const url=source=>'data:text/javascript;base64,'+Buffer.from(source).toString('base64');
const board=url(fs.readFileSync('app/dashboard/opportunity_static/current/comparison-board.js','utf8'));
const client=url(fs.readFileSync('app/dashboard/opportunity_static/current/current-client.js','utf8'));
const detail=url(fs.readFileSync('app/dashboard/opportunity_static/current/selected-details.js','utf8'));
const code=name=>fs.readFileSync('app/dashboard/opportunity_static/current/'+name,'utf8').replace("'./comparison-board.js'",JSON.stringify(board)).replace("'./current-client.js'",JSON.stringify(client)).replace("'./selected-details.js'",JSON.stringify(detail));
const settle=async()=>{for(let i=0;i<80;i++)await Promise.resolve();};
const $=id=>document.getElementById(id);
function setup(view){document.body=new Element('body');document.body.dataset.view=view;document.addEventListener=()=>{};for(const id of ['filters','league','market','period','venue','search','results','basis','sort','freshness','rankings','board','details','flow','resort','limits','test-notice','announcement','settings','count','size-note']){const n=new Element(id==='filters'?'form':'div');n.id=id;document.body.append(n);}$('results').value='all';$('freshness').value='all';$('period').value='full_game';}
class Stream{constructor(){Stream.last=this;}close(){}}
global.EventSource=Stream;global.window={addEventListener:()=>{},scrollBy:()=>{}};global.matchMedia=()=>({matches:false,addEventListener:()=>{}});global.setInterval=()=>0;Object.defineProperty(global,'crypto',{value:require('node:crypto').webcrypto});
const policy={version:'predict-estimate-policy-2',revision:'policy',capital_ceiling_usd:'1000',buffer_rate:'0.005'};
function quote(revision){const amount=revision===1?'20':revision===2?'40':'80';return {id:'Q',revision,venue:'prophetx',source:{native_side:'YES'},binding:{selection:{group_id:'g'}},original:{value:'2',units:'decimal_odds'},times:{source_at:'2026-10-11T12:00:00Z'},display:{american:'+100'},age_seconds:0,calculations:{funded_estimate:{model_available:true,ranking_eligible:true,conditioning:'modeled_complete',buffered_profit_usd:amount,buffered_return_percent:amount,display:{buffered_profit_usd:'+'+amount+'.00',buffered_return_percent:'+'+amount+'.00'},deployed_capital_usd:'1000',size_status:'size_unverified'}}};}
function value(view,revision,generation){const q=quote(revision),base={runtime_id:'runtime',state_revision:revision,estimate_policy:policy,owner_estimate_policy:policy,request_generation:generation,mode:'synthetic',source_status:{},clock_at:'2026-10-11T12:00:00Z'};return view==='ev'?{...base,schema:'comparison-metrics-1',rows:[{id:'Q',quote_revision:revision,title:'Game',selection:'Team',market:'winner',period:'full_game',venue:'prophetx',quote:q,funded_estimate:q.calculations.funded_estimate}],funded_pairs:[]}:{...base,schema:'predict-current-1',events:[{id:'e',title:'Game',league:'NFL',start_at:'2026-10-12T12:00:00Z',groups:[{id:'g',market:'winner',period:'full_game',period_boundary:'Overtime',outcomes:[{id:'o',participant:'Team',predicate:'win',label:'Team',signed_line:null,quotes:{prophetx:q},alternatives:{}}]}]}]};}
(async()=>{
 for(const view of ['ev','odds']){
  setup(view);const waiting=[];let delayed=false;
  global.fetch=async raw=>{const params=Object.fromEntries(new URL(raw,'http://authored.invalid').searchParams);if(delayed)return new Promise(resolve=>waiting.push({resolve,params}));return {ok:true,json:async()=>value(view,1,params.request_generation)};};
  await import(url(code(view==='ev'?'comparison-view.js':'current.js')+'\n// EV08 '+view));await settle();
  delayed=true;const notice=revision=>Stream.last.onmessage({data:JSON.stringify({schema:'predict-current-1',runtime_id:'runtime',state_revision:revision})});
  notice(2);await settle();const old=waiting.shift();assert(old,'first read queued');notice(3);await settle();
  old.resolve({ok:true,json:async()=>value(view,2,old.params.request_generation)});await settle();await new Promise(resolve=>setTimeout(resolve,600));await settle();
  const root=$(view==='ev'?'rankings':'board');assert(!root.textContent.includes('+$40.00'),'a delayed body cannot republish values after a newer input notice: '+view);
  const current=waiting.shift();assert(current,'latest read queued');current.resolve({ok:true,json:async()=>value(view,3,current.params.request_generation)});await settle();
  assert(root.textContent.includes('+$80.00'),'latest revision remains available: '+view);
 }
 for(const view of ['ev','odds']){
  setup(view);const waiting=[];let delayed=false;
  global.fetch=async raw=>{const params=Object.fromEntries(new URL(raw,'http://authored.invalid').searchParams);if(delayed)return new Promise(resolve=>waiting.push({resolve,params}));return {ok:true,json:async()=>value(view,1,params.request_generation)};};
  await import(url(code(view==='ev'?'comparison-view.js':'current.js')+'\n// temporal same revision '+view));await settle();
  delayed=true;
  Stream.last.onmessage({data:JSON.stringify({schema:'predict-current-1',runtime_id:'runtime',state_revision:1,calculation_epoch:1,eligibility:'pending'})});await settle();
  const old=waiting.shift();assert(old,'pending notice starts a validating read');
  old.resolve({ok:true,json:async()=>value(view,1,old.params.request_generation)});await settle();
  const root=$(view==='ev'?'rankings':'board');assert(!root.textContent.includes('+$20.00'),'same-revision pending notice cannot restore revoked estimates: '+view);
  Stream.last.onmessage({data:JSON.stringify({schema:'predict-current-1',runtime_id:'runtime',state_revision:2,calculation_epoch:2,eligibility:'ready'})});await settle();
  const ready=waiting.shift();assert(ready);ready.resolve({ok:true,json:async()=>value(view,2,ready.params.request_generation)});await settle();
  assert(root.textContent.includes('+$40.00'),'ready committed successor restores estimates: '+view);
 }
 for(const view of ['ev','odds']){
  setup(view);let blocked=false,aborted=0;const signals=[];
  global.fetch=async(raw,options={})=>{
   const u=new URL(raw,'http://authored.invalid'),params=Object.fromEntries(u.searchParams);
   if(blocked&&u.pathname==='/api/comparison'&&params.ceiling==='500')return new Promise((resolve,reject)=>{assert(options.signal,'settings requests carry a real AbortSignal');signals.push(options.signal);options.signal.addEventListener('abort',()=>{aborted++;reject(Object.assign(new Error('authored disconnect'),{name:'AbortError'}));},{once:true});});
   const q=quote(1),base=value(view,1,params.request_generation),effective={...policy,capital_ceiling_usd:params.ceiling||'1000',buffer_rate:params.buffer||'0.005'};
   const result=u.pathname==='/api/current/details'?{...base,event:{title:'Game'},outcome:{label:'Team'},quote:q,estimate_policy:effective}:u.pathname==='/api/comparison'?{...value('ev',1,params.request_generation),estimate_policy:effective}:base;
   return{ok:true,json:async()=>result};
  };
  await import(url(code(view==='ev'?'comparison-view.js':'current.js')+'\n// EV08 real abort '+view));await settle();
  if(view==='ev')$('inspect-Q').onclick();else $('board').querySelector('[data-quote-id]').onclick();await settle();
  blocked=true;$('comparison-ceiling').value='500';$('comparison-buffer').value='0.01';$('details').querySelector('form').onsubmit({preventDefault(){}});await settle();assert.equal(signals.length,1,view+' has one blocked settings read');
  $('details').querySelectorAll('button').find(n=>n.textContent==='Restore $1,000 / 0.5%').onclick();await settle();
  assert.equal(aborted,1,view+' Restore aborts underlying fetch');assert(signals[0].aborted);assert(!$('details').textContent.includes('authored disconnect'));assert(!$(view==='ev'?'rankings':'board').textContent.includes('Recalculating requested settings'));
 }
 // Same-revision changes contain no economic rows. Restore must obtain the
 // server defaults from a complete snapshot rather than reuse locally withheld
 // graphs whose events were absent from the incremental response.
 setup('odds');const paths=[];
 global.fetch=async raw=>{
  const u=new URL(raw,'http://authored.invalid');paths.push(u.pathname);
  const full=value('odds',1);
  const result=u.pathname==='/api/current/changes'?{schema:'predict-current-changes-1',base_revision:1,snapshot:{...full,events:undefined},events:[],removed_events:[]}:full;
  return{ok:true,json:async()=>result};
 };
 await import(url(code('current.js')+'\n// Restore unchanged server revision'));await settle();
 const before=paths.filter(p=>p==='/api/current').length;
 $('settings').querySelectorAll('button').find(n=>n.textContent==='Restore $1,000 / 0.5%').onclick();await settle();
 assert.equal(paths.filter(p=>p==='/api/current').length,before+1,'Restore reads a complete authoritative default snapshot');
 assert($('board').textContent.includes('+$20.00'),'Restore repaints exact defaults with an unchanged server revision');
 assert(!$('board').textContent.includes('Restoring server defaults'),'withheld placeholders cannot survive a successful Restore');
 console.log('PASS: newer notices withhold delayed bodies; EV/Odds Restore aborts the real obsolete settings fetch and adopts defaults');
})().catch(error=>{console.error(error);process.exitCode=1;});
