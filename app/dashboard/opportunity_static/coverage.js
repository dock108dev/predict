'use strict';
const byId=id=>document.getElementById(id);
let timer;
async function refresh(){
 const response=await fetch('/api/status');const s=await response.json();
 byId('state').textContent=s.state+(s.error?' · '+s.error:'')+' · '+(s.pilot_allowance||'')+(s.stop_reason?' · '+s.stop_reason:'')+(s.previous_pilot?' · Previous pilot: '+s.previous_pilot.reason:'');
 const d=s.discovery;if(d)byId('state').textContent+=' · Catalog generation '+(d.published_generation??'none')+' · age '+(d.age_seconds==null?'unknown':Math.round(d.age_seconds)+'s')+' · refresh '+d.refresh.state;
 byId('start').disabled=!s.start_available;byId('stop').disabled=!s.active;
 byId('rows').replaceChildren();
 for(const [venue,c] of Object.entries(s.coverage||{})){
  const tr=document.createElement('tr');
  for(const value of [venue,c.discovered_markets,c.eligible,c.requested,c.acknowledged,c.receiving,c.usable]){const td=document.createElement('td');td.textContent=value??'Unknown';tr.append(td);}
  byId('rows').append(tr);
 }
 byId('detail').textContent=JSON.stringify(s,null,2);
 clearTimeout(timer);if(s.active)timer=setTimeout(()=>refresh().catch(showError),1000);
}
function showError(e){byId('state').textContent=e.message;}
async function command(name){
 byId('start').disabled=true;
 const r=await fetch('/api/'+name,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(name==='start'?{duration:180}:{})});
 const body=await r.json();if(!r.ok)throw Error(body.error);await refresh();
}
byId('start').onclick=()=>command('start').catch(showError);
byId('stop').onclick=()=>command('stop').catch(showError);
refresh().catch(showError);
