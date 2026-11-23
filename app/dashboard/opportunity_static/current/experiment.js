import {dateTime,venue,selection,odds} from './workspace-format.js';
import {referenceOnly,isTradingVenue} from './workspace-scope.js';
// Passive, revision-bound views of the collector-owned checkpoint experiment.
const $=id=>document.getElementById(id);
const known=value=>value===null||value===undefined||value===''?'Not recorded':String(value);
const json=value=>JSON.stringify(value??null,null,2);
const node=(tag,text,cls)=>{const item=document.createElement(tag);if(text!==undefined)item.textContent=text;if(cls)item.className=cls;return item;};
const label=value=>known(value).replaceAll('_',' ');
const reasons=values=>(values||[]).map(value=>typeof value==='string'?value:`${known(value.checkpoint)}: ${known(value.reason)}`).join('; ');
const snapshot=checkpoint=>checkpoint?.snapshot||checkpoint?.payload?.snapshot||checkpoint?.payload||checkpoint;
const initialSelection=new URLSearchParams(location.search);
let listing=null,pageOffset=Number(initialSelection.get('offset')||0),busy=false,selected=null,opener=null,suppressCloseURL=false,loadVersion=0;

function number(value){
 if(value===null||value===undefined||value==='')return null;
 const parts=String(value).split('/');
 const result=parts.length===2?Number(parts[0])/Number(parts[1]):Number(value);
 return Number.isFinite(result)?result:null;
}
function exactSign(value){
 if(value===null||value===undefined||value==='')return null;
 const numerator=String(value).split('/')[0];
 if(!/^[+-]?\d+(?:\.\d+)?$/.test(numerator))return null;
 const integer=BigInt(numerator.replace('.',''));
 return integer<0n?-1:integer>0n?1:0;
}
function percent(value){
 const n=number(value),sign=exactSign(value);
 if(n===null)return value===null||value===undefined?'Unavailable':String(value);
 if(sign===0)return '0.00% (exact zero)';
 return `${Math.abs(n*100)<.005?'≈':''}${sign===1?'+':''}${(n*100).toFixed(2)}%`;
}
function probability(value){const n=number(value);return n===null?'Unavailable':`${(n*100).toFixed(2)}%`;}
function gameTitle(value){return typeof value==='string'?value:value?.title||value?.game||value?.name||'Tracked game';}
function lineLabel(row){const line=row.line??row.identity?.line;return line==null?'':String(number(line)??line);}
function role(value){return value&&value.status&&value.status!=='unknown'?[label(value.status),value.source?label(value.source):null].filter(Boolean).join(' · '):'Main role not established';}
function coverageLabel(value,checkpoints={}){
 if(!value)return 'Coverage not recorded';
 if('early' in value||'late' in value)return ['early','late'].map(stage=>{const status=checkpointStatus(checkpoints[stage]);return `${stage==='early'?'Early':'Late'}: ${!value[stage]&&['Scheduled','Capturing'].includes(status.label)?status.label+' · '+status.detail:coverageLabel(value[stage])}`;}).join('; ');
 if(value.incomplete===true)return 'Incomplete returned scope';
 if(value.incomplete===false)return 'Returned request scope; market completeness unestablished';
 return label(value.state||value.status||value.scope);
}
function grid(root,values){const dl=node('dl',undefined,'research-detail-grid');for(const [key,value]of Object.entries(values).filter(([,value])=>value!==null&&value!==undefined&&value!==''))dl.append(node('dt',key),node('dd',known(value)));root.append(dl);return dl;}
function section(root,title){const item=node('section');item.append(node('h3',title));root.append(item);return item;}
function evidence(root,title,value,open=false){const item=node('details');item.open=open;item.append(node('summary',title),node('pre',json(value)));root.append(item);return item;}
function table(root,columns,rows){const scroll=node('div',undefined,'catalog-scroll'),value=node('table',undefined,'experiment-table'),head=node('thead'),tr=node('tr'),body=node('tbody');for(const column of columns)tr.append(node('th',column));head.append(tr);for(const cells of rows){const row=node('tr');for(const [index,content]of cells.entries()){const cell=node('td');cell.dataset.label=columns[index];if(content&&typeof content==='object'&&content.tagName)cell.append(content);else cell.append(node('span',known(content)));row.append(cell);}body.append(row);}value.append(head,body);scroll.append(value);root.append(scroll);return body;}
function stack(...values){const root=node('div');for(const [index,value]of values.entries())root.append(node(index===0?'strong':'small',known(value)));return root;}
async function get(url){const response=await fetch(url,{cache:'no-store'});const value=await response.json();if(!response.ok)throw Error(value?.error||value?.message||`Stored experiment read failed (${response.status})`);return value;}

