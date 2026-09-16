const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('app/dashboard/opportunity_static/dashboard.js','utf8');
const elements=new Map();
const element=id=>{if(!elements.has(id))elements.set(id,{textContent:'old',replaceChildren(){this.cleared=true;}});return elements.get(id);};
const context={busy:false,pendingRefresh:false,inputs:()=>new URLSearchParams(),query:new URLSearchParams(),
 localStorage:{getItem:()=>null},fetch:async()=>{throw Error('offline');},$:element};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('async function refresh('),source.indexOf('for(const key of fields)$(key).onchange')),context);
(async()=>{await context.refresh();assert(element('rows').cleared);assert.equal(element('mode').textContent,'Connection or data unavailable');assert.equal(context.busy,false);console.log('PASS: failed refresh clears previous results and current label');})().catch(e=>{console.error(e);process.exitCode=1;});
