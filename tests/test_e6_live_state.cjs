/* Offline UI-state check. Fake DOM/HTTP only; never invokes collection. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map();const element=id=>{if(!elements.has(id))elements.set(id,{value:'',hidden:false,textContent:'',innerHTML:'',disabled:false,setAttribute(){}});return elements.get(id);};
let pendingPost;
const idle={state:'idle',active:false,start_available:false,saved:[],view:null};
const context=vm.createContext({document:{getElementById:element,querySelectorAll:()=>[]},location:{search:''},history:{replaceState(){}},URLSearchParams,AbortSignal,setInterval(){},fetch:async(url,options)=>{
 if(options?.method==='POST')return new Promise(resolve=>{pendingPost=()=>resolve({ok:true,json:async()=>idle});});
 return {ok:true,json:async()=>idle};
}});
for(const file of ['app/dashboard/e5_static/state.js','app/dashboard/e6_real_static/state.js'])vm.runInContext(fs.readFileSync(file,'utf8'),context);
vm.runInContext(fs.readFileSync('app/dashboard/e6_real_static/watch.js','utf8').split('function render()')[0],context);
vm.runInContext(fs.readFileSync('app/dashboard/e6_live_static/watch.js','utf8'),context);
(async()=>{
 await new Promise(setImmediate);
 const stop=vm.runInContext("action('/api/stop')",context);
 assert.equal(element('owner-state').textContent,'stopping');assert.equal(element('stop').disabled,true);pendingPost();await stop;
 vm.runInContext("data={live:true,timeline:[{cards:[{venue:'kalshi',book:{received_at:'receipt'},connection:'connected'}]}]};renderWatch=()=>{};",context);
 const interrupt=vm.runInContext("action('/api/interrupt')",context);
 assert.equal(vm.runInContext('data.timeline[0].cards[0].book',context),null);
 assert.equal(vm.runInContext('data.timeline[0].cards[0].last_receipt',context),'receipt');
 pendingPost();await interrupt;
 vm.runInContext("selection={at:'current',venue:'polymarket_us'};request=async()=>({session:'saved',hash:'hash',timeline:[{id:'final'}]});",context);
 await vm.runInContext("loadSaved('saved')",context);
 assert.equal(vm.runInContext('selection.venue',context),'polymarket_us');
 assert.equal(vm.runInContext('selection.at',context),'final');
 console.log('PASS: immediate stopping, immediate controlled-invalidation quote hiding, stable venue on saved transition; no provider requests');
})().catch(e=>{console.error(e);process.exitCode=1;});
