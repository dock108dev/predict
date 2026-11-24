import {accountingFacts,accountingEvidence} from './settings-accounting.js';
import {applyTheme, readPreference, savePreference, timezone} from './desk-preferences.js';
const $=id=>document.getElementById(id);
const node=(tag,text)=>{const item=document.createElement(tag);if(text!==undefined)item.textContent=text;return item;};
const known=value=>value===null||value===undefined?'Unavailable':String(value);
const names={sportsgameodds:'SportsGameOdds',the_odds_api:'The Odds API',kalshi:'Kalshi',polymarket_us:'Polymarket US',novig:'Novig',prophetx:'ProphetX'};
const clock=value=>{if(!value)return 'Not reported';const date=new Date(value);return Number.isFinite(date.getTime())?date.toLocaleString(undefined,{timeZone:timezone()}):'Not reported';};
const bytes=value=>value===null||value===undefined?'Unavailable':(Number(value)/1048576).toFixed(1)+' MiB';
let current=null,mode=null,busy=false,refreshing=false,dirty=false,feeMode=null,feePending=false,feeRequested=false,feeNotice=null;
async function request(path,options={}) {const response=await fetch(path,{cache:'no-store',credentials:'same-origin',signal:AbortSignal.timeout(10000),...options});let value;try{value=await response.json();}catch{throw Error('Operating status is unavailable.');}if(!response.ok)throw Error(value.reason||value.error||'Operating control failed.');return value;}
function facts(root,values){const grid=node('dl');grid.className='research-detail-grid';for(const [label,value]of values){grid.append(node('dt',label),node('dd',known(value)));}root.replaceChildren(grid);}
function renderFeeMode(value){
 if(value&&typeof value.enabled==='boolean')feeMode=value;
 const checkbox=$('include-fees');checkbox.checked=feePending?feeRequested:feeMode?.enabled===true;checkbox.disabled=!feeMode||busy||refreshing||feePending;
 $('fee-mode-status').textContent=feeNotice||(feeMode?(feeMode.enabled?'On · calculations use the existing fee models.':'Off · calculations assume zero fees.'):'Fee setting unavailable. Refresh status to retry.');
}
function render() {
 renderFeeMode(feeMode);const s=current;if(!s)return;const healthy=s.data_runtime?.healthy!==false,running=healthy&&s.dispatch_enabled;
 facts($('collection-state'),[['State',!healthy?'Data service unavailable':running?'Running':s.config?.enabled===false?'Disabled in configuration':'Stopped'],['Background service',healthy?'Available · runs with the browser closed':'Unavailable; stored observations remain inspectable']]);
 const stop=document.querySelector('[data-control="stop"]'),resume=document.querySelector('[data-control="recover"]');stop.hidden=!running;resume.hidden=running;stop.disabled=busy||!healthy;resume.disabled=busy||!healthy||!!s.recovery?.reason;
 if(!running&&s.recovery?.reason)$('control-result').textContent='Resume is unavailable: '+String(s.recovery.reason).replaceAll('_',' ')+'.';
 const evidence=accountingEvidence(s);facts($('credits-state'),accountingFacts(s,clock));
 $('hold-details').hidden=!evidence.sportsgameodds.object_holds.length&&!evidence.sportsgameodds.interrupted_scans.length&&!evidence.the_odds_api.recovery_incident&&!evidence.the_odds_api.reserved_exposure&&!evidence.the_odds_api.uncertain_held_credits;$('hold-evidence').textContent=JSON.stringify(evidence,null,2);
 const paused=s.data_runtime?.paused_sources||[];$('source-rows').replaceChildren(...(s.sources||[]).filter(p=>p.provider==='sportsgameodds').map(p=>{const row=node('tr'),state=paused.includes(p.provider)?'Paused':p.worker_done?'Stopped':Object.values(p.status||{}).some(v=>v.state==='available')?'Available':'Waiting / unavailable';const td=node('td'),pause=node('button',paused.includes(p.provider)?'Paused':'Pause source');pause.type='button';pause.dataset.control='pause';pause.dataset.source=p.provider;pause.disabled=busy||!healthy||!running||paused.includes(p.provider);td.append(pause);for(const value of [names[p.provider]||p.provider,state,clock(p.last_valid_receipt_at||p.received_at||p.last_book_receipt_at)])row.append(node('td',value));row.append(td);return row;}));
 $('collection-scope').textContent='Leagues: '+(s.config?.aggregate_sports||s.config?.sports||[]).join(', ')+'. Markets: '+(s.config?.families||[]).join(', ')+'.';
 $('operating-evidence').textContent=JSON.stringify({service:s.service_state,recovery:s.recovery,background:s.background_work,issues:s.issues,source_pauses:paused},null,2);
}
function renderMode(value){mode=value.activity_mode||value;if(!mode?.settings)return;facts($('collection-schedule'),[['Next discovery',clock(mode.next_monitor_at)],['Discovery schedule','24/7 · first full capture, then T−10']]);if(!dirty){$('discovery-interval').value=mode.settings.monitor_interval_seconds/60;$('discovery-phase').value=(mode.settings.monitor_phase_seconds??1200)/60;$('discovery-horizon').value=mode.settings.monitor_horizon_seconds===null?'':mode.settings.monitor_horizon_seconds/3600;}$('save-collection').disabled=busy;}
function renderWorkspace(value){
 const {storage,reference_scope:referenceScope,readiness}=value;
 renderFeeMode(value.fee_mode);
 $('reference-books').textContent=referenceScope?.books
  ? referenceScope.books.map(book=>book.label).join(', ')+'. SportsGameOdds provides the source identity. Kalshi, Polymarket US, Novig and ProphetX remain the four trading markets.'
  : 'The selected sportsbook reference list is unavailable for this status read.';
 const retention=readiness?.retention;
 const knownStorage=[
  ['Retained research',bytes(storage.retained_bytes)+' of '+bytes(storage.byte_cap)],
  ['Unreserved capacity',bytes(storage.remaining_bytes)],
  ['Protected late-capture reservations',bytes(storage.late_reserved_bytes)],
  ['Next checkpoint capture',value.next_capture?value.next_capture.checkpoint+' · '+clock(value.next_capture.target_at):'No eligible pending checkpoint'],
 ];
 if(retention)knownStorage.push(
  ['Tracked games',`${retention.tracked_games} of ${retention.max_tracked_games}`],
  ['Current price database',bytes(retention.database_bytes)+' of '+bytes(retention.database_byte_cap)],
  ['Host disk available',bytes(retention.disk_free_bytes)+' (free-space floor '+bytes(retention.disk_floor_bytes)+')'],
 );
 facts($('storage-state'),knownStorage);
 $('retention-readiness').textContent=readiness?.blockers?.length
  ? readiness.blockers.map(issue=>issue.message).join(' ')
  : readiness?.state==='limited'
    ? 'Unreserved capacity is below the measured mean for a retained checkpoint pair.'
    : readiness?.state==='ready' ? 'Current collection and storage guards allow new capture attempts.' : '';
 if(!retention)return;
 const gaps=[
  ['Historical checkpoint and outcome refusals',retention.checkpoint_refusals],
  ['Last checkpoint or outcome refusal',clock(retention.last_checkpoint_refused_at)],
  ['Missed price checkpoints',retention.missed_checkpoints],
  ['Legacy observation refusals',retention.observation_refusals],
  ['Legacy capture refusals',retention.capture_refusals],
 ];
 if(retention.historical_gap_started_at)gaps.push(
  ['Earlier uncounted refusal window',clock(retention.historical_gap_started_at)],
  ['Earlier refused attempts',retention.historical_gap_attempts??'Unknown'],
 );
 facts($('retention-gaps'),gaps);
}
async function refreshDailyCoverage(){
 try{
  const value=await request('/api/workspace/mens-d1/status'), credits=value.credits, storage=value.storage, forecast=value.forecast;
  const words=raw=>raw==null?'':String(raw).replaceAll('_',' ');
  facts($('mens-d1-source'),[
   ['Sports Reference',words(value.state)],['Source status reason',words(value.reason)||'—'],
   ['Next scheduled job',clock(value.next_run_at)],['Past due within job window',value.overdue_jobs],
   ['Last successful source read',clock(value.last_success_at)],
   ['Recorded requests',credits.requests],['Unconfirmed dispatches',credits.unconfirmed_dispatches],
   ['Confirmed credits',credits.confirmed],['Unconfirmed credit exposure',credits.held],
   ['Source cost (USD)',credits.cost_usd],['Daily source evidence retained',bytes(storage.source_bytes)],
   ['Daily source in-flight reservations',bytes(storage.source_reserved_bytes)],
   ['Unreserved shared research headroom',bytes(storage.headroom_bytes)+' of '+bytes(storage.allocation_bytes)],
   ['Database runway',bytes(storage.sql_bytes)+' of '+bytes(storage.sql_cap_bytes)],
   ['Host disk available',bytes(storage.disk?.free_bytes)+' (free-space floor '+bytes(storage.disk?.floor_bytes)+')'],
   ...(forecast ? [['Next 24 hours, planned source jobs',forecast.next_24h_pending_jobs],
    ['Forecast basic credits before additional retries or detail requests',forecast.planned_basic_credits],
    ['Forecast maximum source response bytes',bytes(forecast.maximum_response_bytes)],
    ['Next 24 hours, T−10 tasks',`${forecast.next_24h_cbb_late_tasks} college basketball · ${forecast.next_24h_late_tasks} all sports`]] : []),
  ]);
  $('mens-d1-job-table').hidden=!value.jobs.length;
  $('mens-d1-job-rows').replaceChildren(...value.jobs.map(job=>{
   const row=node('tr');
   for(const item of [job.game_date,words(job.purpose),words(job.state),
    clock(job.next_attempt_at||job.due_at),clock(job.last_attempt_at),clock(job.last_success_at),
    `${job.attempts}${job.last_reason?' · '+words(job.last_reason):''}`])row.append(node('td',item));
   return row;
  }));
 }catch(error){
  $('mens-d1-source').textContent='Daily job status unavailable. '+error.message;
  $('mens-d1-job-table').hidden=true;
 }
}
async function refresh(){
 if(refreshing||busy)return;
 refreshing=true;renderFeeMode(feeMode);$('settings-status').textContent='Reading operating status…';
 void refreshDailyCoverage();
 const results=await Promise.allSettled([request('/api/admin/status'),request('/api/admin/activity-mode'),request('/api/workspace/status')]);
 if(results[0].status==='fulfilled'){current=results[0].value;render();}
 else{current=null;for(const button of document.querySelectorAll('[data-control]'))button.disabled=true;}
 if(results[1].status==='fulfilled')renderMode(results[1].value);else $('save-collection').disabled=true;
 if(results[2].status==='fulfilled')renderWorkspace(results[2].value);
 else{
  $('storage-state').textContent='Storage status is unavailable. Collection still enforces existing storage limits.';
  $('retention-readiness').textContent='';$('retention-gaps').replaceChildren();
 }
 $('settings-status').textContent=results.every(r=>r.status==='fulfilled')?'Status read at '+clock(new Date().toISOString())+'.':results[0].status==='rejected'?'Operating status unavailable. Controls require a current response.':'Some operating details are unavailable.';
 refreshing=false;renderFeeMode(feeMode);
}
$('settings-refresh').onclick=refresh;
$('include-fees').onchange=async()=>{
 if(!feeMode||busy||refreshing||feePending){renderFeeMode(feeMode);return;}
 feeRequested=$('include-fees').checked;feePending=true;busy=true;feeNotice='Saving fee setting…';renderFeeMode(feeMode);
 try{const saved=await request('/api/workspace/fees',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:feeRequested})});if(typeof saved.enabled!=='boolean')throw Error('The saved fee setting could not be verified.');feeMode=saved;feeNotice=(saved.enabled?'Fees included.':'Zero fees assumed.')+' Calculation setting updated without collecting prices.';}
 catch(error){feeNotice='Fee setting was not confirmed. Refresh status before retrying. '+error.message;}
 finally{feePending=false;busy=false;render();renderFeeMode(feeMode);}
};

