'use strict';
let ownerState, historicalMode=Boolean(location.search), savedLoaded=false, busy=false, actionPending=false;
const historicalSelection=new URLSearchParams(location.search);
function renderWatch(){
 const p=E5State.select(data.timeline,selection.at);if(!p)throw Error('Exact saved cutoff unavailable.');
 const live=data.live,index=data.timeline.indexOf(p);
 $('content').hidden=false;$('loading').hidden=true;$('error').hidden=true;$('reset').hidden=true;
 $('mode').textContent=live?'Live — captured real feeds':'Historical — captured from real feeds';
 $('notice').textContent=live?'Current observations only. A source without a synchronized recent book has no usable current quotes. No execution or qualified economics.':'Collection stopped for this saved session. Nothing shown is currently live or eligible for execution.';
 $('interval').textContent=data.capture_start+' – '+data.capture_end;$('kickoff').textContent=data.kickoff;
 $('cutoff').textContent=p.at;$('point-label').textContent=(live?'Current receipt cutoff':p.label)+' · '+p.known_books+' books retained';
 $('timeline').max=data.timeline.length-1;$('timeline').value=index;$('timeline').disabled=live;$('venue').value=selection.venue;
 $('previous').disabled=live||index===0;$('next').disabled=live||index===data.timeline.length-1;$('position').textContent=live?'Following current':(index+1)+' / '+data.timeline.length;
 const opened=new Set([...document.querySelectorAll('article details[open]')].map(e=>e.closest('article').dataset.venue));
 $('books').innerHTML=p.cards.filter(c=>selection.venue==='both'||selection.venue===c.venue).map(c=>{
  let html=card(c);if(live)html=html.replace('Historical only','Current observation').replace('No book known yet',escape(c.unavailable_reason||'No current book')).replace('This cutoff precedes this venue’s first retained book. No later price is shown.',c.last_receipt?'Last retained receipt: '+escape(c.last_receipt)+'. Await a recent synchronized image.':'Waiting for a synchronized image.');return html;
 }).join('');
 document.querySelectorAll('article').forEach(a=>{if(opened.has(a.dataset.venue)&&a.querySelector('details'))a.querySelector('details').open=true;});
 $('counts').innerHTML=[['frames','Raw frames'],['books','Book states'],['packets','Quote packets'],['ingress','Persisted ingress records']].map(([k,l])=>`<div><strong>${data.counts[k]}</strong><span>${l}</span></div>`).join('');
 $('coverage-limit').textContent=data.coverage.limitation;$('completeness').textContent=data.coverage.completeness;
 $('verification').textContent=live?'Journal-backed current view; exact native replay runs after shutdown.':`Saved file hashes, chain, configuration and native replay verified. ${data.replay.total_books} book states / ${data.replay.total_packets} packets; includes ${data.replay.derived_health_books} derived health states.`;
 $('transitions').textContent=data.transitions.map(t=>`${t.at} · ${t.source} · ${t.state||t.type}`).join('\n');
 $('session-id').textContent=data.session;$('chain').textContent=data.hash;
 for(const [id,key] of [['arb','arb'],['our-price','our_price'],['mispricing','mispricing']])$(id).textContent=data.economics[key];
 $('bookmark').hidden=live;if(!live){const url=RealState.url(data,selection);history.replaceState(null,'',url);$('bookmark').href=url;}
}
async function request(url,post=false){const r=await fetch(url,post?{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}:{cache:'no-store',signal:AbortSignal.timeout(3000)});const result=await r.json();if(!r.ok)throw Error(result.error||'Operation unavailable.');return result;}
async function loadSaved(sid,query){
 data=await request('/api/saved/'+encodeURIComponent(sid)+(query?.get('hash')?'?hash='+encodeURIComponent(query.get('hash')):''));
 const previousVenue=selection?.venue;selection=RealState.restore(data,query?query.toString():'');if(!query&&previousVenue)selection.venue=previousVenue;historicalMode=true;savedLoaded=true;renderWatch();$('saved').value=sid;
}
async function refresh(){
 if(busy)return;busy=true;
 try{
  const nextState=await request('/api/status');if(actionPending)return;ownerState=nextState;$('owner-state').textContent=ownerState.active?ownerState.state:'Idle · feeds stopped';
  $('start').disabled=!ownerState.start_available||ownerState.active;$('stop').disabled=!ownerState.active||ownerState.state==='stopping';$('interrupt').disabled=!ownerState.active||ownerState.interrupted||ownerState.state!=='running';
  $('owner-message').textContent=ownerState.error||(ownerState.active?`${ownerState.state} · ${ownerState.persisted}/${ownerState.delivered} accepted records drained`:'No collection is active. One real run maximum for this slice.');
  const selected=$('saved').value;$('saved').innerHTML='<option value="">Current / idle</option>'+ownerState.saved.map(s=>`<option value="${s}">${s}</option>`).join('');$('saved').value=selected;
  if(historicalMode&&!savedLoaded){await loadSaved(historicalSelection.get('session'),historicalSelection);}
  else if(!historicalMode&&ownerState.view){data=ownerState.view;selection={at:'current',venue:selection?.venue||'both'};renderWatch();}
  else if(!historicalMode&&!ownerState.active&&ownerState.saved.length){await loadSaved(ownerState.saved.at(-1));}
  else if(!historicalMode&&!ownerState.view){$('loading').hidden=true;$('content').hidden=true;}
 }catch(e){fail(e);}finally{busy=false;}
}
async function action(path){
 actionPending=true;
 try{
  $('owner-message').textContent='Working…';
  if(path==='/api/stop'){$('owner-state').textContent='stopping';$('stop').disabled=true;}
  if(path==='/api/interrupt'&&data?.live){
   const c=data.timeline[0].cards.find(c=>c.venue==='kalshi');c.last_receipt=c.book?.received_at||c.last_receipt;c.book=null;c.connection='interruption requested';c.unavailable_reason='Current book unavailable: controlled interruption requested';renderWatch();$('interrupt').disabled=true;
  }
  await request(path,true);
 }catch(e){$('owner-message').textContent=e.message;}
 finally{actionPending=false;await refresh();}
}
$('start').onclick=()=>{historicalMode=false;savedLoaded=false;history.replaceState(null,'','/');action('/api/start');};
$('stop').onclick=()=>action('/api/stop');$('interrupt').onclick=()=>action('/api/interrupt');
$('saved').onchange=async()=>{try{if($('saved').value)await loadSaved($('saved').value);else location.href='/';}catch(e){fail(e);}};
$('venue').onchange=()=>{selection.venue=$('venue').value;renderWatch();};
$('previous').onclick=()=>{selection=RealState.move(data,selection,-1);renderWatch();};$('next').onclick=()=>{selection=RealState.move(data,selection,1);renderWatch();};
$('timeline').oninput=()=>{selection.at=data.timeline[Number($('timeline').value)].id;renderWatch();};
refresh();setInterval(refresh,1000);
