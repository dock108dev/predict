const $=id=>document.getElementById(id);
const fieldIds={search:'search',provider:'provider',book:'original_bookmaker_id',sport:'sport',family:'family',calculation:'calculation_status',age:'max_age_minutes'};
let frame=null,offset=0,busy=false,selection=null,opener=null;
const node=(tag,text,cls)=>{const value=document.createElement(tag);if(text!==undefined)value.textContent=text;if(cls)value.className=cls;return value;};
const known=value=>value===null||value===undefined||value===''?'Unknown':String(value);
const json=value=>JSON.stringify(value,null,2);
const exact=value=>value==null?'Unknown':String(value);
const initial=new URLSearchParams(location.search);
for(const [id,key]of Object.entries(fieldIds))if(initial.has(key))$(id).value=initial.get(key);
function filters(){const query=new URLSearchParams();for(const [id,key]of Object.entries(fieldIds))if($(id).value.trim())query.set(key,$(id).value.trim());return query;}
function controls(){for(const id of ['apply','clear','refresh'])$(id).disabled=busy;$('previous').disabled=busy||!frame||offset===0;$('next').disabled=busy||!frame||frame.next_offset===null;$('catalog').setAttribute('aria-busy',String(busy));}
async function get(url){const response=await fetch(url,{cache:'no-store'});const value=await response.json();if(!response.ok)throw Error(value.error||value.message||`Stored read failed (${response.status})`);return value;}
function lines(cell,...values){for(const [index,value]of values.entries())cell.append(node(index===0?'strong':'small',known(value)));}
function rowView(row){
 const tr=node('tr');tr.dataset.record=row.id;
 const cell=label=>{const value=node('td');value.dataset.label=label;tr.append(value);return value;};
 lines(cell('Event / market'),row.title,`${row.sport} · ${row.family} · ${row.period}`,`Source event ${row.event_id}`);
 lines(cell('Provider / book'),row.provider,row.original_bookmaker_id,`Represented: ${row.represented_venue}`,`Equivalence: ${row.venue_equivalence}`);
 lines(cell('Outcome / line'),row.kind==='raw'?'Raw book: inspect outcomes':row.outcome,row.line===null?'Line: unknown / not applicable':`Line: ${row.line}`,`Identity: ${row.identity.mapping_status}`);
 lines(cell('Source price'),row.price===null?(row.kind==='raw'?'Inspect raw values':'Unavailable'):row.price,row.price_units,row.available===false?`Unavailable: ${row.availability_reason||'reason unknown'}`:row.available===true?'Source available':'Availability unknown');
 lines(cell('Clocks'),`Source: ${known(row.times.source_at)}`,`Received: ${known(row.times.received_at)}`);
 const calculation=cell('Calculation'),state=row.calculation;
 calculation.className='catalog-status-'+state.status;
 lines(calculation,state.status+(state.display?' · '+state.display:''),state.reason||`Net EV: ${exact(state.net_ev_percent)}%`,state.freshness,row.calculation_version);
 const button=node('button','Inspect');button.type='button';button.setAttribute('aria-label',`Inspect ${row.title}, ${row.original_bookmaker_id}, ${row.outcome||'raw book'}`);button.onclick=()=>inspect(row,button);cell('Inspect').append(button);
 return tr;
}
function render(value){
 window.predictResearchPage=value;
 $('catalog-rows').replaceChildren(...value.rows.map(rowView));
 $('catalog-status').textContent=`${value.total.toLocaleString()} received records · ${value.counts.source_events.toLocaleString()} source events`;
 $('catalog-snapshot').textContent=`Captured ${value.captured_at}. ${value.population}`;
 $('page').textContent=value.total?`${value.offset+1}–${value.offset+value.rows.length} of ${value.total.toLocaleString()}`:'No received records match these filters.';
}
async function load(continuation=false){
 if(busy)return;busy=true;controls();$('catalog-status').textContent=frame?'Reading stored data… Previous values remain visible.':'Loading received data…';
 const query=filters();history.replaceState(null,'','/research'+(query.size?'?'+query:''));query.set('offset',String(offset));query.set('limit','50');
 if(continuation&&frame)query.set('token',frame.token);else if(frame&&!selection)query.set('release',frame.token);
 try{const value=await get('/api/research/catalog?'+query);frame=value;offset=value.offset;render(value);}
 catch(error){$('catalog-status').textContent=(frame?'Stored data could not refresh. Displayed values are last-known. ':'Received data could not load. ')+error.message;}
 finally{busy=false;controls();}
}
function grid(parent,values){const dl=node('dl',undefined,'research-detail-grid');for(const [key,value]of Object.entries(values))dl.append(node('dt',key),node('dd',known(value)));parent.append(dl);}
function section(parent,title){const value=node('section');value.append(node('h3',title));parent.append(value);return value;}
function evidence(parent,title,value){const details=node('details');details.append(node('summary',title),node('pre',json(value)));parent.append(details);return details;}
function table(parent,columns,rows){const value=node('table',undefined,'research-evidence-table'),head=node('thead'),headRow=node('tr');for(const title of columns)headRow.append(node('th',title));head.append(headRow);const body=node('tbody');for(const cells of rows){const tr=node('tr');for(const cell of cells)tr.append(node('td',known(cell)));body.append(tr);}value.append(head,body);parent.append(value);}
function detailView(value,query){
 const root=$('input-content');root.replaceChildren();
 root.append(node('p',`Captured ${value.captured_at} · Revision ${value.revision}`,'research-muted'));
 const download=node('a','Export this exact input & result','research-button');
 // The selected record is already captured. Keep its export usable after the
 // bounded SQL paging lease expires while the owner reads the calculation.
 selection.exportUrl=URL.createObjectURL(new Blob([json(value)+'\n'],{type:'application/json'}));
 download.href=selection.exportUrl;download.download='predict-research-record.json';root.append(download);
 const source=section(root,'1. Received source input');
 grid(source,{Provider:value.provider,'Original bookmaker / venue ID':value.original_bookmaker_id,'Represented venue':value.represented_venue,'Venue equivalence':value.venue_equivalence,'Source event ID':value.event_id,'Source market / odd ID':value.source_market_id,'Original price':value.price,'Price units':value.price_units,Outcome:value.outcome,'Exact line':value.line,'Source available':value.available,'Availability reason':value.availability_reason,'Source time':value.times.source_at,'Receipt time':value.times.received_at,'Receipt hash':value.receipt_sha256,'Source revision':value.source_revision});
 if(value.raw_observations)table(source,['Outcome','Side','Price','Units','Disposition'],value.raw_observations.map(row=>[row.label,row.side,row.price,row.units,row.disposition]));
 evidence(source,'Retained source record',value.source_input);
 const identity=section(root,'2. Identity & settlement');
 grid(identity,{'Canonical event':value.identity.event_id,'Canonical contract':value.identity.contract_id,'Mapping status':value.identity.mapping_status,Settlement:value.identity.settlement,'Market family':value.family,'Source period':value.period,'Canonical period':value.identity.market?.period});
 evidence(identity,'Exact market, participant, line, outcome and result policy',value.contract||value.identity);
 const probability=section(root,'3. Probability inputs & policy');
 const payload=value.calculation_payload,ref=payload?.reference;
 grid(probability,{'Screening policy':value.probability_policy,'Selected screening book':ref?.book,'Screening probability':ref?.probability,'Probability conditioning':ref?.conditioning});
 if(ref?.prices)table(probability,['Book','Outcome','Line','American odds','Source time','Receipt time'],ref.prices.map(row=>[row.venue,row.side,row.line,row.price_american,row.source_at,row.received_at]));
 if(value.coherent_probability){const baseline=value.coherent_probability;grid(probability,{'Evaluation baseline':baseline.policy_version,'Whole-pair book':baseline.book,'Complementary probabilities':json(baseline.probabilities),'Exceptional outcomes':baseline.exceptional_outcomes,'Baseline ID':baseline.baseline_id});evidence(probability,'Frozen coherent baseline inputs',baseline);}
 else probability.append(node('p','Coherent evaluation baseline unavailable for this stored record.'));
 for(const [policy,baseline]of Object.entries(payload?.alternative_probabilities||{})){probability.append(node('h4','Optional comparison baseline · '+policy));grid(probability,{'Whole-pair book':baseline.book,'Complementary probabilities':baseline.probabilities?json(baseline.probabilities):null,'Availability reason':baseline.reason,'Selected outcome probability':baseline.probability});evidence(probability,'Exact optional baseline inputs',baseline);}
 const fee=section(root,'4. Fees, quantity & cashflows');
 const finance=payload?.fee||value.price_payload?.fee;
 if(finance){grid(fee,{'Fee classification':finance.classification,'Purchase USD':finance.purchase_usd,'Entry USD':finance.entry_usd,'Reserve USD':finance.reserve_usd,'Committed USD':finance.committed_usd,Quantity:finance.quantity,'Quantity increment':finance.quantity_increment});table(fee,['Settlement state','Exact cashflow'],Object.entries(finance.cashflows||{}).map(([state,cashflow])=>[state,json(cashflow)]));evidence(fee,'Fee applicability, schedule and rounding evidence',value.fee_input||finance);}
 else fee.append(node('p','Fee-qualified cashflows unavailable. '+(value.calculation.reason||'No fee result retained.')));
 const result=section(root,'5. Calculation result');
 grid(result,{Status:value.calculation.status,'Unavailable reason':value.calculation.reason,'Calculation freshness':value.calculation.freshness,'Exact net EV ratio':value.calculation.net_ev_ratio,'Net EV percent':value.calculation.net_ev_percent,'Displayed net EV':value.calculation.display,'Calculation version':value.calculation_version,'Input revision':value.calculation_revision,'Calculated at':value.times.calculated_at,'Eligibility deadline':value.times.valid_until});
 if(ref&&finance){result.append(node('p',`EV = p × (win net receipt / committed cash − 1) + (1 − p) × (loss net receipt / committed cash − 1). Frozen p = ${ref.probability}; committed cash = ${finance.committed_usd}.`));}
 if(value.calculation_association){result.append(node('p',value.calculation_association));grid(result,{'Calculation source time':value.calculation_input_times?.source_at,'Calculation receipt time':value.calculation_input_times?.received_at});}
 evidence(result,'Exact calculation payload',payload);
 if(value.historical_conditional_calculation){result.append(node('p','The previous numeric result assumed venue fee applicability that has not been established. It is retained as a historical conditional witness. Current net EV remains unavailable.'));evidence(result,'Historical conditional calculation · venue fee applicability unestablished',value.historical_conditional_calculation);}
 const retention=section(root,'6. Original-response retention & reproduction');
 grid(retention,{'Original response':value.original_response?.state,'Retention reason':value.original_response?.reason});evidence(retention,'Original-response capture metadata',value.original_response);retention.append(node('p',value.reproduction));evidence(retention,'Complete exported record',value);
}
async function inspect(row,button){
 opener=button;selection={token:frame.token,id:row.id,revision:row.revision};const selected=selection;
 $('input-title').textContent=row.title+' · '+(row.outcome||'Raw inputs');$('input-content').replaceChildren(node('p','Reading captured inputs…'));$('input-detail').showModal();
 const query=new URLSearchParams(selection);
 try{const value=await get('/api/research/input?'+query);if(selection===selected)detailView(value,query);}
 catch(error){if(selection===selected)$('input-content').replaceChildren(node('p',error.message));}
}
$('close-detail').onclick=()=>$('input-detail').close();
$('input-detail').addEventListener('close',()=>{const previous=selection;selection=null;if(previous?.exportUrl)URL.revokeObjectURL(previous.exportUrl);if(previous&&previous.token!==frame?.token)fetch('/api/research/read?token='+previous.token,{method:'DELETE',headers:{'Content-Type':'application/json'}});opener?.focus({preventScroll:true});});
$('catalog-filters').onsubmit=event=>{event.preventDefault();offset=0;load();};
$('clear').onclick=()=>{for(const id of Object.keys(fieldIds))$(id).value='';offset=0;load();};
$('refresh').onclick=()=>load();$('previous').onclick=()=>{if(busy)return;offset=Math.max(0,offset-50);load(true);};$('next').onclick=()=>{if(busy||!frame||frame.next_offset===null)return;offset=frame.next_offset;load(true);};
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
$('coverage').addEventListener('toggle',()=>{if($('coverage').open)coverage();});
function cohortResult(root,detail){
 root.replaceChildren();const value=detail.evaluation;
 grid(root,{Designation:value.designation,'Declared records':value.population_records,'Distinct events':value.distinct_events,'Scored records':value.scored_records,'Scored distinct events':value.scored_distinct_events,'Missing / excluded cases':json(value.status_counts),'Evaluation knowledge cutoff':value.as_of});
 if(value.policy_comparison?.length){const scroll=node('div',undefined,'catalog-scroll');root.append(scroll);table(scroll,['Recorded policy','Population records / events','Scored records / events','Missing / excluded','Mean Brier','Mean log loss'],value.policy_comparison.map(policy=>[policy.policy_version,`${policy.population_records} / ${policy.distinct_events}`,`${policy.scored_records} / ${policy.scored_distinct_events}`,json(policy.status_counts),policy.mean_brier,policy.mean_log_loss]));}
 evidence(root,'Frozen population, cases, calibration and correction history',detail);
}
async function cohorts(){const root=$('cohort-content');root.replaceChildren(node('p','Reading declared populations…'));try{const value=await get('/api/research/cohorts');root.replaceChildren();if(!value.cohorts.length)root.append(node('p','No research population has been declared. The operator CLI declares event/market/line horizons before capture; journal selections are separate.'));for(const item of value.cohorts){const row=node('div',undefined,'research-panel-row'),button=node('button',item.name||item.id),results=node('div'),download=node('a','Export frozen evidence','research-button');download.href='/api/research/cohorts?'+new URLSearchParams({id:item.id,export:'1'});download.download='predict-research-cohort.json';button.onclick=async()=>{button.disabled=true;try{cohortResult(results,await get('/api/research/cohorts?id='+encodeURIComponent(item.id)));}catch(error){results.replaceChildren(node('p',error.message));}finally{button.disabled=false;}};row.append(button,node('small',item.id),download,results);root.append(row);}}catch(error){root.replaceChildren(node('p','Research populations unavailable. '+error.message));}}
$('cohorts').addEventListener('toggle',()=>{if($('cohorts').open)cohorts();});
window.addEventListener('pagehide',()=>{if(frame)fetch('/api/research/read?token='+frame.token,{method:'DELETE',headers:{'Content-Type':'application/json'},keepalive:true});});
load();
