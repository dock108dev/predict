import { boundedTicketJSON } from './ticket-client.js';

// One optional scope read. Publication accounting is entirely server-owned.
export const SUMMARY_BOUNDS=Object.freeze({responseBytes:65536,timeoutMs:1800,intervalMs:2000});
const summaryDimensions=['venues','sports','leagues','markets','periods'];
const summaryCountKeys=['observed_episodes','observed_new','left_censored','ended','open','gap_censored'];
const summaryNumber=value=>typeof value==='string'&&/^-?\d{1,80}(?:\/\d{1,80}|\.\d{1,80})?$/.test(value)&&(!value.includes('/')||Number(value.split('/')[1])!==0);
const summaryInteger=value=>Number.isSafeInteger(value)&&value>=0;
const summaryInstant=value=>value===null||(typeof value==='string'&&value.length<=64&&Number.isFinite(Date.parse(value)));
export function summaryQuery(filters){const q=new URLSearchParams({category:filters.category});for(const k of summaryDimensions)if(filters[k].length)q.set(k,filters[k].join(','));for(const k of ['minimum_edge','minimum_size'])if(filters[k]!==null)q.set(k,filters[k]);return q;}
export function checkSummary(value,filters,context){
  const v=value;
  const blank=v?.state==='unavailable'&&v?.server_id===null&&v?.epoch===null&&v?.observed_at===null;
  if(v?.version!=='predict-opportunity-summaries-1'||(!blank&&(v.server_id!==context.server_id||v.epoch!==context.epoch))||typeof v.scope!=='string'||!v.scope.length||v.scope.length>256||!['available','unavailable','stopped'].includes(v.state)||!summaryInstant(v.observed_at)||(!blank&&v.observed_at===null))throw Error('summary_identity_invalid');
  for(const key of [...summaryDimensions,'category','minimum_edge','minimum_size'])if(JSON.stringify(v.filters?.[key])!==JSON.stringify(filters[key]))throw Error('summary_filters_crossed');
  if(!v.observation_window||!['from','to'].every(k=>summaryInstant(v.observation_window[k]))||(v.observation_window.from!==null&&v.observation_window.to!==null&&Date.parse(v.observation_window.from)>Date.parse(v.observation_window.to)))throw Error('summary_window_invalid');
  if(!v.counts||!summaryCountKeys.every(k=>summaryInteger(v.counts[k])&&v.counts[k]<=10000)||summaryCountKeys.slice(1).some(k=>v.counts[k]>v.counts.observed_episodes))throw Error('summary_count_invalid');
  for(const key of ['edge_percent','supported_capital_usd'])if(!v[key]||!['minimum','maximum'].every(k=>v[key][k]===null||summaryNumber(v[key][k])))throw Error('summary_extrema_invalid');
  if(!v.duration_seconds||!['minimum_observed','maximum_observed'].every(k=>v.duration_seconds[k]===null||(Number.isFinite(v.duration_seconds[k])&&v.duration_seconds[k]>=0&&v.duration_seconds[k]<=604800))||!summaryInteger(v.duration_seconds.complete_episodes)||v.duration_seconds.complete_episodes>v.counts.observed_episodes)throw Error('summary_duration_invalid');
  const c=v.coverage,h=v.history,b=v.bounds;
  if(!c||typeof c.state!=='string'||c.state.length>64||typeof c.complete!=='boolean'||!summaryInteger(c.observed_complete_publications)||!summaryInteger(c.gaps)||!(c.checked_zero===null||typeof c.checked_zero==='boolean')||!['evaluated_pairs','compatible_pairs'].every(k=>c[k]===null||(summaryInteger(c[k])&&c[k]<=2048)))throw Error('summary_coverage_invalid');
  if(c.checked_zero===true&&(!c.complete||c.evaluated_pairs===null||!c.compatible_pairs||c.evaluated_pairs!==c.compatible_pairs))throw Error('summary_checked_zero_invalid');
  if(!h||!['complete','continuity_lost','threshold_history_complete'].every(k=>typeof h[k]==='boolean')||!summaryInteger(h.evicted_episodes)||h.complete&&(h.continuity_lost||!h.threshold_history_complete||h.evicted_episodes>0||v.counts.left_censored>0||v.counts.gap_censored>0))throw Error('summary_history_invalid');
  if(!b||!['retention_seconds','episode_limit','storage_limit_bytes','physical_bytes','physical_high_water_bytes','queue_observations','response_bytes'].every(k=>summaryInteger(b[k]))||b.retention_seconds>604800||b.episode_limit>10000||b.storage_limit_bytes>10485760||b.physical_bytes>b.storage_limit_bytes||b.physical_high_water_bytes>b.storage_limit_bytes||b.response_bytes>SUMMARY_BOUNDS.responseBytes)throw Error('summary_bounds_invalid');
  if(!Array.isArray(v.notes)||v.notes.length>8||v.notes.some(x=>typeof x!=='string'||x.length>128)||!Array.isArray(v.unsupported_filters)||v.unsupported_filters.length>80||v.unsupported_filters.some(x=>typeof x!=='string'||x.length>256)||v.provider_requests!==0||v.financial_evaluations!==0)throw Error('summary_metadata_invalid');
  if((v.state!=='available'||v.unsupported_filters.length)&&c.checked_zero!==null)throw Error('summary_unavailable_zero_invalid');
  return v;
}
function summaryDecimal(value){if(value===null)return null;const parts=value.split('/').map(Number),n=parts.length===2?parts[0]/parts[1]:parts[0];return Number.isFinite(n)?n.toLocaleString(undefined,{maximumFractionDigits:2}):'unknown';}
function summaryRange(value,prefix='',suffix=''){const a=summaryDecimal(value.minimum),b=summaryDecimal(value.maximum);return a===null||b===null?'unknown':prefix+a+(a===b?'':'–'+prefix+b)+suffix;}
function summaryDuration(seconds){if(seconds===null)return 'unknown';return seconds<60?Math.floor(seconds)+'s':seconds<3600?Math.floor(seconds/60)+'m':(seconds/3600).toFixed(1)+'h';}
export function summaryCopy(v){
  if(v.observed_at===null)return {count:'Observation summaries unavailable · zero is not established.',range:'',coverage:'Current prices and manual tickets have their own readiness checks.'};
  const n=v.counts,category=v.filters.category==='covered_outcome_arb'?'arb':v.filters.category==='conditional_hedge'?'conditional-hedge':'EV';
  const count=n.observed_episodes+' observed '+category+' '+(n.observed_episodes===1?'episode':'episodes')+' · '+n.observed_new+' newly qualified · '+n.left_censored+' present at first observation.';
  const d=v.duration_seconds,span=d.minimum_observed===null||d.maximum_observed===null?'unknown':summaryDuration(d.minimum_observed)+'–'+summaryDuration(d.maximum_observed);
  const range='Observed edge '+summaryRange(v.edge_percent,'','%')+'; supported funding '+summaryRange(v.supported_capital_usd,'$')+'. Observed spans '+span+'; '+d.complete_episodes+' fully bounded. Edge and size maxima may differ in time.';
  const window=v.observation_window.from===null||v.observation_window.to===null?'Observation window unavailable':new Date(v.observation_window.from).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})+'–'+new Date(v.observation_window.to).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
  const coverage=window+' · '+(v.state==='stopped'?'Collection stopped':v.coverage.checked_zero===true?'Current selected scope checked; no current matches':v.coverage.complete?'Current selected scope checked':'Coverage incomplete; zero is not established')+'. '+(!v.history.threshold_history_complete?'Historical threshold matches are incomplete. ':'')+(v.history.evicted_episodes?'Older retained episodes were evicted. ':'')+(!v.history.complete?'Earlier history or gaps are unknown. ':'')+'Spans are observations, not uninterrupted market lifetimes.';
  return {count,range,coverage};
}
export function bootSummaries(){
  const panel=document.getElementById('scanner-disclosure'),nodes=['count','range','coverage'].map(k=>document.getElementById('scanner-summary-'+k));
  let generation=0,controller=null,context=null,filters=null,scope='',nextAt=0,accepted=0;
  const put=copy=>['count','range','coverage'].forEach((key,i)=>{if(nodes[i].textContent!==copy[key])nodes[i].textContent=copy[key];});
  function reset(message='Observation summaries will be read for the selected filters.'){generation++;controller?.abort();controller=null;context=null;filters=null;scope='';nextAt=0;put({count:message,range:'',coverage:''});}
  function observe(next,page){const key=JSON.stringify([next,page.server_id,page.epoch]);if(key!==scope){reset();scope=key;}filters=JSON.parse(JSON.stringify(next));context={server_id:page.server_id,epoch:page.epoch};}
  async function read(){
    if(!panel.open||document.hidden||!context||controller||performance.now()<nextAt)return;
    const gen=generation,active=new AbortController(),expected=context,selected=filters;controller=active;nextAt=performance.now()+SUMMARY_BOUNDS.intervalMs;const timeout=setTimeout(()=>active.abort(),SUMMARY_BOUNDS.timeoutMs);
    try{const {value}=await boundedTicketJSON((...args)=>fetch(...args),'/api/scanner/summaries?'+summaryQuery(selected),{signal:active.signal,cache:'no-store'},SUMMARY_BOUNDS.responseBytes);if(gen!==generation)return;const v=checkSummary(value,selected,expected);accepted++;put(summaryCopy(v));}
    catch{if(gen===generation)put({count:'Observation summaries unavailable · zero is not established.',range:'',coverage:'Current prices and manual tickets have their own readiness checks.'});}
    finally{clearTimeout(timeout);if(controller===active)controller=null;}
  }
  panel.addEventListener('toggle',()=>{if(panel.open)void read();else{generation++;controller?.abort();controller=null;}});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)reset('Observation history paused while this page is hidden.');});addEventListener('pagehide',()=>reset());
  Object.defineProperty(window,'predictSummaryObservations',{value:()=>({accepted,activeReaders:controller?1:0,bounds:SUMMARY_BOUNDS})});
  return {observe,read,reset};
}
