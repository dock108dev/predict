// Exercise the real workspace controller with stored inputs and read failures.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {Element}=require('./ev07_dom.cjs');
const html=fs.readFileSync('app/dashboard/opportunity_static/current/research.html','utf8');
for(const match of html.matchAll(/id="([^"]+)"/g)){const value=new Element('div');value.id=match[1];document.body.append(value);}
Element.prototype.showModal=function(){this.open=true;};
Element.prototype.close=function(){this.open=false;this.onclose?.();};
const $=id=>document.getElementById(id),pending=[];
const downloads=[];
const context={document,URLSearchParams,Blob,URL:{createObjectURL:blob=>{downloads.push(blob);return 'blob:captured-record';},revokeObjectURL(){}},Date,JSON,Math,Number,String,Error,
 window:{addEventListener(){}},history:{replaceState(){}},location:{search:''},
 fetch:(url,options)=>new Promise(resolve=>pending.push({url,options,resolve}))};
vm.runInNewContext(fs.readFileSync('app/dashboard/opportunity_static/current/research.js','utf8'),context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const reply=async(value,ok=true)=>{pending.shift().resolve({ok,status:ok?200:503,json:async()=>value});await tick();};
const record=(status,ev)=>({id:'sgo:'+status,revision:'revision-'+status,kind:'sgo',title:'Away at Home',sport:'NBA',family:'moneyline',period:'full_game',provider:'sportsgameodds',original_bookmaker_id:status==='unavailable'?'polymarket':'prophetx',represented_venue:status==='unavailable'?'polymarket_us':'prophetx',venue_equivalence:status==='unavailable'?'unestablished':'provider_identity_only',event_id:'source-event',source_market_id:'home-winner',outcome:'home',line:null,price:'+150',price_units:'american_odds',available:true,identity:{mapping_status:'source_local',event_id:null,contract_id:null,settlement:'unverified'},times:{source_at:null,received_at:'2026-11-22T20:00:00Z'},calculation:{status,net_ev_percent:ev,reason:ev===null?'fee_unknown':null,freshness:'not_established'}});
const page={token:'captured',total:4,counts:{source_events:1},offset:0,next_offset:null,captured_at:'2026-11-22T20:00:00Z',population:'Every received status',rows:[record('positive','5'),record('negative','-5'),record('zero','0'),record('unavailable',null)]};
(async()=>{
 assert.equal($('catalog').attributes['aria-busy'],'true');
 assert($('refresh').disabled);
 await reply(page);
 assert.equal($('catalog-rows').children.length,4);
 const text=$('catalog-rows').textContent;
 assert(text.includes('positive')&&text.includes('negative')&&text.includes('zero')&&text.includes('unavailable'));
 assert(text.includes('fee_unknown'));
 assert(text.includes('Equivalence: unestablished'));
 assert(text.includes('Source: Unknown'));
 assert(!text.includes('Net EV: null%'));
 $('catalog-rows').children[3].querySelector('button').onclick();
 assert($('input-detail').open);
 assert(pending[0].url.includes('token=captured')&&pending[0].url.includes('revision=revision-unavailable'));
 const detail={...page.rows[3],captured_at:page.captured_at,source_input:{price_american:'+150'},contract:null,event:null,calculation_payload:null,fee_input:null,price_payload:null,original_response:{state:'not_recorded',reason:'Historical original bytes absent'},reproduction:'Exact inputs'};
 await reply(detail);
 const inspected=$('input-content').textContent;
 for(const evidence of ['1. Received source input','2. Identity & settlement','3. Probability inputs & policy','4. Fees, quantity & cashflows','5. Calculation result','6. Original-response retention & reproduction','fee_unknown','Historical original bytes absent'])assert(inspected.includes(evidence),evidence);
 const exported=$('input-content').querySelector('a');
 assert.equal(exported.href,'blob:captured-record');
 assert.equal(JSON.parse(await downloads[0].text()).revision,'revision-unavailable');
 $('close-detail').onclick();assert(!$('input-detail').open);
 $('refresh').onclick();await reply({message:'SQL unavailable'},false);
 assert($('catalog-status').textContent.includes('last-known'));
 assert.equal($('catalog-rows').children.length,4);
 assert(pending.every(item=>!item.options||item.options.method==='DELETE'));
 console.log('Research workspace passed: every EV sign, nulls, source identity, captured inspection/export and stale-read preservation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
