import { capturedCalculation } from "/view/current/raw-result-view.js";
const $=id=>document.getElementById(id);
const venues={kalshi:'Kalshi',polymarket_us:'Polymarket US',novig:'Novig',prophetx:'ProphetX',pinnacle:'Pinnacle · Reference'};
const labels={synchronized:'Synchronized',delayed:'Delayed',last_known:'Last-known',unqualified:'Unqualified',aggregate:'Scheduled refresh'};
let frame=null,offset=0,busy=false,generation=0,selection=null,opener=null,lastRows=new Map();
const timing=[];let lastDelivery=null;
window.rawDisplayTiming=timing;
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function options(id,values){for(const [value,label] of values)$(id).append(new Option(label,value));}
options('league',['NFL','NCAAF','NBA','NCAAB','MLB','NHL','unknown'].map(v=>[v,v]));
options('venue',Object.entries(venues));options('family',[['moneyline','Moneyline / winner'],['spread','Spread'],['total','Total'],['unknown','Unknown']]);
options('period',[['full_game','Full game'],['unknown','Unknown']]);
const saved=new URLSearchParams(location.search);for(const [id,key] of [['league','sport'],['venue','venue'],['family','family'],['period','period'],['game','event_id'],['search','search'],['state','state']])if(saved.has(key))$(id).value=saved.get(key);
function filters(){const q=new URLSearchParams();for(const [id,key] of [['league','sport'],['venue','venue'],['family','family'],['period','period'],['game','event_id'],['search','search'],['state','state']])if($(id).value.trim())q.set(key,$(id).value.trim());return q;}
function readControls(){
 $('content').setAttribute('aria-busy',String(busy));
 $('previous').disabled=busy||!frame||frame.offset===0;
 $('next').disabled=busy||!frame||frame.next_offset===null;
 $('refresh').disabled=busy;$('retry').disabled=busy;
 $('clear-filters').disabled=filters().size===0;
}
function age(at){if(!at||!Number.isFinite(Date.parse(at)))return 'Unknown';const seconds=Math.max(0,(Date.now()-Date.parse(at))/1000);return seconds<60?Math.floor(seconds)+'s':seconds<3600?Math.floor(seconds/60)+'m':Math.floor(seconds/3600)+'h';}
async function get(url){const r=await fetch(url,{cache:'no-store'});const v=await r.json();if(!r.ok)throw Error(v.error||'Local read unavailable');if(url.startsWith('/api/raw/prices'))lastDelivery=new Date().toISOString();return v;}
function renderBook(b){
 const article=node('article',undefined,'raw-book'+(b.reference_only?' raw-reference':''));article.dataset.book=b.id;
 article.append(node('h2',b.title));
 article.append(node('div',`${venues[b.venue]||b.venue} · ${b.sport} · ${b.family} · ${b.period.replaceAll('_',' ')} · ${b.kind==='native'?(labels[b.status]||b.status):b.provenance.refresh_status==='scheduled'?'Scheduled every 15 minutes · source age below':'Last-known · '+b.provenance.refresh_status.replaceAll('_',' ')+' refresh'}`,'raw-meta'));
 article.append(node('div',`Game ${b.event_id} · ${b.source_at?'Source updated '+age(b.source_at)+' ago':'Source time unknown'}`,'raw-meta'));
 for(const o of b.observations){
  const row=node('div',undefined,'raw-row');
  row.append(node('span',`${o.label} · ${o.native_side} · ${o.side}${o.line==null?'':' · '+(o.line_meaning||'line')+' '+o.line}`));
  row.append(node('strong',o.price==null?(o.disposition==='empty'?'Empty':o.representation==='not_independently_supplied_short_bid'?'Not supplied separately':'Unavailable'):String(o.price)));
  row.append(node('span',o.units));
  row.append(node('span',o.disposition==='invalid_price'?'Invalid value':o.quantity?`${o.quantity.value} ${o.quantity.unit}`:'Quantity unknown',o.disposition==='invalid_price'?'raw-unqualified':'raw-state'));
  if(o.representation?.startsWith('derived'))row.append(node('small',o.representation==='derived_short_ask_from_long_bid'?'1 − Long bid':'1 − opposite bid'));
  const button=node('button','Original inputs');button.dataset.observation=o.id;button.setAttribute('aria-label',`Original inputs for ${b.title}, ${venues[b.venue]||b.venue}, ${o.label}, ${o.native_side} ${o.side}`);button.addEventListener('click',()=>openInputs(b,o,button));row.append(button);article.append(row);
 }
 if(!b.observations.length)article.append(node('p','Received book has no outcome values.'));
 return article;
}
function render(v){
 window.rawDisplayPage=v;
 const newSamples=[];const focus=document.activeElement?.dataset.observation;const root=$('content');
 const prior=new Map([...root.children].map(n=>[n.dataset.book,n]));const next=[];
 for(const b of v.books){const signature=JSON.stringify([b.revision,b.status,b.validation,age(b.source_at)]);let el=prior.get(b.id);
  if(!el||el.dataset.signature!==signature){el=renderBook(b);el.dataset.signature=signature;}next.push(el);
  const old=lastRows.get(b.id);if(old&&old!==b.revision){newSamples.push({venue:b.venue,id:b.id,received_at:b.received_at,visible_at:new Date().toISOString(),http_delivered_at:lastDelivery,storage_write_at:b.storage_write_at,receipt_to_dom_seconds:(Date.now()-Date.parse(b.received_at))/1000});}
 }
 lastRows=new Map(v.books.map(b=>[b.id,b.revision]));
 for(let i=0;i<next.length;i++)if(root.children[i]!==next[i])root.insertBefore(next[i],root.children[i]||null);
 while(root.children.length>next.length)root.lastChild.remove();
 if(focus&&document.activeElement===document.body)root.querySelector(`[data-observation="${focus}"]`)?.focus({preventScroll:true});
 requestAnimationFrame(()=>requestAnimationFrame(()=>{for(const sample of newSamples){sample.visible_at=new Date().toISOString();sample.receipt_to_visible_seconds=(Date.now()-Date.parse(sample.received_at))/1000;timing.push(sample);}if(timing.length>2048)timing.splice(0,timing.length-2048);}));
 $('status').textContent=v.total_books?`${v.total_books.toLocaleString()} received books · Calculations update separately`:'No received books match these filters.';
 $('page-number').textContent=v.total_books?`${v.offset+1}–${v.offset+v.books.length} of ${v.total_books.toLocaleString()}`:'0';
 $('previous').disabled=v.offset===0;$('next').disabled=v.next_offset===null;
 if(selection){const b=v.books.find(b=>b.id===selection.book.id);if(b&&b.revision!==selection.book.revision)$('captured-state').textContent='Captured inputs · A newer price has arrived';}
}
async function load(continuation=false){
 if(busy)return;busy=true;readControls();$('status').textContent=frame?'Updating received prices… Displayed values are from the previous read.':'Loading received prices…';const gen=generation;const q=filters();history.replaceState(null,'','/odds'+(q.size?'?'+q:''));q.set('offset',offset);q.set('limit','50');
 if(continuation&&frame)q.set('token',frame.token);else if(frame&&!selection)q.set('release',frame.token);
 try{const v=await get('/api/raw/prices?'+q);if(gen!==generation){fetch('/api/raw/read?token='+v.token,{method:'DELETE',headers:{'Content-Type':'application/json'}});return;}frame=v;render(v);$('retry').hidden=true;$('read-diagnostics').hidden=true;}
 catch(e){if(gen!==generation)return;$('status').textContent=frame?'Prices could not refresh. Displayed values are last-known. Retry to read current prices.':'Prices could not load. Retry to read received prices.';$('retry').hidden=false;$('read-diagnostics').hidden=false;$('read-error').textContent=e.message;}
 finally{busy=false;readControls();if(gen!==generation)load();}
}
function detailQuery(b){return new URLSearchParams({token:selection.token,kind:b.kind,venue:b.venue,sport:b.sport,event_id:b.event_id,market_id:b.market_id,revision:b.revision});}
async function openInputs(b,o,button){
 opener=button;selection={book:b,observation:o,token:frame.token};$('details-title').textContent='Original inputs';const content=$('detail-content');content.replaceChildren();
 const state=node('p','Captured inputs');state.id='captured-state';content.append(state,node('h3',`${b.title} · ${o.native_side} ${o.side}`),node('p',`${o.price??'Unavailable'} ${o.units}`));
 content.append(node('p','Calculations have their own captured inputs and may arrive later.'));
 const dl=node('dl',undefined,'raw-detail-grid');for(const [k,v] of Object.entries({Venue:venues[b.venue],Provider:b.provider,Event:b.event_id,Market:b.market_id,Outcome:o.outcome_id,Line:o.line,Period:b.period,'Source time':b.source_at,'Last price change':b.price_change_at,'Received':b.received_at,Synchronization:labels[b.status],Validation:b.validation,Matching:'Source identity · captured comparisons below',Quantity:o.quantity?`${o.quantity.value} ${o.quantity.unit}`:null})){dl.append(node('dt',k),node('dd',v??'Unknown'));}content.append(dl);
 if(o.levels){const depth=node('section');depth.append(node('h3',`Observed depth · ${o.levels} levels · ${o.depth||'Unknown completeness'}`));const rows=node('div');const more=node('button','Show depth');let pos=0;
 more.onclick=async()=>{more.disabled=true;try{const q=detailQuery(b);q.set('outcome',o.outcome_id);q.set('side',o.side);q.set('offset',pos);const data=await get('/api/raw/inputs?'+q);for(const l of data.depth_page.levels)rows.append(node('p',`${l.price?.value??'Unknown'} · ${l.quantity?.value??'Unknown'} ${l.quantity?.unit??''}`));pos=data.depth_page.next_offset;more.hidden=pos===null;more.textContent='More depth';}catch(e){rows.append(node('p',e.message));}finally{more.disabled=false;}};depth.append(rows,more);content.append(depth);}
 const calculations=node('section');const resultStatus=node('p','Checking captured calculations…');const resultRows=node('div');const resultMore=node('button','More captured results');resultMore.hidden=true;calculations.append(resultStatus,resultRows,resultMore);content.append(calculations);
 let resultOffset=0;const readResults=async()=>{try{const q=detailQuery(b);q.set('outcome',o.outcome_id);q.set('side',o.side);q.set('offset',resultOffset);const v=await get('/api/raw/calculations?'+q);if(selection?.book.id!==b.id||selection?.observation.id!==o.id)return;resultStatus.textContent=v.total?'Captured calculations · Last-known evidence, with its own original inputs':'No captured comparison available for this input.';for(const r of v.results)resultRows.append(capturedCalculation(r));resultOffset=v.next_offset;resultMore.hidden=resultOffset===null;}catch(e){resultStatus.textContent='Captured calculations unavailable. '+e.message;}};resultMore.onclick=readResults;readResults();
 const evidence=node('details');evidence.append(node('summary','Source details'),node('pre',JSON.stringify(b,null,2),'raw-detail'));content.append(evidence);evidence.addEventListener('toggle',async()=>{if(evidence.open&&!evidence.dataset.loaded){try{const value=await get('/api/raw/inputs?'+detailQuery(b));evidence.querySelector('pre').textContent=JSON.stringify(value,null,2);evidence.dataset.loaded='true';}catch(e){evidence.append(node('p',e.message));}}});$('details').showModal();
}
$('close-details').onclick=()=>$('details').close();$('details').addEventListener('close',()=>{selection=null;opener?.focus({preventScroll:true});});
for(const id of ['league','venue','family','period','game','search','state'])$(id).addEventListener('change',()=>{generation++;offset=0;load();});
$('clear-filters').onclick=()=>{for(const id of ['league','venue','family','period','game','search','state'])$(id).value='';generation++;offset=0;load();};
$('previous').onclick=()=>{if(busy)return;offset=Math.max(0,offset-50);load(true);};$('next').onclick=()=>{if(busy||!frame||frame.next_offset===null)return;offset=frame.next_offset;load(true);};$('refresh').onclick=()=>load();$('retry').onclick=()=>load();
$('stop').onclick=async()=>{try{const r=await fetch('/api/admin/current',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'stop'})});if(!r.ok)throw Error('Open Admin to stop collection');await load();}catch(e){$('status').textContent=e.message;}};
setInterval(()=>{if($('live').checked&&!document.hidden&&!selection)load();},2000);
load();

$('unusable').addEventListener('toggle',async()=>{if(!$('unusable').open)return;const root=$('unusable-content');try{const v=await get('/api/raw/failures');root.replaceChildren(node('p',v.retention));if(!v.failures.length)root.append(node('p','No retained unusable frames.'));for(const f of v.failures){const d=node('details');d.append(node('summary',`${venues[f.source]} · ${f.received_at} · ${f.stage} · Unqualified`));d.addEventListener('toggle',async()=>{if(d.open&&!d.querySelector('pre')){const x=await get('/api/raw/failures?id='+f.id);d.append(node('pre',JSON.stringify(x.failure,null,2),'raw-detail'));}});root.append(d);}}catch(e){root.replaceChildren(node('p',e.message));}});

window.addEventListener('pagehide',()=>{if(frame)fetch('/api/raw/read?token='+frame.token,{method:'DELETE',headers:{'Content-Type':'application/json'},keepalive:true});});