const feeLabel=mode=>mode?(mode.enabled?'Fees enabled':'0 fees assumed'):'Original captured fee policy';
export function checkpointStatus(task={},capture=null,at=Date.now()){
 const payload=capture?.payload||capture,raw=task.state||payload?.state||payload?.status;
 if(payload?.captured_at||payload?.actual_at||raw==='captured')return {label:'Captured',detail:dateTime(payload?.received_at||payload?.captured_at||payload?.actual_at)};
 if(['claimed','capturing','running','in_progress'].includes(raw))return {label:'Capturing',detail:task.target_at?`Due ${dateTime(task.target_at)}`:''};
 if(['failed','refused','cancelled','missed','superseded_by_reschedule','expired'].includes(raw))return {label:label(raw==='expired'?'missed':raw),detail:label(task.last_reason||payload?.reason||'Capture unavailable')};
 const due=task.target_at||payload?.target_at,deadline=task.deadline_at||payload?.deadline_at;
 if(deadline&&new Date(deadline).getTime()<at)return {label:'Missed',detail:label(task.last_reason||payload?.reason||'Capture window closed without a receipt')};
 return due?{label:'Scheduled',detail:`Due ${dateTime(due)}`}:{label:'Not captured',detail:'Checkpoint timing not recorded'};
}
function taskFor(detail,stage){return detail?.checkpoint_status?.find(task=>task.checkpoint===stage)||detail?.checkpoints?.[stage]||{};}
function missingStage(detail,stage){const status=checkpointStatus(taskFor(detail,stage),detail?.[stage]);return status.label==='Captured'?'Selected exact line not returned at this captured checkpoint':`${status.label} · ${status.detail}`;}
function awaiting(detail,stage){return ['Scheduled','Capturing'].includes(checkpointStatus(taskFor(detail,stage),detail?.[stage]).label);}
function namedRow(row,detail){
 const result={...row.identity,...row},side=row.outcome||row.identity?.outcome;
 if(result.selection_label)return result;
 if(side==='home'||side==='away'){
  for(const stage of ['early','late']){const frozen=snapshot(detail?.[stage]),event=frozen?.event||{},source=frozen?.source_event||{};const name=source.teams?.[side]?.name||Object.entries(event.participants||{}).find(([,identity])=>identity===event[side])?.[0];if(name){result.selection_label=name;return result;}}
  result.selection_label=`${side==='home'?'Home':'Away'} team name unavailable`;
 }else if(side==='over'||side==='under')result.selection_label=side==='over'?'Over':'Under';
 return result;
}
function sourceCell(row,stage,detail){return row[stage]?`${odds(row[stage].price,row[stage].price_units)} · ${role(row[stage].main)}`:missingStage(detail,stage);}
function continuity(row,detail){const pending=['early','late'].filter(stage=>!row[stage]&&awaiting(detail,stage));if(pending.length)return pending.map(stage=>`${stage==='late'?'T−10':'Early'}: ${missingStage(detail,stage)}`).join('; ');return [label(typeof row.role_link==='string'?row.role_link:row.role_link?.relationship),reasons(row.missing_reasons)].filter(Boolean).join(' · ')||'Recorded in checkpoint evidence';}
function checkpointCell(value,task){
 if(!value){const status=checkpointStatus(task);return stack(status.label,status.label==='Captured'?'Selected exact line not returned at this checkpoint':status.detail);}

 const root=stack(odds(value.price,value.price_units),`Screening EV: ${percent(value.screen?.ev)}`,`Screen probability: ${probability(value.screen?.probability)}`,`Coherent EV: ${percent(value.coherent?.ev)}`,`Coherent probability: ${probability(value.coherent?.probability)}`);
 root.title=`Exact screening EV: ${known(value.screen?.ev)}; exact coherent EV: ${known(value.coherent?.ev)}`;
 if(value.fee_mode)root.append(node('small',feeLabel(value.fee_mode)));
 if(value.reason||value.screen?.reason)root.append(node('small',value.reason||value.screen.reason));
 root.append(node('small',value.available===true?'Source available':value.available===false?'Source unavailable':'Source availability unknown'));
 return root;
}
function identityCell(row){return stack(row.title||gameTitle(row.game),`${venue(row.book||row.identity?.book)} · ${label(row.family||row.identity?.family)} · ${label(row.period||row.identity?.period)}`,selection(namedRow(row)));}
function crossCell(value){return stack(`Screening: ${percent(value?.screen?.ev)}`,`Coherent: ${percent(value?.coherent?.ev)}`,value?.reason||value?.screen?.reason||'Early price, quantity, fees and cashflows retained');}
function caseRows(root,cases,onInspect,timing={}){
 const rows=cases.map(row=>{
  const button=node('button','Inspect comparison');button.type='button';button.dataset.case=row.id;button.onclick=()=>onInspect(row,button);
  const clocks=row.capture_timing||timing;
  const roles=stack(`Early: ${role(row.early?.main)}`,`Late: ${role(row.late?.main)}`,`Link: ${label(typeof row.role_link==='string'?row.role_link:row.role_link?.relationship)}`,`Early age: ${known(row.early?.source_age_seconds)}s · late age: ${known(row.late?.source_age_seconds)}s`,`Captured early: ${known(clocks.early_at)}`,`Late target: ${known(clocks.late_target)} · actual: ${known(clocks.late_at)}`,`Coverage: ${coverageLabel(clocks.coverage)}`);
  const lateStatus=checkpointStatus(clocks.checkpoints?.late);const scheduled=!row.late&&['Scheduled','Capturing'].includes(lateStatus.label);const transition=stack(scheduled?lateStatus.label:label(row.transition),scheduled?lateStatus.detail:row.incomplete?'Checkpoint or exact line unavailable':'Complete checkpoint pair');
  if(!scheduled&&row.missing_reasons?.length)transition.append(node('small',reasons(row.missing_reasons)));
  return [identityCell(row),checkpointCell(row.early,clocks.checkpoints?.early),checkpointCell(row.late,clocks.checkpoints?.late),transition,button];
 });
 return table(root,['Game / exact bet','Early checkpoint','T−10 checkpoint','Change / missing capture','Inspect'],rows);
}
function controls(){
 $('experiment-refresh').disabled=busy;$('experiment-context').disabled=busy;
 $('experiment-previous').disabled=busy||!listing||pageOffset===0;
 $('experiment-next').disabled=busy||!listing||listing.next_offset==null;
 $('experiment').setAttribute('aria-busy',String(busy));
}
function operation(value){
 const root=$('experiment-operation-content');root.replaceChildren();
 const status=value.status||{},storage=value.storage||{},attempts=Array.isArray(status.tasks)?status.tasks.reduce((count,item)=>count+Number(item.refusals||0),0):null;
 grid(root,{'Experiment policy':value.policy?.version||value.policy?.id||value.policy,'Recorded scheduling transition':value.scheduling_transition?.retired_at||value.scheduling_transition?.recorded_at,'Early checkpoint rule':value.policy?.early?.rule,'Late target seconds before start':value.policy?.late?.target_seconds_before_start,'Late window opens at target plus seconds':value.policy?.late?.window_start_offset_seconds,'Late window closes at target plus seconds':value.policy?.late?.window_end_offset_seconds,'Guarded postgame follow-up offsets (seconds)':value.policy?.outcomes?.offsets_seconds?.join(', '),'Tracked games':status.games??status.tracked_games,'Complete checkpoint games':status.complete_checkpoint_games,'Retention state':storage.state||(storage.no_automatic_eviction?'Bounded; unique evidence is not automatically evicted':null),'Retained bytes':storage.retained_bytes,'Allocated bytes including reservations':storage.allocated_bytes,'Experiment payload bytes':storage.experiment_payload_bytes,'Late-checkpoint reserved bytes':storage.late_reserved_bytes,'Byte cap':storage.byte_cap,'Remaining bytes':storage.remaining_bytes,'Measured mean completed-game payload bytes':storage.mean_complete_game_payload_bytes,'Estimated remaining complete games':storage.estimated_remaining_games,'Discovery refusal attempts':status.discovery_refusals,'Checkpoint refusal attempts':attempts??storage.refusals});
 evidence(root,'Declared checkpoint policy and timing tolerance',value.policy);
 evidence(root,'Transition from the daily one-hour research schedule',value.scheduling_transition);
 evidence(root,'Scheduled operation, requested/received coverage and refusals',value.status);
 evidence(root,'Bounded retention and measured operating runway',value.storage);
}
function renderListing(value){
 listing=value;const cases=(value.cases||[]).filter(item=>item.retain_case===true&&isTradingVenue(item.book||item.identity?.book)),games=value.games||[];
 const root=$('experiment-cases');root.replaceChildren();
 $('experiment-status').textContent=`${cases.length.toLocaleString()} retained cases on this game page · ${known(value.total_games??games.length)} games${$('experiment-context').checked?' tracked':' with retained cases'}. Captured read; refresh for new checkpoint evidence.`;
 $('experiment-policy').textContent=`Primary sign metric: conservative screening EV. Coherent measurements are labeled separately. Captured prices and clocks remain unchanged.`;
 if(cases.length)caseRows(root,cases.map(row=>({...row,capture_timing:games.find(item=>item.id===row.game_id)})),(row,button)=>inspectExperiment(row.game_id,row.game_revision||games.find(item=>item.id===row.game_id)?.revision,row.id,button));
 else root.append(node('p','No retained cases in this captured view. Show all tracked games to inspect checkpoint progress, missing inputs and the shared market context.'));
 const gameRoot=$('experiment-games');gameRoot.replaceChildren();
 if($('experiment-context').checked){
  for(const game of games){const row=node('div',undefined,'research-panel-row'),button=node('button','Inspect market context');button.type='button';button.dataset.game=game.id;button.onclick=()=>inspectExperiment(game.id,game.revision,null,button);row.append(node('strong',game.title||gameTitle(game)),node('small',`${known(game.league)} · starts ${dateTime(game.starts_at)}`),node('small',`Early: ${checkpointStatus(game.checkpoints?.early,game.early_at?{captured_at:game.early_at}:null).label} · T−10: ${checkpointStatus(game.checkpoints?.late,game.late_at?{captured_at:game.late_at}:null).label} · due ${dateTime(game.late_target)}`),node('small',`Retained cases: ${known(game.case_counts?.retained_cases??game.case_counts?.retained??game.retained_cases)} · ${coverageLabel(game.coverage,game.checkpoints)}`),button);gameRoot.append(row);}
 }
 const offset=value.offset??pageOffset,total=value.total_games??games.length;
 $('experiment-page').textContent=total?`Games ${offset+1}–${offset+games.length} of ${total}`:'No tracked games in this view';
 operation(value);
}
async function load(){
 const version=++loadVersion;busy=true;controls();$('experiment-status').textContent=listing?'Reading stored comparisons… Previous captured values remain visible.':'Reading scheduled checkpoint evidence…';
 const query=new URLSearchParams({limit:'10',offset:String(pageOffset)});if($('experiment-context').checked)query.set('include_context','1');
 try{const value=await get('/api/research/experiment?'+query);if(version!==loadVersion)return;renderListing(value);const current=new URLSearchParams(location.search);if(current.get('id')&&current.get('revision'))await inspectExperiment(current.get('id'),current.get('revision'),current.get('case'),null,{updateURL:false});}
 catch(error){if(version===loadVersion)$('experiment-status').textContent=`${listing?'Could not refresh. Displayed comparisons are last-known.':'Experiment evidence unavailable.'} ${error.message}`;}
 finally{if(version===loadVersion){busy=false;controls();}}
}
function checkpointTiming(root,name,checkpoint,task){
 const value=checkpoint?.payload||checkpoint;
 const panel=section(root,name);
 const status=checkpointStatus(task,value);panel.append(node('p',`${status.label} · ${status.detail}`));
 if(!value)return;
 grid(panel,{State:status.label,'Target time':value.target_at,'Window opens':value.window_start,'Window closes':value.deadline_at||value.window_end,'Actual capture time':value.captured_at||value.actual_at,'First observed by this experiment':value.experiment_first_observed_at||value.observed_at,'Discovery kind':value.discovery_kind,'Seconds remaining until start':value.seconds_to_start,'Minutes remaining at capture':number(value.seconds_to_start)===null?null:(number(value.seconds_to_start)/60).toFixed(2),'Receipt time':value.received_at,'Knowledge cutoff':value.known_at,'Persistence time':checkpoint.recorded_at||value.persisted_at,Reason:value.reason});
 const mode=value.fee_mode||snapshot(checkpoint)?.fee_mode;if(mode)grid(panel,{'Captured fee mode':feeLabel(mode),'Fee assumption':mode.assumption});
 const coverage=value.coverage||snapshot(checkpoint)?.coverage;
 if(coverage){const list=items=>Array.isArray(items)?items.join(', ')||'None recorded':null;
  grid(panel,{'Requested bookmakers':list(coverage.requested?.bookmakers),'Received bookmakers':list(coverage.received?.bookmakers),'Missing bookmakers':list(coverage.missing?.bookmakers),'Requested odd IDs':list(coverage.requested?.odd_ids),'Received odd IDs':list(coverage.received?.odd_ids),'Missing odd IDs':list(coverage.missing?.odd_ids),'Alternate lines requested':coverage.requested?.include_alt_lines,'Received quote count':coverage.received?.quotes,'Supported offer quote count':coverage.supported?.offer_quotes,'Supported reference quote count':coverage.supported?.reference_quotes,'Incomplete declared scope':coverage.incomplete,'Complete market established':coverage.complete_market,'Coverage scope':coverage.scope});
 }
 evidence(panel,'Requested, received, supported, missing and incomplete coverage',coverage);
 evidence(panel,'Immutable checkpoint and original-receipt dependencies',checkpoint);
}
function measurementEvidence(root,name,value,offer,detail,stage){
 const panel=section(root,name);
 if(!value){panel.append(node('p',detail?missingStage(detail,stage):'Not captured. No later inputs substituted.'));return;}
 grid(panel,{'Original offered price':value.price,'Price units':value.price_units,'Source available':value.available,'Screening probability':value.screen?.probability,'Screening exact EV':value.screen?.ev,'Screening policy':value.screen?.policy,'Screening reference book':value.screen?.reference_book,'Screening reason':value.screen?.reason,'Coherent probability':value.coherent?.probability,'Coherent exact EV':value.coherent?.ev,'Coherent policy':value.coherent?.policy,'Coherent reference book':value.coherent?.reference_book,'Coherent reason':value.coherent?.reason,'Main / alternate role':role(value.main),'Main-role authority':value.main?.authority,'Native book main authority':value.main?.native_book_main_authority,'Source time':value.times?.source_at,'Receipt time':value.times?.received_at,'Calculation time':value.times?.calculated_at,'Knowledge time':value.times?.known_at,'Persistence time':value.times?.persisted_at,'Source age at capture (seconds)':value.source_age_seconds,'Calculation version':value.calculation_version,'Missing-data reason':value.reason});
 const calculation=offer?.calculation_payload,fee=calculation?.fee;
 grid(panel,{'Fee mode':feeLabel(calculation?.fee_mode||offer?.fee_input?.fee_mode),'Committed capital (USD)':fee?.committed_usd,'Win-state net receipt (USD)':fee?.cashflows?.win?.net_receipt_usd,'Loss-state net receipt (USD)':fee?.cashflows?.loss?.net_receipt_usd,'Fee applicability':offer?.fee_input?.classification||fee?.reason});
 evidence(panel,'Original normalized input and identity mapping',offer?.record);
 evidence(panel,'Screening reference inputs and recorded pair',calculation?.reference||offer?.screen_reference);
 evidence(panel,'Coherent reference inputs and recorded pair',calculation?.coherent_probability||offer?.coherent_reference);
 evidence(panel,'Frozen fee, quantity, cashflow and rounding inputs',offer?.fee_input);
 evidence(panel,'Frozen calculation, cashflows and exact asserted results',calculation);
 evidence(panel,'Complete captured offer and measurement',{offer,measurement:value});
}
function caseEvidence(root,row,detail){
 const panel=section(root,'Exact bet and cross-checkpoint calculation');
 const pending=['early','late'].filter(stage=>!row[stage]&&awaiting(detail,stage));
 grid(panel,{'Exact bet ID':row.id,Book:venue(row.book),'Market family':row.family,Period:row.period,Selection:selection(namedRow(row,detail)),Transition:pending.length?pending.map(stage=>missingStage(detail,stage)).join('; '):label(row.transition),'Incomplete checkpoints':pending.length?null:row.incomplete,'Main / alternate continuity':typeof row.role_link==='string'?label(row.role_link):json(row.role_link),'Missing reasons':pending.length?null:reasons(row.missing_reasons)});
 evidence(panel,'Canonical identity and material settlement semantics',row.identity);
 measurementEvidence(panel,'Early offer with early references',row.early,snapshot(detail.early)?.offers?.[row.early?.offer_index],detail,'early');
 measurementEvidence(panel,'Late offer with late references',row.late,snapshot(detail.late)?.offers?.[row.late?.offer_index],detail,'late');
 const cross=section(panel,'Analytical diagnostic · early offer using the late probability reference');
 if(pending.length){cross.append(node('p',pending.map(stage=>missingStage(detail,stage)).join('; ')));evidence(cross,'Recorded analytical inputs',row.early_offer_late_reference);return;}
 grid(cross,{'Screening exact EV':row.early_offer_late_reference?.screen?.ev,'Screening probability':row.early_offer_late_reference?.screen?.probability,'Screening policy':row.early_offer_late_reference?.screen?.policy,'Coherent exact EV':row.early_offer_late_reference?.coherent?.ev,'Coherent probability':row.early_offer_late_reference?.coherent?.probability,'Coherent policy':row.early_offer_late_reference?.coherent?.policy,Reason:row.early_offer_late_reference?.reason||row.early_offer_late_reference?.screen?.reason});
 cross.append(node('p','This cross-checkpoint diagnostic is excluded from current opportunity eligibility and arbitrage. It preserves the early contract, original price, quantity, fees and state cashflows. Only the recorded probability reference changes.'));
 evidence(cross,'Exact cross-checkpoint inputs and reproduction result',row.early_offer_late_reference);
}

