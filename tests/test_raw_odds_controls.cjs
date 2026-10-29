// Exercise the authored controller with pending/successful/failed local reads.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {Element}=require('./ev07_dom.cjs');
const html=fs.readFileSync('app/dashboard/opportunity_static/current/raw-odds.html','utf8');
for(const match of html.matchAll(/id="([^"]+)"/g)){const el=new Element('div');el.id=match[1];document.body.append(el);}
const el=id=>document.getElementById(id);
const pending=[];
const context={document,URLSearchParams,Map,Date,JSON,Math,Number,String,Error,
 window:{addEventListener(){}},location:{search:'?sport=NFL'},history:{replaceState(){}},
 Option:function(label,value){const n=new Element('option');n.value=value;n.textContent=label;return n;},
 requestAnimationFrame:fn=>fn(),setInterval(){},fetch:url=>new Promise(resolve=>pending.push({url,resolve}))};
let source=fs.readFileSync('app/dashboard/opportunity_static/current/raw-odds.js','utf8').replace(/^import .*\n/,'');
vm.runInNewContext(source,context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const page=(offset=0)=>({token:'synthetic',total_books:100,offset,next_offset:offset===0?50:null,books:[]});
const reply=async(value,ok=true)=>{pending.shift().resolve({ok,json:async()=>value});await tick();};
(async()=>{
 assert.equal(el('content').attributes['aria-busy'],'true');
 assert(el('next').disabled&&el('refresh').disabled);
 await reply({error:'offline'},false);
 assert(el('status').textContent.includes('could not load'));
 assert(!el('status').textContent.includes('Displayed values'));
 assert.equal(el('content').attributes['aria-busy'],'false');
 el('retry').onclick();await reply(page());
 assert(!el('next').disabled);assert(el('previous').disabled);
 el('next').onclick();el('next').onclick();
 assert.equal(pending.length,1);assert(pending[0].url.includes('offset=50'));
 assert(el('previous').disabled&&el('next').disabled);
 await reply(page(50));assert(!el('previous').disabled);assert(el('next').disabled);
 el('refresh').onclick();await reply({error:'offline'},false);
 assert(el('status').textContent.includes('last-known'));
 el('clear-filters').onclick();assert(!pending[0].url.includes('sport='));assert(pending[0].url.includes('offset=0'));
 await reply(page());assert(el('clear-filters').disabled);
 const book=context.renderBook({id:'book',title:'Away at Home',venue:'kalshi',sport:'NFL',family:'moneyline',period:'full_game',kind:'native',status:'synchronized',event_id:'event',observations:[{id:'yes',label:'Home',native_side:'yes',side:'asks',price:'0.5',units:'USD'}]});
 assert.equal(book.querySelector('button').attributes['aria-label'],'Original inputs for Away at Home, Kalshi, Home, yes asks');
 assert(!html.includes('id="sort-setting"'));assert(!html.includes('data-filter='));
 assert(html.includes('aria-current="page"'));
 assert(html.includes('Previous page')&&html.includes('Next page'));
 console.log('Raw Odds controls passed: loading, initial failure, stale values, navigation ownership and clear filters.');
})().catch(error=>{console.error(error);process.exitCode=1;});
