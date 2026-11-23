// Focused controller evidence: retired Live settings cannot trigger polling or overwrite history.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {Element}=require('./ev07_dom.cjs');
Element.prototype.prepend=function(item){this.insertBefore(item,this.children[0]);};
Element.prototype.reportValidity=()=>true;
const board=new Element('div');board.className='board-info';document.body.append(board);
document.querySelector=selector=>document.body.querySelector(selector);
const recorded={mode:'live',requested_mode:'live',effective_mode:'monitor',revision:7,
 settings:{monitor_interval_seconds:1800,monitor_phase_seconds:1200,monitor_horizon_seconds:86400,live_interval_seconds:90,live_window_seconds:7200,inactivity_seconds:600},
 runs:{live:{state:'complete',completed_at:'2026-11-22T12:00:00Z'}},next_monitor_at:'2026-11-22T12:20:00Z',
 acquisition_policy:{id:'first_observed_tminus10',data_type:'monitor',live_polling:false,separate_saved_game_refresh:false}};
const before=structuredClone(recorded),requests=[],timers=[],storage=new Map([['predict-owner-mode-controls-v1','1']]);
const context={document,Map,Number,String,Date,JSON,Math,Error,AbortController,
 sessionStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
 setTimeout,clearTimeout,setInterval:callback=>{timers.push(callback);return timers.length;},
 bindDialogClose:(button,dialog)=>{button.onclick=()=>{dialog.open=false;};},
 fetch:async(url,options)=>{requests.push({url,options});return {ok:true,status:200,json:async()=>structuredClone({...recorded,revision:options.method==='PATCH'?8:7})};}};
const source=fs.readFileSync('app/dashboard/opportunity_static/current/mode-settings.js','utf8').replace(/^import .*;\n/,'').replace('export function createModeSettings','function createModeSettings');
vm.runInNewContext(source+'\nglobalThis.controller=createModeSettings();',context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 await tick();
 const dialog=document.getElementById('mode-settings'),form=document.getElementById('mode-settings-form'),open=document.getElementById('mode-settings-open');
 assert.equal(open.textContent,'Settings');assert.equal(open.dataset.mode,'monitor');
 assert(dialog.textContent.includes('24/7 discovery · starts at :20 and :50 each hour'));
 const note=document.getElementById('mode-acquisition-policy').textContent;
 assert(note.includes('T−10'));assert(note.includes('No separate saved-game refreshes or Live polling'));
 assert(note.includes('return and bill saved games'));
 assert(dialog.textContent.includes('Historical Live: complete'));
 const labels=form.querySelectorAll('input,select').map(item=>item.attributes['aria-label']||'');
 assert(!labels.some(label=>/Live|inactivity/.test(label)));
 assert(!dialog.querySelectorAll('input').some(item=>item.attributes.role==='switch'));
 assert(!requests.some(item=>item.url.endsWith('/activity')));
 form.onsubmit({preventDefault(){}});await tick();
 const saved=requests.find(item=>item.options.method==='PATCH');assert(saved);
 assert.deepEqual(JSON.parse(saved.options.body),{settings:{monitor_interval_seconds:1800,monitor_phase_seconds:1200,monitor_horizon_seconds:86400}});
 assert.deepEqual(recorded,before,'Controller must preserve recorded Live values');
 assert.equal(timers.length,1);
 await timers[0]();
 assert(requests.at(-1).url.endsWith('mode_status=1'));
 assert(requests.every(item=>item.url==='/api/admin/activity-mode'||item.url==='/api/pregame?mode_status=1'));
 console.log('Checkpoint settings passed: active Monitor feed, :20/:50 and T−10 copy, billing caveat, retired Live controls, preserved saved values and passive polling.');
})().catch(error=>{console.error(error);process.exitCode=1;});
