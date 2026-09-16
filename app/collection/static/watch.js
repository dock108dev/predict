'use strict';
const $=id=>document.getElementById(id);
let saved=null, busy=false;
const bookmark=JSON.parse(localStorage.getItem('e6-selection')||'{}');
$('venue').value=bookmark.venue||'kalshi';
$('venue').onchange=()=>localStorage.setItem('e6-selection',JSON.stringify({venue:$('venue').value,session:$('saved').value}));
function renderBooks(books){$('books').replaceChildren();for(const b of books||[]){const p=document.createElement('p');p.textContent=`${b.venue} · ask $${b.ask} · simulated receipt ${b.at}`;$('books').append(p);}}
function show(snapshot){
 if(saved)renderBooks(snapshot?.books);
 const reference=snapshot?.references?.at(-1);
 $('reference').textContent=reference?`Synthetic Pinnacle-shaped reference · ${reference.at} · decimal odds ${reference.odds?reference.odds.join(' / '):'unavailable'} · ${reference.included?'included in conditional estimate':'excluded latest receipt'} · provider read ${reference.provider_read||'unknown'} · bookmaker change time unknown`:'Current reference calculation unavailable; no earlier valid snapshot is substituted.';
 $('economics').textContent=snapshot?`Our price: ${snapshot.probability===null?'unavailable':snapshot.probability+' conditional probability'} · ${snapshot.status}`:'Current economics unavailable: awaiting a fresh, healthy, persisted calculation.';
 $('details').textContent=snapshot?JSON.stringify(snapshot,null,2):'No eligible current calculation.';
 if(snapshot) for(const signal of snapshot.signals){const p=document.createElement('p');p.textContent=`${signal.signal_class==='arb'?'Arbitrage · worst-case net':'Mispricing · expected net'}: ${signal.net_total_usd===null?'Unavailable':'$'+signal.net_total_usd} · ${signal.status} · ${signal.sizing_basis.quantity} contracts${signal.signal_class==='arb'?' per leg':''}`;$('economics').append(p);}
}
async function refresh(){
 if(busy)return;
 try{
  const response=await fetch('/api/status');const s=await response.json();
  $('status').textContent=`${saved?'Viewing saved synthetic history. Actual session: ':''}${s.state}${s.recovered?.length?' · prior session interrupted; collection has not resumed':''}${s.reason?' · '+s.reason:''}`;
  $('counts').textContent=s.id?`Delivered records: ${s.delivered} · Persisted: ${s.persisted} · Awaiting primary persistence: ${s.journal_only} · Calculations: ${s.calculations}`:'Idle. Start explicitly to collect.';
  $('start').disabled=['running','stopping'].includes(s.state);$('stop').disabled=!['running','stopping'].includes(s.state);
  $('health').replaceChildren();for(const [source,h] of Object.entries(s.health||{})){const p=document.createElement('p');p.textContent=`${source}: ${h.state} · ${h.reason||''}`;$('health').append(p);}
  if(!saved)renderBooks(s.books);
  else $('health').textContent='Saved synthetic history. Source health is historical; no current eligibility is claimed.';
  const selected=$('saved').value||bookmark.session;const list=s.saved||[];
  if(JSON.stringify(list)!==$('saved').dataset.list){$('saved').replaceChildren(new Option('Choose a saved session',''),...list.map(x=>new Option(x,x)));$('saved').dataset.list=JSON.stringify(list);if(list.includes(selected))$('saved').value=selected;}
  if(!saved)show(s.view);
 }catch(e){$('error').textContent=e.message;}
}
async function action(url,body){busy=true;$('error').textContent='';try{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(!r.ok)throw Error(await r.text());}catch(e){$('error').textContent=e.message;}finally{busy=false;await refresh();}}
$('start').onclick=()=>{saved=null;return action('/api/start',{seconds:Number($('duration').value)});};
$('stop').onclick=()=>{show(null);$('status').textContent='Stopping: waiting for producers, calculation and persistence…';return action('/api/stop',{});};
$('reopen').onclick=async()=>{if(!$('saved').value)return;busy=true;try{$('coverage').textContent='Verifying saved dependencies and exact replay…';const r=await fetch('/api/saved/'+$('saved').value);if(!r.ok)throw Error(await r.text());saved=await r.json();$('coverage').textContent=`Synthetic · ${saved.state} · ${saved.counts.prediction} prediction receipts · ${saved.counts.reference} reference receipts · ${saved.counts.reference_gaps} reference gap/stop records. ${saved.coverage}`;$('cutoff').replaceChildren(...saved.snapshots.map((x,i)=>new Option(x.cutoff,i)));$('cutoff').value=String(saved.snapshots.length-1);show(saved.snapshots.at(-1));$('venue').onchange();}catch(e){saved=null;$('error').textContent=e.message;}finally{busy=false;refresh();}};
$('cutoff').onchange=()=>show(saved?.snapshots[Number($('cutoff').value)]);
$('current').onclick=()=>{saved=null;$('coverage').textContent='';refresh();};
refresh();setInterval(refresh,1000);
