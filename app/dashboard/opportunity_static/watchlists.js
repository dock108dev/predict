'use strict';
window.PredictWatch=(()=>{
 const get=id=>document.getElementById(id),escape=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let watches=[],report=null,timer=null,busy=false,current=null;
 const label={raw_gap:'Raw gap (price / probability units)',arb_return:'Supported conditional arbitrage return (%)',ev:'Supported conditional EV (%)'};
 async function request(url,body){const r=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error);return data;}
 function expire(reason){current=null;clearTimeout(timer);get('watch-signals').textContent=reason;}
 function renderWatches(){get('watch-list').innerHTML=watches.map(w=>'<p><b>'+escape(w.name)+'</b> · '+escape(label[w.metric])+' ≥ '+escape(w.threshold)+' · '+escape(w.quantity)+' contracts · '+escape(Object.entries(w.filters).filter(([,v])=>v).map(([k,v])=>k+': '+v).join(', ')||'all markets')+' <button data-remove-watch="'+escape(w.id)+'">Remove</button></p>').join('')||'<p>No saved watchlists.</p>';}
 function pointLink(p,text){return p?.session&&p?.cutoff?'<a href="/game?'+escape(new URLSearchParams({...p,view:'arb'}))+'">'+escape(text)+'</a>':escape(text);}
 function historyHtml(r){return '<p>Historical '+escape(r.mode)+' · '+escape(r.coverage.records)+' journal records · '+escape(r.coverage.evaluations)+' evaluated cutoffs · '+escape(r.coverage.skipped_cutoffs)+' skipped · '+(r.coverage.complete?'complete verified coverage':'partial coverage')+'</p><p>'+escape(r.assumptions)+'</p><p>Retained detail limit: '+escape(r.dropped)+' entries omitted. Calculation '+escape(r.calculation_version)+' · projection '+escape(r.projection_version)+'</p>'+r.items.map(i=>'<details><summary>'+escape(i.title)+' · '+escape(label[i.metric])+' · '+escape(i.episodes)+' distinct crossings · '+escape(i.qualifying_observations)+' qualifying observations</summary><p>'+escape(i.mode)+' · '+escape(i.ended_reason||'No qualifying signal')+'</p>'+(i.observed_spans||[]).map(s=>'<p>'+pointLink(s.first,'First observed '+s.first.at)+' → '+pointLink(s.last,'Last observed '+s.last.at)+' · '+escape(s.samples)+' samples across '+escape(s.observed_seconds)+' observed seconds; availability between samples unproven.</p>').join('')+i.changes.map(c=>'<p>'+pointLink(c.point,c.point.at)+' · '+escape(c.value)+' · '+escape(c.size)+' contracts</p>').join('')+'<p>'+pointLink(i.last_observed_point,'Inspect last evaluated cutoff')+'</p><p>'+i.reasons.map(escape).join('; ')+'</p></details>').join('')+'<p>Exclusions: '+escape(JSON.stringify(r.exclusions))+'</p>'+(r.items.some(i=>i.qualifying_observations)?'':'<p>No qualifying opportunities at the evaluated cutoffs.</p>');}
 async function refresh(payload){
  current=payload;
  if(!payload.live||!payload.status?.active){expire('Historical review / stopped: no live signals.');return;}
  if(busy)return;busy=true;
  try{
   const r=await request('/api/signals');
   if(current!==payload||!current.live)return;
   const active=r.items.filter(i=>i.active&&i.session===payload.capture);
   let markup=active.map(i=>'<p>'+(i.mode==='synthetic'?'Simulation · ':'')+escape(label[i.metric])+' · '+escape(i.title)+' · '+escape(i.changes.at(-1)?.value)+' · observed '+escape(i.last.at)+'</p>').join('')||'No qualifying live signals.';
   markup+=r.events.slice(-8).map(e=>'<p>'+escape(e.kind)+' · '+escape(e.point.at)+' · '+escape(e.reason)+'</p>').join('');
   if(get('watch-signals').innerHTML!==markup)get('watch-signals').innerHTML=markup;
   clearTimeout(timer);timer=setTimeout(()=>expire('Signal view expired: no confirmed refresh within 15 seconds.'),15000);
  }catch(e){expire('Signals unavailable: '+e.message);}finally{busy=false;}
 }
 async function init(){
  try{watches=(await request('/api/watchlists')).watchlists;renderWatches();}catch(e){get('watch-message').textContent=e.message;}
  get('watch-save').onclick=async()=>{try{
   const filters=Object.fromEntries(['competition','season','family','period','venue','search'].map(k=>[k,get(k).value]));
   const w={name:get('watch-name').value,metric:get('watch-metric').value,threshold:get('watch-threshold').value,quantity:get('quantity').value,filters};
   watches=(await request('/api/watchlists',[...watches,w])).watchlists;renderWatches();report=null;get('history-download').disabled=true;get('opportunity-history').textContent='Watch thresholds changed. Rebuild the historical report.';get('watch-message').textContent='Saved locally. Collection authority unchanged.';if(current)refresh(current);
  }catch(e){get('watch-message').textContent=e.message;}};
  get('watch-list').onclick=async e=>{if(!e.target.dataset.removeWatch)return;try{watches=(await request('/api/watchlists',watches.filter(w=>w.id!==e.target.dataset.removeWatch))).watchlists;renderWatches();expire('Watchlist changed; waiting for next admitted observation.');}catch(err){get('watch-message').textContent=err.message;}};
  get('history-build').onclick=async()=>{get('history-build').disabled=true;get('history-download').disabled=true;report=null;get('opportunity-history').textContent='Rebuilding from verified original journal…';try{report=await request('/api/opportunity-history?'+new URLSearchParams({capture:get('capture').value}));get('opportunity-history').innerHTML=historyHtml(report);get('history-download').disabled=false;}catch(e){get('opportunity-history').textContent=e.message;}finally{get('history-build').disabled=false;}};
  get('history-download').onclick=()=>{if(!report)return;location.href='/api/opportunity-history?'+new URLSearchParams({capture:report.session,download:'true',watch_ids:JSON.stringify(report.watchlists.map(w=>w.id))});};
 }
 document.addEventListener('DOMContentLoaded',init);
 return {refresh,expire,historyHtml};
})();
