'use strict';
const $=id=>document.getElementById(id),escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const stamp=s=>s?escape(s.replace('T',' ').replace('+00:00',' UTC')):'Unavailable';
const money=s=>s===null||s===undefined?'Unavailable':'$'+escape(s);
let data,selection;
function fail(error){$('content').hidden=true;$('loading').hidden=true;$('error').hidden=false;$('error').textContent=error.message;$('reset').hidden=false;}
function ladder(side,name){
 if(side===null)return `<div class="ladder"><h4>${name}</h4><p class="subtle">Unavailable — no native ladder supplied.</p></div>`;
 return `<div class="ladder"><h4>${name} · ${side.levels.length} levels</h4><p class="subtle">Retained depth: ${escape(side.depth)}</p><div class="depth-scroll"><table><thead><tr><th>Price (USD)</th><th>Contracts</th></tr></thead><tbody>${side.levels.map(l=>`<tr><td>${money(l.price.value)}</td><td>${escape(l.quantity.value)}</td></tr>`).join('')||'<tr><td colspan="2">Observed empty ladder</td></tr>'}</tbody></table></div></div>`;
}
function quote(price,size){return `<strong>${money(price)}</strong><small>${size===null||size===undefined?'Quantity unavailable':escape(size)+' contracts'}</small>`;}
function card(c){
 const b=c.book;
 return `<article class="panel book" data-venue="${c.venue}"><div class="card-title"><h3>${escape(c.label)}</h3><span class="historical-label">Historical only</span></div><p class="market-id">${c.venue==='kalshi'?'KXNFLGAME-26SEP17DETBUF-BUF':'657964 · aec-nfl-det-buf-2026-09-17'}</p><dl class="health"><div><dt>Recorded connection</dt><dd>${escape(c.connection.replaceAll('_',' '))}</dd></div><div><dt>Last book synchronization</dt><dd>${b?escape(b.sync):'Unavailable'}</dd></div><div><dt>Observation age at cutoff</dt><dd>${c.age_seconds===null?'Unavailable':escape(c.age_seconds)+' s'}${c.receipt_stale?' · stale by saved 30 s policy':''}</dd></div></dl>${!b?'<div class="empty"><strong>No book known yet</strong><p>This cutoff precedes this venue’s first retained book. No later price is shown.</p></div>':`
 <table class="quotes"><thead><tr><th>Outcome / native side</th><th>Bid</th><th>Ask</th></tr></thead><tbody>${b.outcomes.map(o=>`<tr><th>${escape(o.team)}<small>${escape(o.native)}${o.native.toLowerCase()===o.side?'':' · '+escape(o.side)}</small></th><td>${quote(o.quote.bid,o.quote.bid_size)}</td><td>${quote(o.quote.ask,o.quote.ask_size)}</td></tr>`).join('')}</tbody></table>
 <p class="transformation">${c.venue==='kalshi'?'YES = Buffalo · NO = Detroit. Each displayed ask uses the existing supported transformation: 1 − the opposite native bid, with that bid’s quantity.':'Long = Detroit · Short = Buffalo. Long bids and offers are native. Short bid, ask and depth are unavailable in the saved supported conversion.'}</p>
 <p class="change">${b.changed_levels===null?'First retained book — no preceding book to compare.':b.changed_levels===0?'No native price-level or quantity change from the preceding book.':escape(b.changed_levels)+' native price level'+(b.changed_levels===1?'':'s')+' changed since the preceding book (additions, removals or quantity changes).'}</p>
 <div class="receipt"><p><span>Book received</span> ${stamp(b.received_at)}</p><p><span>Book known / retained</span> ${stamp(b.known_at)}</p><p><span>Source timestamp</span> ${stamp(b.source_at)}</p><p><span>Source time progression</span> ${escape(b.source_progress)} · last book market state: ${escape(b.market_state)}</p></div>
 <details class="depth"><summary>Inspect all retained native depth</summary><p>Native ladders only. Full describes the retained API image; partial is an advertised window. Neither establishes executable capacity.</p>${b.outcomes.map(o=>`<h4>${escape(o.team)} · ${escape(o.native)}</h4><div class="ladders">${ladder(o.depth.bids,'Native bids')}${ladder(o.depth.asks,'Native offers')}</div>`).join('')}</details>`}</article>`;
}
function render(){
 const p=E5State.select(data.timeline,selection.at),index=data.timeline.indexOf(p);
 $('cutoff').textContent=p.at.replace('T',' ').replace('+00:00',' UTC');$('point-label').textContent=p.label+' · '+p.known_books+' of 44 books known';
 $('timeline').max=data.timeline.length-1;$('timeline').value=index;$('timeline').setAttribute('aria-valuetext',p.label+' '+p.at);$('venue').value=selection.venue;
 $('previous').disabled=index===0;$('next').disabled=index===data.timeline.length-1;$('position').textContent=(index+1)+' / '+data.timeline.length;
 const open=new Set([...document.querySelectorAll('article details[open]')].map(e=>e.closest('article').dataset.venue));
 $('books').innerHTML=p.cards.filter(c=>selection.venue==='both'||selection.venue===c.venue).map(card).join('');
 document.querySelectorAll('article').forEach(a=>{if(open.has(a.dataset.venue)&&a.querySelector('details'))a.querySelector('details').open=true;});
 const url=RealState.url(data,selection);history.replaceState(null,'',url);$('bookmark').href=url;
}
async function init(){
 try{
  const response=await fetch('/api/package',{cache:'no-store'});data=await response.json();if(!response.ok)throw Error(data.error||'Saved evidence unavailable.');
  selection=RealState.restore(data,location.search);
  $('interval').textContent=data.capture_start.slice(11,26)+' – '+data.capture_end.slice(11,26)+' UTC';$('kickoff').textContent=data.kickoff.replace('T',' ').replace('+00:00',' UTC');
  $('counts').innerHTML=[['frames','Raw frames'],['books','Reconstructed books'],['packets','Quote packets'],['ingress','Persisted ingress records']].map(([k,l])=>`<div><strong>${data.counts[k]}</strong><span>${l}</span></div>`).join('');
  $('coverage-limit').textContent=data.coverage.limitation;$('completeness').textContent=data.coverage.completeness;
  $('verification').textContent='Verified on this load: journal hash chain, saved configuration, 44 native books and 88 exact quote packets. Terminal completion is a separate journal row.';
  $('session-id').textContent=data.session;$('chain').textContent=data.hash;
  $('arb').textContent=data.economics.arb;$('our-price').textContent=data.economics.our_price;$('mispricing').textContent=data.economics.mispricing;
  $('previous').onclick=()=>{selection=RealState.move(data,selection,-1);render();};$('next').onclick=()=>{selection=RealState.move(data,selection,1);render();};
  $('timeline').oninput=()=>{selection.at=data.timeline[Number($('timeline').value)].id;render();};$('venue').onchange=()=>{selection.venue=$('venue').value;render();};
  window.onpopstate=()=>{try{selection=RealState.restore(data,location.search);render();}catch(e){fail(e);}};
  render();$('loading').hidden=true;$('content').hidden=false;
 }catch(error){fail(error);}
}
init();
