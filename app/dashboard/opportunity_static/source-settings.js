/* Preferences are inert. Neither the include switch nor fresh quota is restored. */
(function(root){
'use strict';
const fields=['kalshi-events','kalshi-markets','us-events','us-markets','sports','markets','events','limit','refresh','stale','requests','credits','response','storage'];
const el=k=>document.getElementById('sources-'+k);
try{const saved=JSON.parse(localStorage.getItem('predict-source-settings')||'{}');for(const k of fields)if(typeof saved[k]==='string')el(k).value=saved[k];}catch(_){}
function settings(status){
 if(!el('enabled').checked)return null;
 if(!status.source_settings_available)throw Error('Aggregate source activation unavailable in this configuration.');
 const saved=Object.fromEntries(fields.map(k=>[k,el(k).value]));localStorage.setItem('predict-source-settings',JSON.stringify(saved));
 if(el('used').value===''||el('remaining').value==='')throw Error('Enter the fresh mock quota baseline for this explicit Start.');
 const csv=k=>el(k).value.split(',').map(x=>x.trim()).filter(Boolean),num=k=>Number(el(k).value);
 return {version:'unified-source-session-1',roles:{kalshi:'native_comparison',polymarket_us:'native_comparison',novig:'aggregate_comparison',prophetx:'aggregate_comparison',pinnacle:'reference',draftkings:'reference',betmgm:'reference'},
 correspondence_policy:'source-correspondence-1',native_scopes:{kalshi:'required-63-v1',polymarket_us:'required-63-v1'},
 native_selection:{kalshi:{event_ids:csv('kalshi-events'),market_ids:csv('kalshi-markets')},polymarket_us:{event_ids:csv('us-events'),market_ids:csv('us-markets')}},
 scopes:csv('sports').map(sport=>({sport,markets:csv('markets'),event_ids:csv('events')})),refresh_seconds:num('refresh'),stale_seconds:num('stale'),event_limit:num('limit'),quota_observed_at:new Date().toISOString(),
 http:{requests:num('requests'),credits:num('credits'),dollars:'0',dollars_per_credit:'0',reserve_per_request:csv('markets').length,initial_used:num('used'),initial_remaining:num('remaining'),plan_evidence:'Explicit local simulation; no credits spent',response_bytes:num('response'),session_bytes:num('storage'),timeout:5,retries:0,backoff:1}};
}
function render(status,capture,state){
 const bindings=el('bindings');if(bindings)bindings.href='/api/source-bindings?download=true'+(capture?'&capture='+encodeURIComponent(capture):'');
 const recovery=el('recovery');if(recovery){recovery.hidden=!(capture&&(state==='incomplete'||status.error));recovery.href='/api/recovery?capture='+encodeURIComponent(capture||'')+'&download=true';}
 for(const k of [...fields,'enabled','used','remaining'])el(k).disabled=status.active||!status.source_settings_available;
 const a=status.aggregate;
 el('state').textContent=a?`${status.active?a.state:'stopped'} · ${a.accounting.requests} requests · ${a.accounting.reserved_credits} credits reserved · ${a.accounting.conservative_remaining} remaining${a.accounting.stop?' · '+a.accounting.stop:''}`:status.source_settings_available?'Isolated local transports available. Start remains explicit.':'Aggregate collection unavailable: an isolated transport configuration or separately approved live binding is required.';
 if(status.active){el('used').value='';el('remaining').value='';}
}
root.PredictSources={settings,render};
})(globalThis);