document.addEventListener('click',async event=>{const button=event.target.closest('[data-control]');if(!button||button.disabled||busy||!current)return;const action=button.dataset.control,body={action};if(action==='pause')body.source=button.dataset.source;if(action==='recover')Object.assign(body,{runtime_id:current.runtime_id,candidate_digest:current.candidate_digest});busy=true;render();try{current=await request('/api/admin/current',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});$('control-result').textContent=action==='stop'?'Collection stopped. Stored data remains available.':action==='pause'?'Source pause acknowledged and preserved across restarts.':'Collection resumed under its existing guards.';}catch(error){$('control-result').textContent=error.message;}finally{busy=false;render();}});
$('collection-form').oninput=()=>{dirty=true;};$('collection-form').onsubmit=async event=>{event.preventDefault();if(busy||!mode)return;const settings={monitor_interval_seconds:Math.round(Number($('discovery-interval').value)*60),monitor_phase_seconds:Math.round(Number($('discovery-phase').value)*60),monitor_horizon_seconds:$('discovery-horizon').value===''?null:Math.round(Number($('discovery-horizon').value)*3600)};busy=true;$('save-collection').disabled=true;try{const value=await request('/api/admin/activity-mode',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({settings})});dirty=false;renderMode(value);$('configuration-result').textContent='Collection configuration saved.';}catch(error){$('configuration-result').textContent=error.message;}finally{busy=false;$('save-collection').disabled=false;}};
for(const zone of [...new Set(['UTC',Intl.DateTimeFormat().resolvedOptions().timeZone,...(Intl.supportedValuesOf?.('timeZone')||[])])].sort())$('timezone').append(new Option(zone.replaceAll('_',' '),zone));for(const key of ['theme','timezone']){$(key).value=readPreference(key);$(key).onchange=()=>{savePreference(key,$(key).value);applyTheme();};}$('display-form').onsubmit=event=>event.preventDefault();
refresh();setInterval(()=>{if(!document.hidden)refresh();},15000);
