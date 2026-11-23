// Exercise the real Settings controller's confirmed fee setting and failure path.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {Element}=require('./ev07_dom.cjs');
for(const match of fs.readFileSync('app/dashboard/opportunity_static/current/settings.html','utf8').matchAll(/id="([^"]+)"/g)){const item=new Element('div');item.id=match[1];item.checked=false;document.body.append(item);}
const $=id=>document.getElementById(id),calls=[],controls={};
for(const action of ['stop','recover']){controls[action]=new Element('button');controls[action].dataset.control=action;document.body.append(controls[action]);}
document.querySelector=selector=>selector.includes('"stop"')?controls.stop:selector.includes('"recover"')?controls.recover:null;
document.querySelectorAll=selector=>selector==='[data-control]'?Object.values(controls):document.body.querySelectorAll(selector);
document.addEventListener=()=>{};
const context={document,AbortSignal,Date,JSON,Number,String,Error,Set,console,setInterval(){},Intl:{DateTimeFormat:Intl.DateTimeFormat,supportedValuesOf:()=>['UTC']},Option:function(text,value){const item=new Element('option');item.textContent=text;item.value=value;return item;},
 accountingFacts:()=>[],accountingEvidence:()=>({sportsgameodds:{object_holds:[],interrupted_scans:[]},the_odds_api:{}}),applyTheme(){},readPreference:()=>'',savePreference(){},timezone:()=> 'UTC',
 fetch:(url,options={})=>new Promise(resolve=>calls.push({url,options,resolve,settled:false}))};
vm.runInNewContext(fs.readFileSync('app/dashboard/opportunity_static/current/settings.js','utf8').replace(/^import .*;\n/gm,''),context,{filename:'settings.js'});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function reply(path,value,status=200){const call=calls.find(call=>!call.settled&&call.url===path);assert(call,'Expected request '+path);call.settled=true;call.resolve({ok:status>=200&&status<300,json:async()=>value});await tick();return call;}
const mode=(enabled,revision)=>({enabled,revision,version:'fixture-fee-mode-1',assumption:enabled?'existing_fee_models':'zero_fees'});
(async()=>{
 assert.equal($('include-fees').checked,false);
 assert.equal($('include-fees').disabled,true,'cannot change an unconfirmed setting');
 await reply('/api/admin/status',{config:{enabled:true,aggregate_provider:'sportsgameodds'},data_runtime:{healthy:true,paused_sources:[]},dispatch_enabled:true,sources:[]});
 await reply('/api/admin/activity-mode',{settings:{monitor_interval_seconds:1800,monitor_phase_seconds:1200,monitor_horizon_seconds:86400}});
 await reply('/api/workspace/status',{storage:{},reference_scope:{books:[]},fee_mode:mode(false,'off')});
 assert.equal($('include-fees').disabled,false);
 assert.equal($('include-fees').checked,false);assert.match($('fee-mode-status').textContent,/zero fees/i);
 $('include-fees').checked=true;$('include-fees').onchange();
 assert.equal($('include-fees').disabled,true,'one setting write at a time');
 const mutation=calls.find(call=>call.url==='/api/workspace/fees');
 assert.equal(mutation.options.method,'PATCH');assert.deepEqual(JSON.parse(mutation.options.body),{enabled:true});
 await reply('/api/workspace/fees',{...mode(true,'on'),queued_events:2,provider_requests:0});
 assert.equal($('include-fees').checked,true);assert.equal($('include-fees').disabled,false);assert.match($('fee-mode-status').textContent,/included|existing/i);
 $('include-fees').checked=false;$('include-fees').onchange();await reply('/api/workspace/fees',{error:'Fixture storage is unavailable'},503);
 assert.equal($('include-fees').checked,true,'failed save restores the last confirmed persisted setting');
 assert.match($('fee-mode-status').textContent,/could not|not confirmed/i);
 assert.deepEqual(calls.filter(call=>call.options.method).map(call=>call.url),['/api/workspace/fees','/api/workspace/fees']);
 console.log('Settings fee switch passed: confirmed default off, protected boolean write, saved on, failed save retains confirmation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
