const node=(tag,text,cls)=>{const value=document.createElement(tag);if(text!==undefined)value.textContent=text;if(cls)value.className=cls;return value;};
const known=value=>value===null||value===undefined||value===''?'Unknown':String(value);
const json=value=>JSON.stringify(value,null,2);
const $=id=>document.getElementById(id);
async function get(url){const response=await fetch(url,{cache:'no-store'});const value=await response.json();if(!response.ok)throw Error(value.error||value.message||'Stored read failed');return value;}
function grid(parent,values){const dl=node('dl',undefined,'research-detail-grid');for(const [key,value]of Object.entries(values))dl.append(node('dt',key),node('dd',known(value)));parent.append(dl);}
function section(parent,title){const value=node('section');value.append(node('h3',title));parent.append(value);return value;}
function evidence(parent,title,value){const details=node('details');details.append(node('summary',title),node('pre',json(value)));parent.append(details);return details;}
function table(parent,columns,rows){const value=node('table',undefined,'research-evidence-table'),head=node('thead'),headRow=node('tr');for(const title of columns)headRow.append(node('th',title));head.append(headRow);const body=node('tbody');for(const cells of rows){const tr=node('tr');for(const cell of cells)tr.append(node('td',known(cell)));body.append(tr);}value.append(head,body);parent.append(value);}
async function coverage(){
 const root=$('coverage-content');root.replaceChildren(node('p','Reading acquisition, archive and retention…'));
 try{
  const value=await get('/api/research/coverage'),report=value.coverage;root.replaceChildren();
  root.append(node('p',`Collector: ${report.runtime?.healthy?'process healthy':'process unavailable'} · observed ${report.observed_at}. Receipt and archive clocks below establish their own coverage.`));
  const scroll=node('div',undefined,'catalog-scroll');root.append(scroll);
  table(scroll,['Source','Acquisition','Last receipt','Received / admitted','Calculated','Durable archive'],(report.sources||[]).map(item=>[
   item.provider,item.acquisition_state,item.last_received_at,
   `${known(item.received?.records)} / ${known(item.admitted?.records)}`,
   item.calculated?`${item.calculated.records} records · ${item.calculated.events} events · ${item.calculated.unavailable} unavailable`:'Unknown',
   item.archive_supported?`${known(item.archive?.verified)} verified · ${known(item.archive?.last_verified_at)} · ${known(item.archive?.skipped)} recorded skips`:'Unsupported archive route']));
  const retention=value.original_responses;root.append(node('p',`Original responses: ${known(retention.state)} · ${known(retention.captured_receipts)} captures · ${known(retention.compressed_bytes)} compressed bytes. Historical completeness is not established.`));
  evidence(root,'Outages, gaps, controls and coverage limitations',report);evidence(root,'Original-response retention bounds and gaps',retention);
 }catch(error){root.replaceChildren(node('p','Coverage unavailable. '+error.message));}
}
$('coverage')?.addEventListener('toggle',()=>{if($('coverage').open)coverage();});
function cohortResult(root,detail){
 root.replaceChildren();const value=detail.evaluation;
 grid(root,{Designation:value.designation,'Declared records':value.population_records,'Distinct events':value.distinct_events,'Due records':value.due_records,'Due distinct events':value.due_distinct_events,'Future records':value.future_records,'Future distinct events':value.future_distinct_events,'Scored records':value.scored_records,'Scored distinct events':value.scored_distinct_events,'Case statuses':json(value.status_counts),'Evaluation knowledge cutoff':value.as_of});
 if(value.policy_comparison?.length){const scroll=node('div',undefined,'catalog-scroll');root.append(scroll);table(scroll,['Recorded policy','Population records / events','Due / future records','Scored records / events','Case statuses','Mean Brier','Mean log loss'],value.policy_comparison.map(policy=>[policy.policy_version,`${policy.population_records} / ${policy.distinct_events}`,`${known(policy.due_records)} / ${known(policy.future_records)}`,`${policy.scored_records} / ${policy.scored_distinct_events}`,json(policy.status_counts),policy.mean_brier,policy.mean_log_loss]));}
 evidence(root,'Frozen population, cases, calibration and correction history',detail);
}
function researchRetention(root,value){
 const panel=section(root,'Research retention & capture gaps');panel.id='research-retention-status';
 if(!value){panel.append(node('p','Retention accounting is unavailable for this read.'));return;}
 const counts=value.retention_dispositions||{},account=value.retention_accounting||{};
 grid(panel,{'Frozen record bytes':value.retained_bytes,'Allocated bytes including gap accounting':value.total_allocation_bytes,'Total research byte cap':value.byte_cap,'Observation bytes':value.observation_bytes,'Observation byte cap':value.observation_byte_cap,'Reserved case/horizon slots':counts.slots,'Counter coverage starts':account.coverage_started_at,'Observation refusal attempts':counts.observation_refusals,'Capture refusal attempts':counts.capture_refusals,'Observation case/horizon slots affected':counts.observation_affected_slots,'Capture case/horizon slots affected':counts.capture_affected_slots,'Open observation case/horizon gaps':counts.observation_open_gaps,'Open capture case/horizon gaps':counts.capture_open_gaps,'Earlier first observed refusal':account.prior_first_observed_refusal_at,'Earlier uncounted window ends':account.prior_uncounted_window_end,'Earlier refusal attempts':account.prior_refused_attempts,'Earlier affected cases':account.prior_affected_cases});
 panel.append(node('p','Current refusal counts cover recorded attempts since counter coverage began. Attempts and case/horizon slots are different counts. Earlier unknown counts remain unknown.'));
 if(account.prior_window_status)panel.append(node('p',account.prior_window_status));
 evidence(panel,'Retention bounds, counter scope and recorded gaps',value);
}
async function cohorts(){const root=$('cohort-content');root.replaceChildren(node('p','Reading declared populations…'));try{const value=await get('/api/research/cohorts');root.replaceChildren();researchRetention(root,value.research_retention);if(!value.cohorts.length)root.append(node('p','No research population has been declared. The operator CLI declares event/market/line horizons before capture; journal selections are separate.'));for(const item of value.cohorts){const row=node('div',undefined,'research-panel-row'),button=node('button',item.name||item.id),results=node('div'),download=node('a','Export frozen evidence','research-button');download.href='/api/research/cohorts?'+new URLSearchParams({id:item.id,export:'1'});download.download='predict-research-cohort.json';button.onclick=async()=>{button.disabled=true;try{cohortResult(results,await get('/api/research/cohorts?id='+encodeURIComponent(item.id)));}catch(error){results.replaceChildren(node('p',error.message));}finally{button.disabled=false;}};row.append(button,node('small',item.id),download,results);root.append(row);}}catch(error){root.replaceChildren(node('p','Research populations unavailable. '+error.message));}}
$('cohorts')?.addEventListener('toggle',()=>{if($('cohorts').open)cohorts();});
