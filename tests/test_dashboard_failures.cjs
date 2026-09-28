const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/dashboard/opportunity_static/dashboard.js','utf8');
const elements=new Map();
const element=id=>{if(!elements.has(id))elements.set(id,{textContent:'old',replaceChildren(){this.cleared=true;}});return elements.get(id);};
const context={busy:false,pendingRefresh:false,followSession:null,view:"feed",inputs:()=>new URLSearchParams(),query:new URLSearchParams(),
 localStorage:{getItem:()=>null},fetch:async()=>{throw Error('offline');},$:element};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('async function refresh('),source.indexOf('for(const key of fields)$(key).onchange')),context);
(async()=>{await context.refresh();assert(element('rows').cleared);assert.equal(element('mode').textContent,'Connection or data unavailable');assert.equal(context.busy,false);context.fetch=async()=>({ok:false,status:422,json:async()=>({error:'Invalid quantity'})});await context.refresh();assert.equal(element('mode').textContent,'Inputs need attention');assert(element('error').textContent.includes('Saved scans and settings'));assert(!element('scan-state').textContent.includes('reconnect'));console.log('PASS: failed refresh clears old results; invalid inputs receive settings guidance');})().catch(e=>{console.error(e);process.exitCode=1;});

// Browser Start follows the owner's declared contract instead of operating-mode guesses.
vm.runInContext(source.slice(source.indexOf('function startOptions('),source.indexOf('async function command(')),context);
element('duration').value='90';element('max-games').value='3';
context.last={status:{start_controls:['duration']}};
assert.equal(JSON.stringify(context.startOptions()),'{"duration":90}');
context.last={status:{start_controls:['duration','max_games']}};
assert.equal(JSON.stringify(context.startOptions()),'{"duration":90,"max_games":3}');
context.last=null;assert.throws(()=>context.startOptions(),/Refresh/);
context.last={status:{start_controls:['unsupported']}};assert.throws(()=>context.startOptions(),/Unsupported/);
