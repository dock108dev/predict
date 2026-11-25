import {accountingFacts,accountingEvidence} from './settings-accounting.js';
import {applyTheme, readPreference, savePreference, timezone} from './desk-preferences.js';
const $=id=>document.getElementById(id);
const node=(tag,text)=>{const item=document.createElement(tag);if(text!==undefined)item.textContent=text;return item;};
const known=value=>value===null||value===undefined?'Unavailable':String(value);
const names={sportsgameodds:'SportsGameOdds',the_odds_api:'The Odds API',kalshi:'Kalshi',polymarket_us:'Polymarket US',novig:'Novig',prophetx:'ProphetX'};
const clock=value=>{if(!value)return 'Not reported';const date=new Date(value);return Number.isFinite(date.getTime())?date.toLocaleString(undefined,{timeZone:timezone()}):'Not reported';};
const bytes=value=>value===null||value===undefined?'Unavailable':(Number(value)/1048576).toFixed(1)+' MiB';
let current=null,busy=false,refreshing=false,feeMode=null,feePending=false,feeRequested=false,feeNotice=null;
async function request(path,options={}) {const response=await fetch(path,{cache:'no-store',credentials:'same-origin',signal:AbortSignal.timeout(10000),...options});let value;try{value=await response.json();}catch{throw Error('Operating status is unavailable.');}if(!response.ok)throw Error(value.reason||value.error||'Operating control failed.');return value;}
function facts(root,values){const grid=node('dl');grid.className='research-detail-grid';for(const [label,value]of values){grid.append(node('dt',label),node('dd',known(value)));}root.replaceChildren(grid);}
function renderFeeMode(value){
 if(value&&typeof value.enabled==='boolean')feeMode=value;
 const checkbox=$('include-fees');checkbox.checked=feePending?feeRequested:feeMode?.enabled===true;checkbox.disabled=!feeMode||busy||refreshing||feePending;
 $('fee-mode-status').textContent=feeNotice||(feeMode?(feeMode.enabled?'On · calculations use the existing fee models.':'Off · calculations assume zero fees.'):'Fee setting unavailable. Refresh status to retry.');
}
function render() {
 renderFeeMode(feeMode);const s=current;if(!s)return;const healthy=s.data_runtime?.healthy!==false,running=healthy&&s.dispatch_enabled;
 const retryStop=healthy&&!running&&Boolean(s.cleanup_errors?.length);
 facts($('collection-state'),[['State',!healthy?'Data service unavailable':running?'Running':retryStop?'Stop cleanup unconfirmed':s.config?.enabled===false?'Disabled in configuration':'Stopped'],['Background service',healthy?'Available · runs with the browser closed':'Unavailable; stored observations remain inspectable']]);
 const stop=document.querySelector('[data-control="stop"]'),resume=document.querySelector('[data-control="recover"]');stop.hidden=!running&&!retryStop;stop.textContent=retryStop?'Retry Stop':'Stop collection';resume.hidden=running;stop.disabled=busy||!healthy;resume.disabled=busy||!healthy||!!s.recovery?.reason;
 if(retryStop)$('control-result').textContent='Acquisition is withdrawn. Retry Stop to confirm cleanup.';
 else if(!running&&s.recovery?.reason)$('control-result').textContent='Resume is unavailable: '+String(s.recovery.reason).replaceAll('_',' ')+'.';
 const evidence=accountingEvidence(s);facts($('credits-state'),accountingFacts(s,clock));
 $('hold-details').hidden=!evidence.sportsgameodds.object_holds.length&&!evidence.sportsgameodds.interrupted_scans.length&&!evidence.the_odds_api.recovery_incident&&!evidence.the_odds_api.reserved_exposure&&!evidence.the_odds_api.uncertain_held_credits;$('hold-evidence').textContent=JSON.stringify(evidence,null,2);
 const paused=s.data_runtime?.paused_sources||[];
 const config=s.config||{};
 const sourceConfigured=id=>paused.includes(id)||(id===(config.aggregate_provider||'sportsgameodds')
  ?config.aggregate_enabled!==false:config['direct_'+id+'_enabled']!==false&&['kalshi','polymarket_us'].includes(id));
 $('source-rows').replaceChildren(...(s.sources||[]).filter(p=>sourceConfigured(p.provider)).map(p=>{const row=node('tr'),state=paused.includes(p.provider)?'Paused':p.worker_done?'Stopped':Object.values(p.status||{}).some(v=>v.state==='available')?'Available':'Waiting / unavailable';const td=node('td'),pause=node('button',paused.includes(p.provider)?'Paused':'Pause source');pause.type='button';pause.dataset.control='pause';pause.dataset.source=p.provider;pause.disabled=busy||!healthy||!running||paused.includes(p.provider);td.append(pause);for(const value of [names[p.provider]||p.provider,state,clock(p.last_valid_receipt_at||p.received_at||p.last_book_receipt_at)])row.append(node('td',value));row.append(td);return row;}));
 $('collection-scope').textContent='Leagues: '+(s.config?.aggregate_sports||s.config?.sports||[]).join(', ')+'. Markets: '+(s.config?.families||[]).join(', ')+'.';
 $('operating-evidence').textContent=JSON.stringify({service:s.service_state,recovery:s.recovery,background:s.background_work,issues:s.issues,source_pauses:paused},null,2);
}
function renderMode({settings, next_monitor_at}) {
 if (!settings) return;
 const interval = settings.monitor_interval_seconds / 60;
 facts($('collection-schedule'), [['Next discovery', clock(next_monitor_at)], ['Discovery interval', interval + ' minutes']]);
}
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
  const sourceNames={college_basketball_data:'CollegeBasketballData API',sports_reference:'Sports Reference'};
  const isCbbd=value.source==='college_basketball_data';
  const late=forecast?.late_capture, latency=late?.current_execution_latency;
  const busyWindow=late?.windows?.reduce((busiest,window)=>!busiest||window.scheduled_tasks>busiest.scheduled_tasks?window:busiest,null);
  const seconds=value=>value==null?'Unknown':`${Number(value).toFixed(2)} s`;
  facts($('mens-d1-source'),[
   ...(value.sources||[value]).map(source=>[sourceNames[source.source],
    [words(source.state),words(source.reason)].filter(Boolean).join(' · ')]),
   ['Scheduled job source',sourceNames[value.source]],
   ['Next scheduled job',clock(value.next_run_at)],['Past due within job window',value.overdue_jobs],
   ['Last successful source read',clock(value.last_success_at)],
   ['Recorded game requests',credits.requests],['Unconfirmed dispatches',credits.unconfirmed_dispatches],
   [isCbbd?'Confirmed metered calls':'Confirmed credits',credits.confirmed],
   [isCbbd?'Unconfirmed call exposure':'Unconfirmed credit exposure',credits.held],
   ...(isCbbd&&credits.budget?.window_ends_at?[['Shared monthly balance at account check',
    `${credits.budget.remaining_calls_at_check} of ${credits.budget.monthly_call_limit} calls`],
    ['Account allowance resets',clock(credits.budget.window_ends_at)]]:[]),
   ['Source cost (USD)',credits.cost_usd],['Daily source evidence retained',bytes(storage.source_bytes)],
   ['Daily source in-flight reservations',bytes(storage.source_reserved_bytes)],
   ['Unreserved shared research headroom',bytes(storage.headroom_bytes)+' of '+bytes(storage.allocation_bytes)],
   ['Database runway',bytes(storage.sql_bytes)+' of '+bytes(storage.sql_cap_bytes)],
   ['Host disk available',bytes(storage.disk?.free_bytes)+' (free-space floor '+bytes(storage.disk?.floor_bytes)+')'],
   ...(forecast ? [['Next 24 hours, planned source jobs',forecast.next_24h_pending_jobs],
    [isCbbd?'Forecast game calls before retries':'Forecast basic credits before additional retries or detail requests',forecast.planned_basic_credits],
    ['Forecast maximum source response bytes',bytes(forecast.maximum_response_bytes)],
    ['Next 24 hours, T−10 tasks',`${forecast.next_24h_cbb_late_tasks} college basketball · ${forecast.next_24h_late_tasks} all sports`]] : []),
   ...(busyWindow ? [['Busiest upcoming T−10 window',`${clock(busyWindow.target_at)} to ${clock(busyWindow.deadline_at)}`],
    ['Tasks and planned requests',`${busyWindow.scheduled_tasks} tasks · ${busyWindow.planned_event_requests} requests · ${busyWindow.ncaab_tasks} college basketball`],
    ['Window storage',`${bytes(busyWindow.reserved_bytes)} reserved · ${busyWindow.tasks_without_storage_reservation} tasks use shared headroom`],
    ['Measured batch samples',`${latency.samples} successful captures · ${latency.observed_physical_requests} observed request receipts`],
    ['Window capacity estimate',`${seconds(busyWindow.estimated_window_service_p95_seconds)} service · ${seconds(busyWindow.seconds_available)} available · ${words(busyWindow.risk)}`],
    ['Competing work',`${busyWindow.competing_non_late_tasks} ordinary checkpoint or result tasks · discovery slot ${clock(busyWindow.ordinary_discovery_slot_at)}`],
    ['In-flight and retry allowances',`${late.permitted_in_flight_event_requests} in flight · ${late.paid_retry_allowance} paid retries`]] : []),
  ]);
  $('mens-d1-job-table').hidden=!value.jobs.length;
  $('mens-d1-job-rows').replaceChildren(...value.jobs.map(job=>{
   const row=node('tr');
   const columns=[['Eastern game date',job.game_date],['Job',words(job.purpose)],['State',words(job.state)],
    ['Due / retry',clock(job.next_attempt_at||job.due_at)],['Last attempt',clock(job.last_attempt_at)],['Last success',clock(job.last_success_at)],
    ['Attempts / reason',`${job.attempts}${job.last_reason?' · '+words(job.last_reason):''}`]];
   for(const [name,item] of columns){const cell=node('td',item);cell.dataset.label=name;row.append(cell);}
   if(job.game_date){
    const dateLink=node('a',job.game_date);
    dateLink.href='/data?'+new URLSearchParams({evidence:'mens-d1',scope:'mens-d1',date:job.game_date});
    row.firstElementChild.replaceChildren(dateLink);
   }
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
 if(results[1].status==='fulfilled')renderMode(results[1].value);
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
for(const section of document.querySelectorAll('main > details[id]')){
 const reveal=()=>{if(location.hash==='#'+section.id)section.open=true;};
 window.addEventListener('hashchange',reveal);
 reveal();
}
for(const zone of [...new Set(['UTC',Intl.DateTimeFormat().resolvedOptions().timeZone,...(Intl.supportedValuesOf?.('timeZone')||[])])].sort())$('timezone').append(new Option(zone.replaceAll('_',' '),zone));for(const key of ['theme','timezone']){$(key).value=readPreference(key);$(key).onchange=()=>{savePreference(key,$(key).value);applyTheme();};}$('display-form').onsubmit=event=>event.preventDefault();
refresh();setInterval(()=>{if(!document.hidden)refresh();},15000);
