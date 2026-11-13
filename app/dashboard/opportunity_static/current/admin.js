import {mountFeeCensus} from './fee-census-view.js';
import '/view/current/ui-common.js';
import {applyTheme, readPreference, savePreference, timezone} from '/view/current/desk-preferences.js';
const $=id=>document.getElementById(id);
const requestedSection=new URLSearchParams(location.search).get('section');
const adminSection=['sources','scope','usage','settings','fees','quality','database'].includes(requestedSection)?requestedSection:'overview';
for(const panel of document.querySelectorAll('[data-panel]'))panel.hidden=panel.dataset.panel!==adminSection;
for(const link of document.querySelectorAll('[data-section]'))if(link.dataset.section===adminSection)link.setAttribute('aria-current','page');
for(const zone of [...new Set(['UTC', Intl.DateTimeFormat().resolvedOptions().timeZone, ...(Intl.supportedValuesOf?.('timeZone')||[])])].sort()) {
  const option=document.createElement('option');option.value=zone;option.textContent=zone.replaceAll('_',' ');$('timezone').append(option);
}
for(const key of ['theme','timezone']){
  $(key).value=readPreference(key);
  $(key).onchange=()=>{savePreference(key,$(key).value);applyTheme();};
}
$('display-settings').onsubmit=event=>event.preventDefault();
const labels={kalshi:'Kalshi',polymarket_us:'Polymarket US',the_odds_api:'The Odds API',sportsgameodds:'SportsGameOdds',novig:'Novig',prophetx:'ProphetX'};
const value=x=>x===null||x===undefined?'Unknown':typeof x==='object'?JSON.stringify(x):String(x);
const seconds=x=>x===null||x===undefined?'Unknown':`${Math.round(x)}s`;
const latency=x=>x===null||x===undefined?'Unknown':x<1?`${Math.round(x*1000)}ms`:`${x.toFixed(1)}s`;
const name=x=>labels[x]||x;
const scheduled=x=>x?.state==='budget_delayed'&&['aggregate_budget_delayed','aggregate_outside_window'].includes(x.reason_code);
const availability=x=>scheduled(x)?'Waiting for scheduled refresh':x.state.replaceAll('_',' ');
function refreshTime(at){
  if(!at||!Number.isFinite(Date.parse(at)))return 'Not scheduled';
  return new Intl.DateTimeFormat(undefined,{hour:'numeric',minute:'2-digit',timeZoneName:'short',timeZone:timezone()}).format(new Date(at));
}
function alternateProgress(p){
  const m=p.metrics||{};
  if(m.alternate_state==='deferred_for_scheduled_refresh')return m.alternate_deferred===null?'Event discovery paused for the next scheduled refresh.':`${m.alternate_completed||0} completed · ${m.alternate_deferred} deferred for the next scheduled refresh. Older uncollected events take priority next cycle.`;
  if(m.alternate_state==='acquiring')return `${m.alternate_completed||0} of ${m.alternate_plan?.event_requests??'unknown'} event requests completed.`;
  if(m.alternate_state==='acquisition_and_exact_line_admission_complete')return `${m.alternate_completed||0} event requests completed in the last alternate pass.`;
  if(m.alternate_state==='blocked_full_census_exceeds_authorized_cycle')return 'Full alternate scope exceeds the current cycle budget.';
  return m.alternate_state==='event_census'?'Checking the event list.':'Not collected in this cycle yet.';
}
function sgoDiagnostics(metrics){
  const {objects, provider_usage:provider, schedule_budget:pace,
    admitted_quote_clock_samples:samples, completed_refresh_polls:polls,
    resolved_objects_last_hour:spend, resolved_objects_hour_ended_at:spendThrough,
    alternate_refresh:alternates} = metrics;
  const accounted = objects ? objects.initial_used + objects.charged : null;
  const totals = {};
  for (const [cohort, tally] of Object.entries(samples || {})) {
    if (['pinnacle','fanduel','draftkings','betmgm','caesars'].includes(cohort.split(':').at(-1))) continue;
    for (const [field, count] of Object.entries(tally)) {
      totals[field] = (totals[field] || 0) + count;
    }
  }
  const objectsByCategory = {};
  for (const row of spend || []) {
    objectsByCategory[row.category] = (objectsByCategory[row.category] || 0) + row.objects;
  }
  return [
    ['Object use', objects ? `${accounted} accounted · ${objects.held} held · ${objects.reserve} reserved · ${objects.available} available above reserve` : 'Account limits unavailable'],
    ['Latest provider usage', provider ? `${provider.used} used at ${refreshTime(provider.at)} · ${accounted === provider.used ? 'Agrees with ledger' : 'Ledger and provider snapshots differ'}` : 'No provider observation'],
    ['Next scheduled refresh', refreshTime(metrics.next_refresh_at)],
    ['Estimated daily object use', pace ? `${pace.projected_refresh_objects} refresh + ${pace.projected_discovery_objects ?? 'unknown'} discovery · ${pace.daily_allowance} allowance · variable overhead excluded${pace.projected_headroom_objects == null ? '' : ` · ${pace.projected_headroom_objects} projected headroom`}` : 'No estimate'],
    ['Polling intervals', pace ? `Live ${pace.live_minutes} min · within ${pace.approaching_hours}h ${pace.approaching_minutes} min · within 12h ${pace.imminent_minutes} min · 12–72h ${pace.near_minutes} min · later ${pace.distant_minutes} min` : 'No estimate'],
    [spendThrough ? `Objects charged in the hour ending ${refreshTime(spendThrough)}` : 'Last recorded hourly charges', spend ? Object.entries(objectsByCategory).map(([category, count]) => `${count} ${category.replaceAll('_', ' ')}`).join(' · ') || '0' : 'No measurement'],
    ['Discovery', Object.entries(metrics.discovery_complete || {}).map(([league, complete]) => `${league}: ${complete ? 'complete traversal' : 'partial traversal'}`).join(' · ') || 'No traversal observed'],
    ['Alternate-line refreshes', alternates?.resolved_requests ? `${alternates.resolved_requests} requests · ${alternates.admitted_alternate_rows} retained · ${alternates.admitted_available_alternate_rows} provider-available at receipt` : 'No alternate-line receipts'],
    ['Completed event polls since start', polls ? Object.entries(polls).map(([tier, tally]) => `${tier}: ${tally.events} · ${value(tally.between_discovery_pages)} between pages · ${tally.max_schedule_delay_seconds}s max delay`).join(' | ') : 'No poll measurements'],
    ['Exchange-labeled receipt clocks since start', samples ? `${totals.within_15_seconds || 0} of ${totals.available || 0} available within 15s at receipt` : 'No receipt measurements'],
    ['Live exchange-labeled observations since start', samples ? `${totals.live_available || 0} available · ${totals.live_post_start || 0} post-start clocks · ${value(totals.live_fresh)} fresh at receipt · ${value(totals.live_fresh_at_admission)} fresh at admission` : 'No receipt measurements'],
    ['Live exact four-book pairs since start', samples ? `${totals.live_with_exact_sportsbook_pair || 0} offers · ${value(totals.live_with_sportsbook_clocks)} co-fresh at receipt · ${value(totals.live_with_sportsbook_clocks_at_admission)} co-fresh at admission` : 'No receipt measurements'],
    ['Live exact Pinnacle pairs since start', samples ? `${totals.live_with_exact_pinnacle_pair || 0} offers · ${value(totals.live_with_pinnacle_clocks)} co-fresh at receipt · ${value(totals.live_with_pinnacle_clocks_at_admission)} co-fresh at admission` : 'No receipt measurements']
  ];
}
function sourceAction(p){
  if(p.worker_behavior==='running'&&p.provider==='the_odds_api')return 'Collecting the selected scope. Completed league receipts remain separately listed; the next slot keeps its scheduled priority.';
  if(p.worker_behavior==='receiving')return 'Receiving updates. Check each displayed price’s age; connection status alone does not establish freshness.';
  if(p.worker_behavior==='waiting_for_cycle'&&Object.values(p.status||{}).every(scheduled))return 'Refresh runs automatically at the scheduled time.';
  return p.next_action||(p.worker_done?'Worker ended. Inspect issues and cleanup before guarded recovery.':p.provider==='the_odds_api'?'Wait for the shared daytime slot, or use the aggregate refresh control above.':'Wait for source images within the bounded runtime.');
}
const recoveryReason=x=>({quota_missing_duplicate_or_malformed:'Provider quota response failed validation.',candidate_changed:'This runtime uses an earlier app version. Open the matching version before restarting.',configuration_changed:'Source configuration changed. Start a runtime with the intended configuration.',cleanup_safety_unresolved:'Cleanup is unresolved. Stop acquisition and inspect the cleanup issue before restarting.',ambiguous_dispatch_unresolved:'A dispatched charge is unresolved. Reconcile accounting before restarting.',clock_continuity_unknown:'Clock continuity is unknown. Inspect accounting and source clocks before restarting.',data_runtime_unavailable:'The background data runtime is stopped or unhealthy. Start the data runtime locally, then inspect status.'}[x]||String(x).replaceAll('_',' '));
const node=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=value(text);return e;};
function pairs(target,rows){const dl=node('dl');for(const [key,v] of rows){dl.append(node('dt',key),node('dd',v));}target.replaceChildren(dl);}
// Keep disclosure elements stable so polling cannot steal focus or close them.
function groupedPairs(target,rows,visible,summary){let primary=target.querySelector('.primary-facts'),secondary=target.querySelector('.secondary-facts');if(!primary){primary=node('div');primary.className='primary-facts';const detail=node('details');detail.append(node('summary',summary));secondary=node('div');secondary.className='secondary-facts';detail.append(secondary);target.replaceChildren(primary,detail);}pairs(primary,rows.filter(([key])=>visible.includes(key)));pairs(secondary,rows.filter(([key])=>!visible.includes(key)));}
function replaceIfChanged(target,build,key){if(target.dataset.key===key)return;target.dataset.key=key;build();}
let current=null,busy=false,pulling=false,pollGeneration=0,feedbackTimer;
function feedback(text,durable=true){clearTimeout(feedbackTimer);$('feedback').textContent=text;if(!durable)feedbackTimer=setTimeout(()=>{$('feedback').textContent='';},6000);}
function render(s){
  current=s;
  const requestPending=s.dispatch_enabled&&s.quota?.blocking_reason==='ambiguous_dispatch_unresolved'&&(s.sources||[]).some(p=>p.provider==='the_odds_api'&&p.accounting_pending);
  const delayed=(s.sources||[]).flatMap(p=>Object.entries(p.status||{}).filter(([,v])=>v.state!=='available').map(([venue,v])=>name(venue)+': '+availability(v)));
  const healthy=s.data_runtime?.healthy!==false;
  const running=healthy&&s.dispatch_enabled;
  $('update-state').textContent=running?'Running':!healthy?'Data service unavailable':s.config?.enabled===false?'Collection disabled in configuration':'Stopped';
  document.querySelector('[data-action="stop"]').hidden=!running;
  document.querySelector('[data-action="recover"]').hidden=running||!healthy;
  const q=s.quota;
  const sgo=s.config?.aggregate_provider==='sportsgameodds' ? (s.sources||[]).find(p=>p.provider==='sportsgameodds') : null;
  const sgoObjects=sgo?.metrics?.objects;
  const incident=q?.recovery_incident;
  const aggregate=(s.sources||[]).find(p=>p.provider==='the_odds_api');
  const supported=incident?.attempts?.length && incident.attempts.every(a=>a.status>=500&&a.status<=599&&a.reason==='quota_missing_duplicate_or_malformed');
  const recover=$('account-recovery');
  recover.hidden=!!sgo||!supported;recover.disabled=busy||!healthy||!running||!aggregate?.worker_done||s.data_runtime?.paused_sources?.includes('the_odds_api');
  const sgoHolds = sgo?.metrics?.object_holds || [];
  $('recovery-incident').textContent = sgoHolds.length
    ? sgoHolds.map(hold => `${hold.id} · ${hold.created_at} · ${hold.reserved} held · ${hold.category || 'Request type unknown'} · ${hold.provider_request_id || 'No provider request ID'}`).join(' | ')
      + '. Reconcile each request with its provider response or charge record.'
    : incident?incident.attempts.map(a=>`${a.id} · HTTP ${a.status??'unknown'} · ${a.cost} credits · ${a.at}`).join('; ')+` . All ${incident.preserved_credits} credits remain held. `+(supported?'The owned service rechecks exact receipt, account, window and cleanup before one zero-credit balance observation. No missing charge is resolved.':'No supported recovery action for this incident. A new rate-limit exception requires separate authority.'):'No unresolved incident requires a new recovery action.';
  $('sgo-hold-trace').hidden = !sgoHolds.length;
  $('sgo-hold-evidence').textContent = sgoHolds.length ? JSON.stringify(sgoHolds, null, 2) : '';
  $('recovery-outcome').textContent=(q?.recovery_probes||[]).slice(-1).map(p=>`${p.id}: ${p.state}. Next eligible scheduled slot: ${refreshTime(q.next_due_at)}.`).join('');
  const sgoState=sgo?.metrics?.state;
  const sgoReason=sgo?.metrics?.reason_code;
  $('attention').textContent=!healthy?'Saved prices remain visible.':sgo
    ? sgoState ? `SportsGameOdds: ${sgoState.replaceAll('_',' ')}${sgoReason ? ' · '+recoveryReason(sgoReason) : ''}` : 'SportsGameOdds status unavailable.'
    : requestPending?'An aggregate request is in progress.':q?.blocking_reason?'Aggregate prices held: '+recoveryReason(q.blocking_reason):delayed.length?delayed.join(' · '):'Prices update automatically.';
  const configured=(s.sources||[]).length;
  const paused=(s.data_runtime?.paused_sources||[]).length;
  $('source-count').textContent=configured?`${Math.max(0,configured-paused)} of ${configured} collection feeds enabled`:'No source status available';
  const available=sgo ? sgoObjects?.available : q?.remaining;
  if(available==null)$('spending-summary').textContent='Balance unavailable';
  else $('spending-summary').replaceChildren(node('strong',available.toLocaleString()),node('span',sgo?' SportsGameOdds objects available above reserve':' provider credits remaining'));
  const holds=[];
  if(sgoObjects)holds.push(`${sgoObjects.held.toLocaleString()} SportsGameOdds objects held`);
  if(q?.held_uncertain_credits!=null)holds.push(`${q.held_uncertain_credits.toLocaleString()} ${sgo?'The Odds API ':''}credits held for unresolved charges`);
  $('spending-holds').textContent=holds.join(' · ');
  const config=s.config||{};
  pairs($('collection-scope'),[['Native leagues',(config.native_sports?.length?config.native_sports:config.sports)?.join(', ')],
    ['Native markets',(config.native_families?.length?config.native_families:config.families)?.join(', ')],
    ['Aggregate leagues',(config.aggregate_sports?.length?config.aggregate_sports:config.sports)?.join(', ')],
    ['Aggregate markets',config.families?.join(', ')]]);
  if(s.evidence_class&&!$('synthetic-notice')){const notice=node('p',s.evidence_class);notice.id='synthetic-notice';document.querySelector('h1').after(notice);}
  groupedPairs($('service'),[['State',(s.service_state||s.state||'Unknown').replaceAll('_',' ')],['Acquisition owner',s.ownership_held?'Held by this runtime':'Not held by this runtime'],['Runtime / attempt',`${value(s.runtime_id)} / ${value(s.attempt_id)}`],['Candidate',s.candidate_digest],['Runtime limit',s.deadline_remaining_seconds===null?'While data runtime runs':seconds(s.deadline_remaining_seconds)],['Background runtime',s.data_runtime?(s.data_runtime.healthy?'Healthy':'Unhealthy · current action withdrawn'):'Unknown'],['Shared calculations',Object.entries(s.background_calculations||{}).filter(([k])=>!k.endsWith('_error')).map(([k,v])=>`${k}: ${v}`).join(' · ')||'Unknown'],['Failure detection',`${seconds(s.data_runtime?.heartbeat_timeout_seconds)} heartbeat limit · last heartbeat ${value(s.data_runtime?.heartbeat_at)}`],['App lifecycle','Independent reader · closing the app leaves data running'],['Cleanup',s.cleanup_complete?'Complete':s.cleanup_errors?.length?s.cleanup_errors.join(', '):'Pending until stop'],['Recovery gate',requestPending?'Restart waits for pending request or charge accounting. See Usage & budget.':s.recovery?.reason?recoveryReason(s.recovery.reason):'Ready for guarded replacement']],['State','Background runtime','Recovery gate',...(s.service_state==='stopped'||s.cleanup_errors?.length?['Cleanup']:[])],'Runtime identity and failure detection');
  for(const b of document.querySelectorAll('[data-action]'))b.disabled=busy||(s.data_runtime&&s.data_runtime.healthy===false)||(b.dataset.action==='recover'&&(s.dispatch_enabled||!s.recovery||!!s.recovery.reason))||(b.dataset.action==='refresh'&&!s.dispatch_enabled);
  if(!$('refresh-sports').children.length)for(const sport of ['NFL','NBA','MLB','NHL','NCAAF','NCAAB']){const label=node('label',sport+' '),input=node('input');input.type='checkbox';input.value=sport;input.checked=s.config?.sports?.includes(sport)||false;label.prepend(input);$('refresh-sports').append(label);}
  $('refresh-result').textContent=s.dispatch_enabled?'':'Refresh needs an active acquisition runtime. Use recovery when its checks permit a restart.';
  const novigPublic=s.metrics?.novig_public;
  const novigNative=s.metrics?.novig_native;
  const sportsbook = s.metrics?.public_sportsbook;
  $('public-sportsbook-status').hidden = !sportsbook;
  if (sportsbook) {
    $('public-sportsbook-schedule').textContent = `Target ${sportsbook.poll_target_seconds / 60} minutes · ${sportsbook.paid_objects} paid objects`;
    $('public-sportsbook-leagues').replaceChildren(...Object.entries(sportsbook.leagues || {}).map(([league, poll]) => {
      const received = poll.received_at ? ` · last receipt ${refreshTime(poll.received_at)}` : '';
      const interval = poll.interval_seconds == null ? '' : ` · ${seconds(poll.interval_seconds)} between receipts`;
      return node('li', `${league} · ${poll.completed}/${poll.attempts} polls · ${poll.reason || poll.state}${received}${interval}`);
    }));
  }
  $('novig-public-status').textContent=!novigPublic ? 'Novig public discovery is not running.' :
    novigPublic.state === 'initializing' ? 'Novig public discovery is waiting for its first read.' :
    `Novig public discovery: ${novigPublic.events || 0} live events observed; ${novigPublic.books || 0} books sampled. ` +
    (novigPublic.state === 'unavailable' ? `Public discovery is unavailable (${String(novigPublic.gap || 'source error').replaceAll('_',' ')}).` :
     'Public snapshots are discovery evidence.') +
    (novigNative ? ` Signed feed: ${novigNative.state}; ${novigNative.subscriptions || 0} subscriptions` +
      (novigNative.discovery_partial ? ' (partial roster)' : '') +
      (novigNative.gap ? `. ${novigNative.gap.replaceAll('_',' ')}.` : '.') : '');
  const panels=s.sources||[];
  $('sources-empty').hidden=!!panels.length;
  $('sources').hidden=!panels.length;
  $('novig-public-status').hidden=!panels.length&&!novigPublic;
  // Stable source controls and open disclosures survive polling.
  for(const p of panels){
    let card=$('source-'+p.provider);
    if(!card){card=node('section');card.id='source-'+p.provider;card.append(node('h2',name(p.provider)),node('p','Affects '+p.affected_venues.map(name).join(' and ')));const body=node('div');body.className='source-body';card.append(body);const button=node('button','Pause '+(['the_odds_api','sportsgameodds'].includes(p.provider)?'aggregate source':name(p.provider)));button.dataset.action='pause';button.dataset.source=p.provider;card.append(button);$('sources').append(card);}
    groupedPairs(card.querySelector('.source-body'),[['Availability',p.worker_behavior==='running'&&p.provider==='the_odds_api'?'Collecting':Object.entries(p.status).map(([v,x])=>`${name(v)}: ${availability(x)}`).join(' · ')],...(p.provider==='the_odds_api'?[['Collection schedule','Every 15 minutes · 9 AM–11 PM Eastern'],['Alternate coverage',alternateProgress(p)],['League receipts',Object.entries(p.league_collection||{}).map(([league,venues])=>league+': '+Object.entries(venues).map(([venue,x])=>name(venue)+' '+x.reason_code.replaceAll('_',' ')+' · '+refreshTime(x.received_at)).join('; ')).join(' | ')||'No completed league receipts in this runtime'],['Next scheduled refresh',refreshTime(p.processing_phase==='waiting_for_cycle'?(Object.values(p.status||{}).find(x=>x.next_due_at)?.next_due_at||s.quota?.next_due_at):s.quota?.next_due_at)]]:[]),...(p.provider==='sportsgameodds'?sgoDiagnostics(p.metrics):[]),['Source detail',Object.entries(p.status).map(([v,x])=>`${name(v)}: ${x.reason}`).join('\n')],['Restoration',p.metrics.restoration?.stage?.replaceAll('_',' ')||'No restoration reported'],['Last connection failure',p.metrics.last_stream_failure?.close_diagnostic?.category||JSON.stringify(p.metrics.last_stream_failure?.close_diagnostic||null)||'None'],['Subscription coverage',p.metrics.subscription_priority?`${p.metrics.subscription_priority.active_markets} active / ${p.metrics.subscription_priority.deferred_markets} deferred · rotation every ${p.metrics.subscription_priority.rotation_seconds}s`:p.provider==='sportsgameodds'?'Paid pages; slate coverage is unverified':'Full selected roster'],['Book synchronization',p.metrics.synchronization?.state?.replaceAll('_',' ')||'Unknown'],['Raw update delay (p95)',latency(p.metrics.synchronization?.delivery_latency?.raw?.p95_seconds)],['Pending raw / derived',`${value(p.metrics.synchronization?.raw_pending_images)} / ${value(p.metrics.synchronization?.derived_pending_images)}`],['Last book / receipt',`${value(p.last_book_observation_at)} / ${value(p.last_book_receipt_at)}`],['Retained price source time',p.source_at],['Source age / meaning',`${seconds(p.source_age_seconds)} / ${p.timestamp_meanings.join(', ').replaceAll('_',' ')||'Unknown'}`],['Last price receipt',p.received_at],['Receipt age',seconds(p.receipt_age_seconds)],['Retained prices',p.quote_count_scope==='diagnostic_cache'?'SQL prices are reported in Coverage; diagnostic cache: '+p.quotes:p.quotes],['Worker behavior',p.worker_behavior?.replaceAll('_',' ')||'Unknown'],['Verified / eligible',`${p.identity_verified} identity verified / ${p.comparison_eligible} comparison eligible / ${p.stale} stale`],['Discovery / subscription',`${value(p.metrics.generations)} generations / ${value(p.metrics.selected_markets)} selected markets`],['Connections / requests',`${value(p.metrics.connections)} / ${value(p.metrics.requests)}`],['Reconnect / backoff',`${value(p.metrics.retries)} retries / ${seconds(p.backoff_remaining_seconds)} remaining`],['Calculation eligibility',Object.entries(p.calculation_eligible||{}).map(([k,n])=>`${k.replaceAll('_',' ')}: ${n}`).join(' / ')],['Next action',sourceAction(p)],['Freshness policy',p.freshness_policies.length?p.freshness_policies.map(x=>`${x.version}: ${x.maximum_age_seconds}s engineering threshold`).join('; '):'No evidenced freshness policy for retained prices']],['Availability','Collection schedule','Next scheduled refresh','Alternate coverage','League receipts','Restoration','Subscription coverage','Next action'],'Source clocks and diagnostics');
  }
  for(const b of document.querySelectorAll('[data-action="pause"]')){const paused=s.data_runtime?.paused_sources?.includes(b.dataset.source);b.disabled=busy||!s.dispatch_enabled||paused;b.textContent=paused?'Paused':(['the_odds_api','sportsgameodds'].includes(b.dataset.source)?'Pause aggregate source':'Pause '+name(b.dataset.source));}
  pairs($('quota'),s.config?.aggregate_provider==='sportsgameodds'?[['Accounting','SportsGameOdds object usage is shown in its source card. Historical The Odds API holds remain preserved.']]:q?[['Owner operating limits','300 credits per 15-minute cycle · 16,800 per operating day; existing account and hold guards apply'],['Monthly ceiling / reserve',`${q.ceiling} / ${q.engineering_reserve} credits`],['Provider used / remaining',`${value(q.used)} / ${value(q.remaining)}`],['Usage observed at',q.observation?.at],['Observation age',seconds(q.observation_age_seconds)],['Unresolved reservations',`${value(q.reserved)} credits / ${value(q.unresolved_attempts)} attempts`],['Independent balance',q.independent_balance?`${q.independent_balance.remaining} remaining at ${q.independent_balance.at}`:'No recovery balance imported'],['Recovery authority',q.recovery_authority?.length?`${q.covered_uncertain_attempts} uncertain attempts covered by ${q.recovery_authority.at(-1).authority}; charges remain unresolved`:'No conservative recovery authority'],['Current accounting blocker',requestPending?'Active request awaiting charge evidence':q.blocking_reason||q.pause?recoveryReason(q.blocking_reason||q.pause):'None'],['Conservative allowance',`${value(q.available)} credits above reserve; out-of-band spend may reduce this`],['Evidenced reset window',q.reset?`${q.reset.starts_at} → ${q.reset.ends_at}`:'Unknown — dispatch blocked'],['Next batch / bootstrap due',`${value(q.next_due_at)} / ${value(q.bootstrap_due_at)}`],['Scheduled sport scope',(s.config?.aggregate_sports?.length?s.config.aggregate_sports:s.config?.sports)?.join(', ')||'Unknown'],['Dispatch gate',q.pause||panels.find(x=>x.provider==='the_odds_api')?.status.novig?.reason||'Unknown']]:[['Accounting','No shared scheduler configured; no provider balance verified.']]);
  const issues=s.issues||[];
  replaceIfChanged($('issues'),()=>{const children=issues.map(i=>{const wrap=node('article');wrap.className='issue';wrap.append(node('h3',`${name(i.provider)} · ${i.kind.replaceAll('_',' ')}`));const body=node('div');wrap.append(body);groupedPairs(body,[['Affects',i.affected_venues.map(name).join(', ')],['Impact',i.impact],['Next action',i.next_action],['First / last observation',`${i.first_at} / ${i.last_at} (${i.occurrences} occurrences)`],['Scope / endpoint class',`${i.scope.sports.join(', ')} · ${i.scope.families.join(', ')} / ${i.endpoint_class.replaceAll('_',' ')}`],['Healthy independent paths',i.healthy_independent_paths.map(name).join(', ')||'None observed at issue time'],['Charge / reserved',`${value(i.credits)} / ${value(i.reserved_credits)} credits`],['Retry / backoff',`${i.retry_count} retries / ${i.backoff_seconds.join(', ')||'No automatic retry'} seconds`],['Runtime / attempt / candidate',`${i.runtime_id} / ${i.attempt_id} / ${i.candidate_digest}`]],['Affects','Impact','Next action','Charge / reserved'],'Issue history and identity');return wrap;});$('issues').replaceChildren(...(children.length?children:[node('p','No issues recorded in this runtime. This does not establish fresh quotes or provider coverage.')]));},JSON.stringify(issues));
  replaceIfChanged($('historical'),()=>{for(const i of s.historical_issues||[]){const wrap=node('article');pairs(wrap,[['Historical observation',i.observed_at],['Scope',i.scope],['Impact',i.impact],['Next action',i.next_action],['Paid batch charge',i.credits],['Candidate / attempt',`${i.candidate_digest} / ${i.attempt_id}`]]);const a=node('a','Retained U4 issue provenance');a.href='/api/admin/u4-issue';wrap.append(a);$('historical').replaceChildren(wrap);}},JSON.stringify(s.historical_issues));
  replaceIfChanged($('exclusions'),()=>{const x=s.exclusions||[];$('exclusions').replaceChildren(node('p',x.length?`${x.length} current admission exclusions`:'No sink exclusions recorded. Source discovery exclusions remain in technical measurements.'),...x.slice(0,100).map(e=>node('p',`${name(e.source)} · ${e.market_id} — ${e.reason}`)));},JSON.stringify(s.exclusions));
  const r=s.resources||{};
  pairs($('measurements'),[['Process peak RSS / retained peak / ceiling',`${value(r.sampled_rss_bytes)} / ${value(r.sampled_highwater_rss_bytes)} / ${value(r.rss_ceiling_bytes)} bytes`],['Encoded state / ceiling',`${value(r.state_encoded_bytes)} / ${value(r.state_ceiling_bytes)} bytes`],['Issue buffer / bounds',`${value(r.issue_records)} records, ${value(r.issue_encoded_bytes)} bytes / ${value(r.issue_record_ceiling)} records, ${value(r.issue_byte_ceiling)} bytes`],['Streams / pending notices / held reviews',`${value(r.subscribers)} / ${value(r.pending_notices)} / ${value(r.reviews)}`],['Admitted / rejected observations',`${value(s.sink?.admitted_observations)} / ${value(s.sink?.rejected_observations)}`],['Retained records / identity exclusions',`${value(s.sink?.admitted_records)} / ${value(s.sink?.identity_excluded_records)}`],['Commit latency last / high-water',`${value(s.sink?.last_commit_ms)} / ${value(s.sink?.max_commit_ms)} ms`],['Latency meaning','source_receipt_ms is a source-clock age difference; receipt_projection_ms is local image processing. http_response_ms measures awaited HTTP delivery. No browser paint latency is measured.']]);
  $('technical').textContent=JSON.stringify(s,null,2);
}
const feeStateNames = {
  verified:'Verified public terms', expired:'Fee review expired', scheduled:'Verified terms awaiting their effective time',
  market_terms_verified:'Market terms verified · PDF recheck unavailable',
  verification_overdue:'Standing terms · source recheck overdue',
  review_required:'Explicit review required', awaiting_verification:'Awaiting first verification'
};
const feeErrors = {
  public_straight_schedule_changed:'The official straight schedule changed.',
  prior_change_requires_explicit_review:'A prior change still requires explicit review.',
  conflicting_straight_fee_documents:'The fee page lists conflicting straight schedules.',
  conflicting_approved_rules:'Reviewed rules conflict at the same effective time.',
  straight_fee_document_missing:'The fee page did not identify a straight schedule.',
  fee_index_unparseable:'The straight schedule listing could not be read.',
  fee_document_unparseable:'The fee document could not be read.',
  fee_retrieval_failed:'The source did not respond in time or could not be reached.',
  fee_http_status:'The source returned an unsuccessful HTTP status.',
  fee_response_freshness_unverified:'The response could not be confirmed as fresh.',
  kalshi_renderer_unconfigured:'The data process has no configured PDF renderer.',
  kalshi_renderer_configuration_invalid:'The data process could not load a valid renderer endpoint.',
  kalshi_rendered_origin_unverified:'The renderer could not prove a fresh fetch of the official PDF.',
  kalshi_rendered_origin_http_status:'The renderer received an unsuccessful status from the official PDF.',
  kalshi_rendered_scope_ambiguous:'The renderer did not return a complete document.',
  kalshi_rendered_schedule_changed:'The rendered PDF differs from the approved rendering.',
  kalshi_market_terms_approval_mismatch:'The runtime fee model differs from the reviewed market terms.',
  kalshi_market_terms_changed:'Kalshi series or event fee terms changed.',
  kalshi_market_terms_ambiguous:'Kalshi market fee evidence is incomplete, conflicting, or unsupported.',
  kalshi_rounding_terms_changed:'The official rounding documentation changed.',
  fee_response_size_limit:'The response exceeded the retrieval limit.',
  fee_response_encoding_unsupported:'The source sent an unsupported response encoding.'
};
const feeDate = at => at ? new Intl.DateTimeFormat(undefined,{
  dateStyle:'medium',timeStyle:'medium',timeZone:timezone()
}).format(new Date(at)) : 'None known';
function feeSourceURL(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : null;
  } catch {
    return null;
  }
}
let feeSchedulesPending = false;
async function refreshFeeSchedules() {
  if (feeSchedulesPending) return;
  feeSchedulesPending = true;
  const notice = $('fee-schedules-status');
  try {
    const response = await fetch('/api/admin/fee-schedules', {
      cache: 'no-store', signal: AbortSignal.timeout(5000)
    });
    if (!response.ok) throw Error();
    const status = await response.json();
    replaceIfChanged($('other-public-fee-schedules'), () => {
      const root=$('other-public-fee-schedules');
      root.replaceChildren();
      for (const item of status.products || []) {
        const section=document.createElement('section');
        const title=document.createElement('h3');
        title.textContent=({novig:'Novig · pregame straight',polymarket_us:'Polymarket US · standard sports',kalshi:'Kalshi · exchange'})[item.venue] || item.venue;
        section.append(title);
        const facts=document.createElement('div'); section.append(facts);
        const attempt = item.refresh?.retrieval;
        const verified = item.retrieval;
        const httpStatus = attempt?.failed_request?.http_status || attempt?.renderer?.http_status || attempt?.document?.http_status;
        pairs(facts, [
          ['Status',feeStateNames[item.state] || item.state],
          ['Applicable through',item.review_before && feeDate(item.review_before)],
          ['Terms',item.standing_public_terms && 'Standing public terms'],
          ['Next action',item.next_action],
          ['Last issue',item.refresh?.error && (feeErrors[item.refresh.error] || recoveryReason(item.refresh.error))],
          ['Review basis',item.review_basis],
          ['Last verified',item.last_verified_at && feeDate(item.last_verified_at)],
          ['Next check',item.next_refresh_at && feeDate(item.next_refresh_at)],
          ['Recheck due',item.recheck_due_at && feeDate(item.recheck_due_at)],
          ['Last HTTP status',httpStatus],
          ['Rendered PDF verified',verified?.rendered_origin?.retrieved_at && feeDate(verified.rendered_origin.retrieved_at)],
          ['Last direct PDF check',item.direct_pdf?.http_status && `HTTP ${item.direct_pdf.http_status} · ${feeDate(item.direct_pdf.retrieved_at)}`],
          ['Exact-market evidence',verified?.event_history_complete && `${verified.series_count} series and complete event fee-change history verified.`]
        ].filter(([, value]) => value !== undefined && value !== null && value !== false && value !== ''));
        const source = feeSourceURL(item.source_url);
        if (source) {
          const link = node('a', 'Official fee source');
          link.href = source;
          section.append(link);
        }
        root.append(section);
      }
    },JSON.stringify(status.products));
    const terms = status.terms || {};
    const review = status.review_required;
    const recent = status.refresh;
    const error = recent?.error;
    $('public-fee-state').textContent = feeStateNames[status.state];
    replaceIfChanged($('public-fee-facts'), () => pairs($('public-fee-facts'), [
      ['Published version',terms.published_version || 'Awaiting verification'],
      ['Published update',terms.published_update || 'None known'],
      ['Published effective time',feeDate(terms.published_effective_from)],
      ['Authority begins',feeDate(terms.effective_from)],
      ['Last verified',feeDate(status.last_verified_at)],
      ['Review expires',feeDate(status.review_before)],
      ['Last refresh attempt',feeDate(recent?.at)],
      ['Refresh error',error ? feeErrors[error] || recoveryReason(error) : 'None'],
      ['Next refresh',feeDate(status.next_refresh_at)],
      ['Next known change',status.next_change ? `${feeDate(status.next_change.effective_from)} · ${status.next_change.version}` : 'None published'],
      ['Review issue',review ? feeErrors[review.reason] || recoveryReason(review.reason) : 'None'],
      ['NHL taker fee',terms.nhl_taker_coefficient ? `${terms.nhl_taker_coefficient} × price × (1 − price) per contract` : 'Unavailable'],
      ['Other events',terms.fee_rate ? `${Number(terms.fee_rate)*100}% of positive net gains per market` : 'Unavailable']
    ]),JSON.stringify(status));
    const documentURL = feeSourceURL(terms.document_url);
    $('public-fee-document-wrap').hidden = !documentURL;
    if (documentURL) $('public-fee-document').href = documentURL;
    const evidence = terms.retrieval || {};
    const failed = recent?.retrieval?.failed_request;
    replaceIfChanged($('public-fee-receipts'), () => pairs($('public-fee-receipts'), [
      ['Fee page retrieved',feeDate(evidence.index?.retrieved_at)],
      ['Fee page SHA-256',evidence.index?.sha256],
      ['Schedule retrieved',feeDate(evidence.document?.retrieved_at)],
      ['Schedule SHA-256',evidence.document?.sha256],
      ['Last error HTTP status',failed?.http_status],
      ...(review ? [['Review opened',feeDate(review.detected_at)],['Document awaiting review',review.retrieval?.document?.sha256]] : [])
    ]),JSON.stringify([evidence,failed,review]));
    notice.hidden = true;
  } catch {
    $('public-fee-state').textContent = 'Fee schedule status unavailable';
    notice.textContent = 'Latest fee schedules unavailable. Displayed review dates may be out of date.';
    notice.hidden = false;
  } finally {
    feeSchedulesPending = false;
  }
}

