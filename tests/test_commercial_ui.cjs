const assert=require('node:assert/strict');
const ui=require('../app/dashboard/opportunity_static/decision.js');
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const html=ui.summary({conclusion:'Net unavailable',settlement:['48 hours versus two weeks'],costs:['<img>'],freshness:['stale'],quantity:['unknown'],net_reason:['Private charges unknown']},esc);
assert(html.includes('48 hours versus two weeks'));assert(html.includes('&lt;img&gt;'));assert(!html.includes('<img>'));assert(html.includes('Private charges unknown'));
const controls=ui.controls({session:'s~g',hash:'s',cutoff:'3-exact',contract:'<c>',legs:[]},esc);
assert(controls.includes('3-exact'));assert(controls.includes('&lt;c&gt;'));assert(controls.includes('Spending ceiling'));
const report={original_outputs:'Derived analysis',at:'cutoff',sizes:[{requested:'.5',limitation:'Fractional execution unsupported',fractional_entries:[{venue:'US',contract:'c',entry:{notional:'.25',reason:'fractional execution unverified',upper:null}}],acquisitions:[]}],search:'Explicit sizes only',best:null};
const rendered=ui.sizeHtml(report,esc);assert(rendered.includes('raw acquisition $.25'));assert(rendered.includes('No supported conditional result'));
console.log('PASS: decision and size presentation, exact binding and escaping');

// Signal presentation must expire locally even when polling fails, and saved
// review must never ask for live signals or repeat identical announcements.
const vm=require('node:vm'),fs=require('node:fs');
let assignments=0,fetches=0,expiry;
const nodes=new Map();
const node=id=>{if(!nodes.has(id)){let html='';nodes.set(id,{textContent:'',get innerHTML(){return html},set innerHTML(v){html=v;assignments++;}});}return nodes.get(id);};
const context={window:{},document:{getElementById:node,addEventListener(){}},URLSearchParams,clearTimeout(){},setTimeout(fn){expiry=fn;return 1},fetch:async()=>{fetches++;return {ok:true,json:async()=>({items:[{active:true,session:'s',mode:'synthetic',metric:'raw_gap',title:'<unsafe>',changes:[{value:'.04'}],last:{at:'t'}}],events:[]})}}};
vm.createContext(context);vm.runInContext(fs.readFileSync('app/dashboard/opportunity_static/watchlists.js','utf8'),context);
(async()=>{
 const api=context.window.PredictWatch,payload={live:true,status:{active:true},capture:'s'};
 await api.refresh(payload);assert(node('watch-signals').innerHTML.includes('Simulation'));assert(node('watch-signals').innerHTML.includes('&lt;unsafe&gt;'));
 const count=assignments;await api.refresh(payload);assert.equal(assignments,count);
 expiry();assert(node('watch-signals').textContent.includes('expired'));
 const before=fetches;await api.refresh({live:false,status:{active:false}});assert.equal(fetches,before);assert(node('watch-signals').textContent.includes('Historical review'));
 context.fetch=async()=>{throw Error('disconnected');};await api.refresh(payload);assert(node('watch-signals').textContent.includes('unavailable'));
 let resolve;context.fetch=()=>new Promise(r=>{resolve=r;});
 const pending=api.refresh(payload);api.expire('Stop requested; signals expired');
 resolve({ok:true,json:async()=>({items:[{active:true,session:'s',mode:'synthetic',metric:'raw_gap',title:'late response',changes:[],last:{at:'t'}}],events:[]})});
 await pending;assert(node('watch-signals').textContent.includes('Stop requested'));assert(!node('watch-signals').innerHTML.includes('late response'));
 console.log('PASS: deduplicated announcements, browser expiry, disconnected suppression and historical isolation');
})().catch(e=>{console.error(e);process.exitCode=1;});