function svg(tag,attributes={},text){const item=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value]of Object.entries(attributes))item.setAttribute(key,String(value));if(text!==undefined)item.textContent=text;return item;}
function decimalPrice(value){
 const price=number(value?.price);if(price===null)return null;
 if(value.price_units==='american_odds')return price>0?1+price/100:price<0?1+100/-price:null;
 if(value.price_units==='decimal_odds')return price>1?price:null;
 if(value.price_units==='usd_per_contract'||value.price_units==='probability')return price>0?1/price:null;
 return null;
}
function plot(root,title,rows,metric,detail){
 const figure=node('figure',undefined,'experiment-plot'),caption=node('figcaption',title),canvas=svg('svg',{viewBox:'0 0 520 280',role:'img','aria-label':title});figure.append(caption,canvas);root.append(figure);
 const points=[];for(const row of rows){const x=number(row.line??row.identity?.line);if(x===null)continue;for(const stage of ['early','late']){const observation=row[stage],value=observation?metric(observation):null;if(!observation&&awaiting(detail,stage))continue;points.push({x,y:value,stage,observation,row});}}
 if(!points.length){figure.append(node('p','No observed numeric spread/total points for this selection. Moneyline and unavailable identities remain in the context table.'));return;}
 const xs=points.map(item=>item.x),ys=points.filter(item=>item.y!==null).map(item=>item.y);
 let xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=ys.length?Math.min(0,...ys):0,ymax=ys.length?Math.max(0,...ys):1;
 if(xmin===xmax){xmin-=.5;xmax+=.5;}if(ymin===ymax){ymin-=.5;ymax+=.5;}
 const px=x=>55+(x-xmin)/(xmax-xmin)*440,py=y=>205-(y-ymin)/(ymax-ymin)*175;
 canvas.append(svg('line',{x1:55,y1:205,x2:495,y2:205,class:'plot-axis'}),svg('line',{x1:55,y1:30,x2:55,y2:205,class:'plot-axis'}),svg('line',{x1:55,y1:py(0),x2:495,y2:py(0),class:'plot-zero'}));
 for(const x of [xmin,(xmin+xmax)/2,xmax])canvas.append(svg('text',{x:px(x),y:224,'text-anchor':'middle'},Number(x.toFixed(3)).toString()));
 for(const y of [ymin,(ymin+ymax)/2,ymax])canvas.append(svg('text',{x:48,y:py(y)+3,'text-anchor':'end'},Number(y.toFixed(3)).toString()));
 canvas.append(svg('text',{x:275,y:244,'text-anchor':'middle'},'Exact spread / total'),svg('text',{x:48,y:263,'text-anchor':'end'},'Missing'));
 let missing=0,reportedMain=0;
 for(const point of points){
  const cls='plot-'+point.stage,x=px(point.x),main=point.observation?.main?.status==='main'&&point.observation?.main?.source==='source_reported';
  const tip=`${point.stage} · line ${known(point.row.line)} · ${point.y===null?'Unavailable':point.y} · ${role(point.observation?.main)} · source ${known(point.observation?.times?.source_at)} · received ${known(point.observation?.times?.received_at)} · ${point.observation?.reason||point.observation?.screen?.reason||''}`;
  let marker;
  if(point.y===null){missing++;const shift=point.stage==='early'?-3:3;marker=svg('path',{d:`M${x+shift-3},255l6,6m-6,0l6,-6`,class:cls+' plot-missing','data-missing':'true'});}
  else if(main){reportedMain++;marker=svg('rect',{x:x-4,y:py(point.y)-4,width:8,height:8,class:cls,'data-main':'source_reported'});}
  else marker=svg('circle',{cx:x,cy:py(point.y),r:3.5,class:cls});
  marker.append(svg('title',{},tip));canvas.append(marker);
 }
 figure.append(node('p',`Early: hollow blue. Late: filled gold. Squares: source-reported main for this book. ${missing} missing observations shown in the separate strip; ${reportedMain} main markers. Observed points only.`,'research-muted'));
}
function rememberCase(row){if(!selected)return;selected.caseId=row.id;const q=new URLSearchParams(location.search);q.set('case',row.id);history.pushState(null,'',location.pathname+'?'+q);}
function contextSourceEvidence(root,row,detail){
 const panel=section(root,referenceOnly(row)?'Reference only · sportsbook source quote':row.reference_only?'Trading market context · numeric calculation unavailable':'Shared offer context · no separate case is created');
 grid(panel,{'Source quote / exact bet ID':row.id,Book:venue(row.book),'Market family':row.family,Period:row.period,Selection:selection(namedRow(row,detail)),'Book role':referenceOnly(row)?'Reference only':row.reference_only?'Trading market context':'Supported prediction market'});
 evidence(panel,'Recorded identity and source mapping',row.identity);
 for(const stage of ['early','late']){
  const value=row[stage],frozen=snapshot(detail[stage]);
  if(row.reference_only){
   const group=section(panel,`${label(stage)} reference-book observation`);
   if(!value){group.append(node('p',missingStage(detail,stage)));continue;}
   grid(group,{'Original price':value.price,'Price units':value.price_units,'Main / alternate role':role(value.main),'Native book authority':value.main?.native_book_main_authority,'Source time':value.times?.source_at,'Receipt time':value.times?.received_at,Available:value.available,Reason:value.reason||value.screen?.reason});
   evidence(group,'Original received bookmaker quote',frozen?.raw_quotes?.[value.raw_quote_index]);
  }else measurementEvidence(panel,`${label(stage)} shared offer`,value,frozen?.offers?.[value?.offer_index],detail,stage);
 }
}
function plots(root,context,detail){
 const panel=section(root,'Observed market context');
 panel.append(node('p','These points include shared negative/negative context without creating separate research cases. Reference-only books provide received prices and main roles, without execution EV claims. Missing observations are preserved; no fitted or extrapolated values are drawn.'));
 const controls=node('div',undefined,'experiment-controls');panel.append(controls);
 const select=(caption,id,values)=>{const labelNode=node('label',caption),input=node('select');input.id=id;for(const [value,text]of values){const option=node('option',text);option.value=value;input.append(option);}labelNode.append(input);controls.append(labelNode);return input;};
 const bookValues=[...new Set(context.map(row=>row.book||row.identity?.book).filter(Boolean))].sort();
 const books=select('Book','experiment-plot-book',bookValues.map(value=>[value,venue(value)]));
 const families=select('Market','experiment-plot-market',[['spread','Spread'],['total','Total'],['moneyline','Moneyline']]);
 const periods=select('Period','experiment-plot-period',[]);
 const outcomes=select('Outcome','experiment-plot-outcome',[]);
 const policies=select('Measurement','experiment-plot-policy',[['screen','Screening EV / probability'],['coherent','Coherent EV / probability']]);
 const chartRoot=node('div',undefined,'experiment-plots');panel.append(chartRoot);
 function render(changeOutcome=false){
  const bookMarket=context.filter(row=>(row.book||row.identity?.book)===books.value&&(row.family||row.identity?.family)===families.value);
  if(changeOutcome){const values=[...new Set(bookMarket.map(row=>row.period||row.identity?.period).filter(Boolean))].sort();periods.replaceChildren(...values.map(value=>{const option=node('option',label(value));option.value=value;return option;}));}
  const candidates=bookMarket.filter(row=>(row.period||row.identity?.period)===periods.value);
  if(changeOutcome){const values=[...new Set(candidates.map(row=>row.outcome||row.identity?.outcome).filter(Boolean))].sort();outcomes.replaceChildren(...values.map(value=>{const option=node('option',namedRow(candidates.find(row=>(row.outcome||row.identity?.outcome)===value)||{outcome:value},detail).selection_label||label(value));option.value=value;return option;}));}
  const rows=candidates.filter(row=>(row.outcome||row.identity?.outcome)===outcomes.value);chartRoot.replaceChildren();
  if(!rows.length){chartRoot.append(node('p','No observed exact bets for this book, market and outcome.'));return;}
  const scope=`${venue(books.value)} · ${label(families.value)} · ${label(periods.value)} · ${namedRow(rows[0],detail).selection_label||label(outcomes.value)}`,policy=policies.value;
  const sourceOnly=rows.every(row=>row.reference_only===true),sportsbookOnly=rows.every(row=>referenceOnly(row));
  if(!sourceOnly)plot(chartRoot,`${scope} · ${policy==='screen'?'Screening':'Coherent'} EV (%)`,rows,value=>{const n=number(value[policy]?.ev);return n===null?null:n*100;},detail);
  plot(chartRoot,`${scope} · Offered decimal price`,rows,decimalPrice,detail);
  if(!sourceOnly)plot(chartRoot,`${scope} · ${policy==='screen'?'Screening reference':'Coherent'} probability (%)`,rows,value=>{const n=number(value[policy]?.probability);return n===null?null:n*100;},detail);
  else chartRoot.append(node('p',sportsbookOnly?'Reference only: offered-price observations are shown. Trading EV and probability measurements are not asserted.':'Trading market context: offered-price observations are shown. Numeric calculation support is unavailable.'));
 }
 books.onchange=()=>render(true);families.onchange=()=>render(true);periods.onchange=()=>{const values=[...new Set(context.filter(row=>(row.book||row.identity?.book)===books.value&&(row.family||row.identity?.family)===families.value&&(row.period||row.identity?.period)===periods.value).map(row=>row.outcome||row.identity?.outcome).filter(Boolean))].sort();outcomes.replaceChildren(...values.map(value=>{const matching=context.find(row=>(row.book||row.identity?.book)===books.value&&(row.family||row.identity?.family)===families.value&&(row.period||row.identity?.period)===periods.value&&(row.outcome||row.identity?.outcome)===value);const option=node('option',namedRow(matching||{outcome:value},detail).selection_label||label(value));option.value=value;return option;}));render();};outcomes.onchange=()=>render();policies.onchange=()=>render();
 if(bookValues.length){const offer=context.find(row=>!row.reference_only);books.value=offer?.book||offer?.identity?.book||bookValues[0];const first=context.find(row=>(row.book||row.identity?.book)===books.value);families.value=first?.family||first?.identity?.family||'spread';policies.value='screen';render(true);}else chartRoot.append(node('p','No exact market context has been retained yet.'));
 const all=section(panel,'Every captured exact line');
 const contextEvidence=node('div');
 table(all,['Book / market / exact offer','Early source price / role','T−10 source price / role','Availability / continuity','Inspect source'],context.map(row=>{const button=node('button','Inspect context quote');button.type='button';button.dataset.context=row.id;button.onclick=()=>{rememberCase(row);contextEvidence.replaceChildren();contextSourceEvidence(contextEvidence,row,detail);contextEvidence.scrollIntoView?.({block:'start'});};return [`${venue(row.book)}${referenceOnly(row)?' (Reference only)':row.reference_only?' (Trading market context)':''} · ${label(row.family)} · ${selection(namedRow(row,detail))}`,sourceCell(row,'early',detail),sourceCell(row,'late',detail),continuity(row,detail),button];}));
 all.append(contextEvidence);
}
function mainLinks(root,value,context,detail){
 const panel=section(root,"Each book's main-line progression");
 panel.append(node('p','Roles include their recorded source authority. Inferred and unknown roles remain distinct from source-reported main lines. A reference book’s main line does not establish another book’s main line or native execution authority.'));
 const groups=Array.isArray(value)?value:Object.values(value||{}),byId=new Map(context.map(row=>[row.id,row]));
 if(!groups.length){panel.append(node('p','No source-reported per-book main-line links are available.'));return;}
 for(const group of groups){const name=[venue(group.book),label(group.family),label(group.period),namedRow(group,detail).selection_label].filter(Boolean).join(' · ');panel.append(node('h4',name||'Recorded book / market group'));
  const contextLine=id=>byId.has(id)?selection(namedRow(byId.get(id),detail)):'Exact selection not recorded';
  const mains=stage=>{if(awaiting(detail,stage))return missingStage(detail,stage);return (group[stage+'_main_ids']||[]).map(id=>`${contextLine(id)} (${label(byId.get(id)?.[stage]?.main?.source)})`).join(', ')||(group[stage+'_main_lines']||[]).map(line=>selection({...namedRow(group,detail),line})).join(', ')||'No source-designated main offer recorded';};
  const pending=['early','late'].filter(stage=>awaiting(detail,stage));
  grid(panel,{'Recorded early main offers':mains('early'),'Recorded late main offers':mains('late'),Movement:pending.length?pending.map(stage=>missingStage(detail,stage)).join('; '):typeof group.movement==='string'?label(group.movement):json(group.movement)});
  table(panel,['Exact offer','Early role / authority','T−10 role / authority','Relationship'],(group.links||[]).map(link=>[contextLine(link.id),byId.get(link.id)?.early?role(byId.get(link.id).early.main):missingStage(detail,'early'),byId.get(link.id)?.late?role(byId.get(link.id).late.main):missingStage(detail,'late'),pending.length?pending.map(stage=>missingStage(detail,stage)).join('; '):label(link.relationship)]));
 }
 evidence(panel,'Exact continuity links and source role authority',value);
}
async function prepareExport(root,selection){
 root.replaceChildren(node('p','Preparing the complete export at this captured revision…'));
 const query=new URLSearchParams({id:selection.id,revision:selection.revision,export:'1'});
 try{const value=await get('/api/research/experiment?'+query);if(selected!==selection)return;
  const url=URL.createObjectURL(new Blob([json(value)+'\n'],{type:'application/json'}));selection.exportUrl=url;
  const download=node('a','Export this captured game & all dependencies','research-button');download.href=url;download.download='predict-early-late-game.json';
  root.replaceChildren(download,node('small',`Captured revision ${selection.revision}. This complete download stays fixed while you inspect it.`));
 }catch(error){if(selected===selection)root.replaceChildren(node('p','Complete export unavailable. '+error.message,'experiment-notice'));}
}
function detailView(value,selection){
 const root=$('experiment-content');root.replaceChildren();const game=value.game||{},context=[...(value.context||[]),...(value.reference_context||[])].map(row=>namedRow(referenceOnly(row)?{...row,reference_only:true}:row,value)),cases=(value.cases||[]).filter(row=>row.retain_case===true&&isTradingVenue(row.book||row.identity?.book)).map(row=>namedRow(row,value));
 $('experiment-title').textContent=game.title||gameTitle(game);
 root.append(node('p',`Captured revision ${value.revision||selection.revision}`,'research-muted'));
 const download=node('div',undefined,'experiment-export');root.append(download);prepareExport(download,selection);
 grid(root,{'Game identity':game.id||selection.id,League:game.league,'Scheduled start':dateTime(game.starts_at),State:game.state||game.status,'Retained cases':cases.length,'Shared supported-offer context':(value.context||[]).length,'Reference-only quote context':(value.reference_context||[]).length,'Screening policy':value.policy_versions?.primary,'Coherent policy':value.policy_versions?.coherent,'Calculation version':value.policy_versions?.calculation,'Identity version':value.policy_versions?.identity});
 const selectedEvidence=node('div');root.append(selectedEvidence);
 const selectedCase=cases.find(row=>row.id===selection.caseId),selectedContext=context.find(row=>row.id===selection.caseId);if(selectedCase)caseEvidence(selectedEvidence,selectedCase,value);else if(selectedContext)contextSourceEvidence(selectedEvidence,selectedContext,value);
 const timing={checkpoints:Object.fromEntries((value.checkpoint_status||[]).map(task=>[task.checkpoint,task])),early_at:value.early?.captured_at,late_at:value.late?.captured_at,late_target:value.late?.target_at,coverage:{early:snapshot(value.early)?.coverage,late:snapshot(value.late)?.coverage}};
 const retained=section(root,'Retained exact-bet comparisons');if(cases.length)caseRows(retained,cases,row=>{rememberCase(row);selectedEvidence.replaceChildren();caseEvidence(selectedEvidence,row,value);selectedEvidence.scrollIntoView?.({block:'start'});},timing);else retained.append(node('p','No separate research case has positive screening EV at either checkpoint. Market context and capture failures remain below.'));
 checkpointTiming(root,'Early checkpoint · first observed by this experiment within 24 hours',value.early,value.checkpoint_status?.find(task=>task.checkpoint==='early'));
 checkpointTiming(root,'T−10 checkpoint',value.late,value.checkpoint_status?.find(task=>task.checkpoint==='late'));
 mainLinks(root,value.main_line_links,context,value);plots(root,context,value);
 const outcomes=section(root,'Sporting outcomes and probability evaluation');outcomes.append(node('p','Sporting outcomes, venue settlements and actual fills remain separate evidence streams. Movement analysis is available before outcomes arrive. Scores cover cases selected by positive screening EV at either checkpoint; multiple bets from one game are dependent.'));
 if(value.quality){grid(outcomes,{'Observed scoring scope':value.quality.scope,'Retained cases in scoring scope':value.quality.retained_cases});if(value.quality.reports?.some(item=>item.records>0))table(outcomes,['Checkpoint','Measurement policy','Scored records','Distinct events','Mean Brier'],value.quality.reports.filter(item=>item.records>0).map(item=>[label(item.checkpoint),label(item.policy),item.records,item.distinct_events,item.mean_brier]));else outcomes.append(node('p','No scored completed games in this captured view.'));}
 evidence(outcomes,'Sporting outcome observations and corrections',value.outcomes);evidence(outcomes,'Probability scoring, exclusions and observed-scope limitations',value.quality);
 evidence(root,'Schedule history, reschedules and current checkpoint status',{schedule_history:value.schedule_history,checkpoint_status:value.checkpoint_status});
 evidence(root,'Experiment retention, refused captures and runway',value.retention);
 evidence(root,'Complete captured comparison and reproduction metadata',value);
}
export async function inspectExperiment(id,revision,caseId,button,{updateURL=true}={}){
 if(!id||!revision){const status=$('experiment-status')||$('catalog-status');status.textContent='Captured game identity is unavailable; refresh stored data.';return;}
 if(updateURL&&location.pathname==='/experiments'){const query=new URLSearchParams(location.search);query.set('id',id);query.set('revision',revision);if(caseId)query.set('case',caseId);else query.delete('case');history.pushState(null,'','/experiments?'+query);}
 opener=button;if(selected?.exportUrl)URL.revokeObjectURL(selected.exportUrl);const selection={id,revision,caseId};selected=selection;
 $('experiment-title').textContent='Captured checkpoint comparison';$('experiment-content').replaceChildren(node('p','Reading captured game evidence…'));if(!$('experiment-detail').open)$('experiment-detail').showModal();
 try{const value=await get('/api/research/experiment?'+new URLSearchParams({id,revision}));if(value.revision!==revision)throw Error('Captured comparison revision differs; refresh comparisons.');if(selected===selection)detailView(value,selection);}
 catch(error){if(selected===selection)$('experiment-content').replaceChildren(node('p',error.message,'experiment-notice'));}
}
export function closeExperiment(){if($('experiment-detail')?.open){suppressCloseURL=true;$('experiment-detail').close();}}
$('experiment-close').onclick=()=>$('experiment-detail').close();
$('experiment-detail').addEventListener('close',()=>{if(selected?.exportUrl)URL.revokeObjectURL(selected.exportUrl);selected=null;opener?.focus({preventScroll:true});const suppress=suppressCloseURL;suppressCloseURL=false;if(!suppress&&location.pathname==='/experiments'){const q=new URLSearchParams(location.search);for(const key of ['id','revision','case'])q.delete(key);history.pushState(null,'','/experiments'+(q.size?'?'+q:''));}});
function saveListURL(){const q=new URLSearchParams();if($('experiment-context').checked)q.set('context','1');else q.set('context','0');if(pageOffset)q.set('offset',String(pageOffset));history.pushState(null,'','/experiments?'+q);}
if($('experiment')){
 if(initialSelection.has('context'))$('experiment-context').checked=initialSelection.get('context')==='1';
 $('experiment-refresh').onclick=()=>load();$('experiment-context').onchange=()=>{pageOffset=0;saveListURL();load();};
 $('experiment-previous').onclick=()=>{if(busy)return;pageOffset=Math.max(0,pageOffset-10);saveListURL();load();};
 $('experiment-next').onclick=()=>{if(busy||listing?.next_offset==null)return;pageOffset=listing.next_offset;saveListURL();load();};
 window.addEventListener('popstate',()=>{const q=new URLSearchParams(location.search);pageOffset=Number(q.get('offset')||0);$('experiment-context').checked=q.get('context')!=='0';if(!q.has('id'))closeExperiment();load();});
 load();
}
window.addEventListener('pagehide',()=>{if(selected?.exportUrl)URL.revokeObjectURL(selected.exportUrl);});