async function refresh(){if(pulling||busy)return;pulling=true;const generation=pollGeneration;try{const response=await fetch('/api/admin/status');if(!response.ok)throw Error();const data=await response.json();if(generation===pollGeneration&&!busy)render(data);}catch{if(generation!==pollGeneration||busy)return;feedback('Admin status unavailable. Controls require a current status response.');current=null;for(const b of document.querySelectorAll('[data-action]'))b.disabled=true;}finally{pulling=false;}}
document.addEventListener('click',async e=>{const b=e.target.closest('[data-action]');if(!b||b.disabled||busy)return;busy=true;pollGeneration++;for(const x of document.querySelectorAll('[data-action]'))x.disabled=true;const body={action:b.dataset.action};if(b.dataset.source)body.source=b.dataset.source;if(body.action==='refresh'){body.sports=[...$('refresh-sports').querySelectorAll('input:checked')].map(n=>n.value);body.request_id=crypto.randomUUID();body.reference=$('reference').checked;}if(body.action==='recover'||body.action==='recover_accounting'){body.runtime_id=current.runtime_id;body.candidate_digest=current.candidate_digest;}if(body.action==='recover_accounting'){body.recovery_id=current.quota.recovery_incident.recovery_id;body.covered_attempts=current.quota.recovery_incident.covered_attempts;}
  try{const response=await fetch('/api/admin/current',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok){feedback(data.reason||'Control failed. Inspect current status.');}else{feedback(body.action==='recover_accounting'?'Balance observation completed; original holds remain protected. Inspect the next eligible slot.':body.action==='recover'?'Fresh runtime recorded. Previous reviews expired.':body.action==='stop'?'The data runtime acknowledged Stop. Acquisition is withdrawn; check cleanup below.':body.action==='refresh'?'Refresh complete. Prices and quota updated.':'The data runtime acknowledged the source pause. It survives app and data restarts.',body.action==='recover'||body.action==='stop');render(data);}}
  catch{feedback('Control outcome unknown. Inspect status before trying again.');}finally{busy=false;if(current)render(current);await refresh();}
});
if (adminSection === 'fees') {
  const refreshCounts = mountFeeCensus($('admin-fee-census'));
  $('refresh-fee-census').onclick = () => refreshCounts();
  void refreshCounts();
}
async function quoteQuality(eventId) {
  const status = $('quote-quality-status');
  const root = $('quote-quality-results');
  root.replaceChildren();
  status.textContent = 'Reading stored observations…';
  try {
    const response = await fetch('/api/admin/quote-quality?' + new URLSearchParams(eventId ? {event_id:eventId} : {}));
    const report = await response.json();
    if (!response.ok) throw Error(report.reason || 'Stored observations unavailable.');
    if (!eventId) {
      for (const event of report.events) {
        $('quote-quality-event').append(new Option(`${event.league} · ${event.title} · ${event.start}`, event.id));
      }
      status.textContent = report.events.length ? '' : 'No retained events.';
      return;
    }
    status.textContent = `${report.event.title} · ${report.rows.length} direct quotes${report.truncated ? ' (limited to 500)' : ''} · SportsGameOdds receipt ${report.aggregate_received_at}`;
    const scroll = node('div'); scroll.className = 'odds-scroll'; scroll.tabIndex = 0;
    scroll.setAttribute('role', 'region'); scroll.setAttribute('aria-label', 'Direct and aggregate prices');
    const table = node('table'); table.className = 'odds-matrix';
    const header = table.createTHead().insertRow();
    for (const label of ['Outcome', 'Direct quote', 'SportsGameOdds same line', 'Game and contract association']) {
      const cell = node('th', label); cell.scope = 'col'; header.append(cell);
    }
    const body = table.createTBody();
    for (const row of report.rows) {
      const direct = row.native;
      const line = direct.selection.signed_line;
      const outcome = [direct.selection.label, direct.market.family, line].filter(value => value != null).join(' · ');
      const tr = body.insertRow();
      tr.append(node('th', outcome));
      const native = tr.insertCell();
      native.append(node('strong', `${name(direct.provider)} ${row.native_american || direct.price_value}`),
        node('small', `Source ${direct.source_at || 'unknown'} · Receipt ${direct.received_at}`),
        node('small', `${direct.native_market_id} · ${direct.native_outcome_id} · ${direct.native_side}`));
      const observed = tr.insertCell();
      for (const price of row.aggregate) {
        observed.append(node('strong', price.price_american || 'Price unavailable'),
          node('small', `${price.available ? 'Observed' : 'Closed'} · Source ${price.source_at || 'unknown'} · Receipt ${price.received_at}`),
          node('small', price.odd_id));
      }
      if (!row.aggregate.length) observed.append(node('span', 'No retained quote for this exact side and line'));
      tr.insertCell().textContent = ({polymarket_us_unverified:'Polymarket US mapping unverified',
        provider_event_link:'Provider event link', schedule_and_teams:'Teams and scheduled start'})[row.event_match]
        + ' · ' + ({unverified:'Contract unverified', exact_side_and_line_only:'Exact side and line; settlement unverified',
          unobserved:'No aggregate contract observed'})[row.contract_match];
    }
    scroll.append(table);
    root.append(scroll);
    const retained = node('details');
    retained.append(node('summary', 'Retained SportsGameOdds lines, fair values and links'),
      node('pre', JSON.stringify({links:report.links, observations:report.aggregate_observations,
        sportsbooks:report.sportsbook_observations}, null, 2)));
    root.append(retained);
  } catch (error) {
    status.textContent = error.message || 'Quote comparison unavailable.';
  }
}

if (adminSection === 'quality') {
  $('quote-quality-event').onchange = () => { $('quote-quality-id').value = $('quote-quality-event').value; };
  $('quote-quality-form').onsubmit = event => {
    event.preventDefault();
    const id = $('quote-quality-id').value.trim();
    if (id) void quoteQuality(id);
  };
  void quoteQuality();
}
const poll = adminSection === 'fees' ? refreshFeeSchedules : refresh;
if (adminSection === 'database') {
  import('/view/current/admin-database.js').then(({mountDatabase}) => mountDatabase()).catch(() => {
    $('db-status').textContent = 'Database browser could not load. Reload the page to try again.';
  });
} else if (adminSection !== 'quality') { poll(); setInterval(poll,5000); }
