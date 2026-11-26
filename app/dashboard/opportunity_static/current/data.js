import {marketRow,renderMarket,renderMarketInput} from './data-market.js';
import {dateTime,venue as bookName,percent,odds,selection} from './workspace-format.js';
import {referenceOnly,isTradingVenue,tradingContext} from './workspace-scope.js';
import {hasSavedSession,renderSavedSession} from './data-sessions.js';
import {renderSavedCapture} from './data-captures.js';
import {renderInput} from './data-evidence.js';
import {inspectExperiment,closeExperiment} from './experiment.js';
const $=id=>document.getElementById(id);
const fields={'reference-scope':'reference_scope',search:'search',provider:'provider',book:'original_bookmaker_id',sport:'sport',date:'date',family:'family',calculation:'calculation_status',age:'max_age_minutes',sort:'sort',view:'view'};
const node=(tag,text,cls)=>{const value=document.createElement(tag);if(text!==undefined)value.textContent=text;if(cls)value.className=cls;return value;};
const known=value=>value==null||value===''?'Not recorded':String(value);
const readable=value=>known(value).replaceAll('_',' ');
let frame=null,frameKey=null,selectedGame=null,displayedGameId=null,busy=false,loading=false,loadQueued=false,sequence=0,inputCleanup=null,savedCleanup=null,suppressInputClose=false,suppressExperimentClose=false;
const state=()=>new URLSearchParams(location.search);
const rowsPerPage=query=>['25','50','100'].includes(query.get('data_rows')) ? query.get('data_rows') : '50';
function link(text,query){const value=node('a',text,'research-button');value.href='/data?'+query;return value;}
function navigate(query,replace=false){history[replace?'replaceState':'pushState'](null,'','/data'+(query.size?'?'+query:''));window.dispatchEvent?.(new Event('predict:data-selection'));load();}
function filters(){const query=new URLSearchParams();for(const [id,key]of Object.entries(fields))if(id!=='view'&&$(id).value.trim())query.set(key,$(id).value.trim());if($('alternates').checked)query.set('include_alternates','1');return query;}
function sync(){
 const query=state();
 const legacy=['id','bet_id','quote_key','line','game_key','bet'].some(key=>query.has(key));
 const historyView=query.get('view')==='history'||Boolean(query.get('provider')&&query.get('provider')!=='sportsgameodds')||query.get('original_bookmaker_id')&&!query.get('market');
 if(historyView&&!query.get('view'))query.set('view','history');
 if(!query.has('reference_scope'))query.set('reference_scope',legacy||historyView?'all':'selected');
 if(query.get('provider')&&query.get('provider')!=='sportsgameodds')query.set('reference_scope','all');
 history.replaceState(null,'','/data?'+query);
 for(const [id,key]of Object.entries(fields))$(id).value=query.get(key)||'';
 if(!query.has('sport')&&query.has('league'))$('sport').value=query.get('league');
 $('alternates').checked=query.get('include_alternates')==='1';
 $('sort').value=query.get('sort')||'ev_desc';
 $('data-rows').value=rowsPerPage(query);
 $('data-view').value=query.get('view')||'';
 $('provider').placeholder=historyView?'All retained sources':'SportsGameOdds';
 if(!query.has('event_id')&&query.has('source_event'))query.set('event_id',query.get('source_event'));
 return query;
}
function scopeSummary(scope){const provider=$('provider').value,historical=$('reference-scope').value==='all';$('reference-summary').textContent=provider&&provider!=='sportsgameodds'?`Historical ${provider} evidence. Active collection uses SportsGameOdds; original saved source identities stay inspectable.`:!provider&&historical?'Stored observations across retained sources.':historical?'SportsGameOdds · all retained sportsbook reference observations. Historical inputs keep their original capture scope.':`SportsGameOdds · four trading markets, ${scope?.books?.length||10} sportsbook references.`;if(scope?.books){const books=[...scope.books.map(item=>[item.id,item.label]),...(scope.trading_venues||[]).map(id=>[({polymarket_us:'polymarket',prophetx:'prophetexchange'})[id]||id,id])];$('books').replaceChildren(...books.map(([id,label])=>{const option=node('option');option.value=id;option.label=label;return option;}));}}
function feeSummary(mode){$('fee-mode-summary').textContent=mode?(mode.enabled?'New calculations: fees enabled · captures keep their recorded fee assumption.':'New calculations: Fees OFF · captures keep their recorded fee assumption.'):'Each retained calculation keeps its captured fee assumption.';}
function controls(){for(const id of ['apply','clear','refresh'])$(id).disabled=busy;$('previous').disabled=busy||!frame||Number(state().get('offset')||0)===0;$('next').disabled=busy||!frame||frame.next_offset==null;$('catalog').setAttribute('aria-busy',String(busy));}
async function get(url,timeout=15000){const response=await fetch(url,{cache:'no-store',signal:AbortSignal.timeout(timeout)});const value=await response.json().catch(()=>null);if(!response.ok||!value){const error=Error(value?.error||value?.message||`Stored read failed (${response.status})`);error.status=response.status;error.snapshotExpired=response.status===422&&/^Catalog snapshot expired(?: or filters changed)?;/.test(error.message);throw error;}return value;}
function lines(cell,...values){for(const [index,value]of values.filter(value=>value!==null&&value!==undefined&&value!=='').entries())cell.append(node(index===0?'strong':'small',known(value)));}
function cell(tr,title,...values){const item=node('td');item.dataset.label=title;lines(item,...values);tr.append(item);return item;}
function gameRow(game){const tr=node('tr');tr.dataset.game=game.id;cell(tr,'Game / start',game.title,`${known(game.sport)} · ${dateTime(game.start_at||game.starts_at)}`,game.identity_status==='source_local'?'Source-local game · identity unconfirmed':'');const trading=game.trading_books||(game.books||[]).filter(id=>isTradingVenue(id)||tradingContext(id)),references=game.reference_books||(game.books||[]).filter(id=>!isTradingVenue(id)&&!tradingContext(id));cell(tr,'Trading markets',trading.length?trading.map(bookName).join(', '):'No trading prices captured',(game.markets||game.families||[]).map(readable).join(', '));const refCell=cell(tr,'Sportsbook references',references.length?`${references.length} sportsbooks`:'No reference prices captured');if(references.length){const books=node('details');books.append(node('summary','View books'),node('p',references.map(bookName).join(', ')));refCell.append(books);}const counts=game.calculation_counts||{},best=percent(game.best_net_ev_percent);cell(tr,'Calculations','Historical calculation context',`${counts.positive||0} positive · ${counts.negative||0} negative · ${counts.unavailable||0} unavailable`,`${game.records} prices · received ${dateTime(game.latest_received_at)}`,game.experiment?'Checkpoint comparison available':'');const query=state();query.set('game',game.id);query.set('token',frame.token);for(const key of ['bet','revision','capture','record_offset'])query.delete(key);const open=link('Open game',query);open.onclick=event=>{if(event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();if(!busy)navigate(query);};cell(tr,'Open').append(open);return tr;}
function quoteRow(row){const tr=node('tr');tr.dataset.record=row.id;cell(tr,'Book / source',bookName(row.original_bookmaker_id),row.provider);cell(tr,'Market / exact bet',`${row.family} · ${row.period}`,selection(row),`Role: ${readable(row.main_role)}`);cell(tr,'Source price',row.price==null?(row.kind==='raw'?'Inspect raw values':'Price unavailable'):odds(row.price,row.price_units),row.available===false?`Unavailable: ${readable(row.availability_reason)}`:'');cell(tr,'Observation times',`Source: ${dateTime(row.times.source_at)}`,`Received: ${dateTime(row.times.received_at)}`);const reference=referenceOnly(row),context=tradingContext(row),c=cell(tr,'Calculation',reference?'Reference only':context?'Trading market · calculation unavailable':percent(row.calculation.net_ev_percent)||readable(row.calculation.status),reference?'Sportsbook source price':context?'Existing numeric integration unavailable':row.calculation.reason?readable(row.calculation.reason):percent(row.calculation.net_ev_percent));if(!reference){c.className='catalog-status-'+row.calculation.status;if(row.fee_mode)c.append(node('small',row.fee_mode.enabled?'Fees included':'0 fees assumed'));}const button=node('button','Inspect exact observation');button.type='button';button.onclick=()=>{const q=state();q.set('bet',row.id);q.set('revision',row.revision);q.set('token',frame.token);q.set('capture','latest');navigate(q);};cell(tr,'Inspect').append(button);return tr;}
function table(root,columns,rows){const scroll=node('div',undefined,'catalog-scroll'),value=node('table',undefined,'catalog-table'),head=node('thead'),tr=node('tr'),body=node('tbody');for(const title of columns)tr.append(node('th',title));head.append(tr);body.replaceChildren(...rows);value.append(head,body);scroll.append(value);root.append(scroll);return body;}
function checkpointLink(game,caseId){if(!game.experiment)return null;const q=state();q.set('game',game.id);q.set('capture','checkpoints');q.delete('bet');q.delete('revision');if(caseId)q.set('case',caseId);else q.delete('case');const a=link(caseId?'Compare this exact bet at first observation / T−10':'Inspect first observation / T−10',q);a.onclick=event=>{if(event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();navigate(q);};return a;}
function renderGame(value,query){
 const game=value.game||selectedGame;selectedGame=game;$('game-detail').hidden=false;$('game-title').textContent=game?.title||'Selected game';const root=$('game-content');root.replaceChildren();
 if(game&&game.id!==displayedGameId){displayedGameId=game.id;$('game-title').tabIndex=-1;$('game-title').focus({preventScroll:true});$('game-detail').scrollIntoView({block:'start'});}
 if(!game){root.append(node('p','This game is absent from the captured filters. Clear filters or refresh stored data.'));return;}
 $('catalog').hidden=true;$('game-pagination').hidden=true;
 root.append(node('p',`${known(game.sport)} · ${dateTime(game.start_at||game.starts_at)}`));
 const identity=node('details');identity.append(node('summary','Source identity and stored read'),node('p',`${readable(game.identity_status)} · ${game.source_events?.map(item=>`${item.provider}: ${item.event_id}`).join('; ')||'No source identity retained'}`));root.append(identity);
 const actions=node('div',undefined,'catalog-actions'),capture=checkpointLink(game);if(capture)actions.append(capture);root.append(actions);
 root.append(node('h3','Received observations'));
 table(root,['Book / source','Market / exact bet','Source price','Observation times','Calculation','Inspect'],(value.rows||[]).map(quoteRow));
 if(!value.rows?.length)root.append(node('p','No current source observations match. Frozen experiment evidence remains available when retained.'));
 const paging=node('nav',undefined,'catalog-pagination');paging.setAttribute('aria-label','Game observation pages');const current=Number(query.get('record_offset')||0);for(const [title,target]of [['Previous observations',Math.max(0,current-Number(rowsPerPage(query)))],['Next observations',value.next_offset]]){const button=node('button',title);button.disabled=target==null||title.startsWith('Previous')&&current===0;button.onclick=()=>{const q=state();q.set('record_offset',String(target));q.delete('bet');q.delete('revision');navigate(q);};paging.append(button);}paging.insertBefore(node('span',value.total?`${current+1}–${current+(value.rows||[]).length} of ${value.total}`:'No latest records'),paging.lastChild);root.append(paging);
}
async function inspectInput(query,version){
 const id=query.get('bet');if(!id)return;if(!query.get('revision')){$('catalog-status').textContent='The saved observation needs its exact revision. Open its game and select the retained observation again.';return;}
 $('input-title').textContent='Exact captured observation';$('input-content').replaceChildren(node('p','Reading captured source and calculation…'));if(!$('input-detail').open)$('input-detail').showModal();
 try{const value=await get('/api/research/input?'+new URLSearchParams({token:frame.token,id,revision:query.get('revision'),...(query.get('game')?{game_id:query.get('game')}:query.get('game_key')?{game_id:'canonical:'+query.get('game_key')}:{})}));if(version!==sequence)return;inputCleanup?.();inputCleanup=renderInput($('input-content'),value);$('input-title').textContent=`${value.title} · ${selection(value)}`;const capture=checkpointLink(selectedGame||{},value.checkpoint_bet_id);if(capture)$('input-content').prepend(capture);}
 catch(error){if(version===sequence)$('input-content').replaceChildren(node('p',error.message+' The saved exact selection has not been replaced with another quote.'));}
}
// One navigation read at a time. Back keeps only the newest pending selection.
function workbenchView(){return ['pulls','checkpoints','populations','mens-d1','tables'].includes(state().get('evidence'));}
function load(){const version=++sequence;if(workbenchView()){loadQueued=false;return;}if(loading){loadQueued=true;return;}return runLoad(version);}
async function runLoad(version){
 loading=true;const query=sync();feeSummary(null);busy=true;controls();$('catalog-status').textContent='Reading stored data…';$('game-detail').hidden=true;selectedGame=null;
 $('catalog').hidden=Boolean(query.get('game')||query.get('game_key'));$('game-pagination').hidden=$('catalog').hidden;
 const historical=Boolean(query.get('view')==='history'||query.get('game')||query.get('game_key')||query.get('bet'));document.querySelectorAll('#catalog th').forEach((heading,index)=>heading.textContent=(historical?['Game / start','Trading markets','Sportsbook references','Historical evidence','Open','']:['Game / start','Market / exact offer','Venue / odds','Screening EV','Capture / references','Offers'])[index]);
 if(!query.get('offer')&&!query.get('bet')&&!query.get('saved_bet')&&!((query.has('result_id')||query.has('game_capture')||query.has('dataset'))&&(query.has('id')||query.has('bet_id')||query.has('quote_key')||query.has('selection')||query.has('line')))&&!(hasSavedSession(query)&&query.get('contract'))&&$('input-detail').open){suppressInputClose=true;$('input-detail').close();}if(query.get('capture')!=='checkpoints'&&$('experiment-detail').open){suppressExperimentClose=true;closeExperiment();}
 try{
  if(hasSavedSession(query)){
   savedCleanup?.();$('game-detail').hidden=false;$('game-title').textContent='Saved session';$('catalog-rows').replaceChildren();$('catalog-status').textContent='Inspecting verified saved session evidence';$('catalog-snapshot').textContent='This selection reads source inputs at its saved cutoff, with no new calculations.';$('page').textContent='Saved session';$('reference-summary').textContent='Retained historical session evidence keeps its original source scope and cutoff.';frame=null;
   savedCleanup=await renderSavedSession($('game-content'),query,{inspectRoot:$('input-content'),inspectTitle:$('input-title'),dialog:$('input-detail'),isCurrent:()=>version===sequence,onSelect:contract=>{const q=state();q.set('contract',contract);history.pushState(null,'','/data?'+q);}});return;
  }
  if(query.has('result_id')||query.has('game_capture')||query.has('dataset')){
   savedCleanup?.();$('game-detail').hidden=false;$('game-title').textContent='Saved capture';$('catalog-rows').replaceChildren();$('catalog-status').textContent='Inspecting retained capture evidence';$('catalog-snapshot').textContent='This selection reads its saved observation, with original source clocks.';$('page').textContent='Saved capture';$('reference-summary').textContent='Retained historical capture evidence keeps its original source scope.';frame=null;
   savedCleanup=await renderSavedCapture($('game-content'),query,{inspectRoot:$('input-content'),inspectTitle:$('input-title'),dialog:$('input-detail'),isCurrent:()=>version===sequence,onSelect:id=>{const q=state();q.set('saved_bet',id);history.pushState(null,'','/data?'+q);}});return;
  }
  savedCleanup?.();savedCleanup=null;
  const legacy=Boolean(query.get('view')==='history'||query.get('game')||query.get('game_key')||query.get('bet')||['bet_id','quote_key','id','line'].some(key=>query.has(key)));
  const q=filters();if(legacy){q.delete('sort');q.delete('include_alternates');}if(query.get('event_id'))q.set('event_id',query.get('event_id'));q.sort();const limit=rowsPerPage(query),key=(legacy?'games:':'markets:')+q.toString()+':'+limit,offset=Number(query.get('offset')||0);q.set('offset',String(offset));q.set('limit',limit);const token=query.get('token');
  async function readGames(useToken){const request=new URLSearchParams(q);if(useToken&&token)request.set('token',token);else if(frame?.token)request.set('release',frame.token);return get((legacy?'/api/research/games?':'/api/research/markets?')+request);}
  let value;if(token&&frame?.token===token&&frameKey===key&&frame.offset===offset)value=frame;else{try{value=await readGames(true);}catch(error){if(!token||!error.snapshotExpired)throw error;value=await readGames(false);}}
  if(version!==sequence)return;
  function showCatalog(){frame=value;frameKey=key;feeSummary(value.fee_mode);window.predictDataPage=value;scopeSummary(value.reference_scope);const current=state();current.set('token',value.token);history.replaceState(null,'','/data?'+current);
   $('catalog-rows').replaceChildren(...value.rows.map(row=>legacy?gameRow(row):marketRow(row,current,q=>{if(!busy)navigate(q);})));if(!query.has('game')&&!query.has('game_key')&&displayedGameId){const row=[...$('catalog-rows').children].find(row=>row.dataset.game===displayedGameId);row?.querySelector('a')?.focus({preventScroll:true});row?.scrollIntoView({block:'center'});displayedGameId=null;}
   $('catalog-status').textContent=`${value.total.toLocaleString()} ${legacy?(value.total===1?'game':'games'):(value.total===1?'market':'markets')}${query.get('calculation_status')?' · '+readable(query.get('calculation_status'))+' EV filter':''}`;
   $('catalog-snapshot').textContent=`${legacy?'Historical source evidence':'Stored comparisons'} as of ${dateTime(value.captured_at)}.${legacy?' This view does not establish current snapshot eligibility.':' Refresh to read newer captures.'}`;
   $('page').textContent=value.total?`${value.offset+1}–${value.offset+value.rows.length} of ${value.total}`:'No market comparisons match these filters.';
  }
  showCatalog();
  if(query.get('market')){
   const request=new URLSearchParams({token:value.token,market_id:query.get('market'),pull_id:query.get('pull')||''});
   if(query.get('offer')){request.set('offer_id',query.get('offer'));request.set('revision',query.get('revision')||'');}
   let detail;try{detail=await get('/api/research/market?'+request);}catch(error){if(!error.snapshotExpired)throw error;value=await readGames(false);if(version!==sequence)return;showCatalog();request.set('token',value.token);detail=await get('/api/research/market?'+request);}
   if(version!==sequence)return;$('game-detail').hidden=false;$('game-title').textContent=detail.row.title+' · '+readable(detail.row.family);$('close-game').textContent='Back to markets';
   renderMarket($('game-content'),detail,{positive:query.get('calculation_status')==='positive',includeAlternates:query.get('include_alternates')==='1',onSelect:offer=>{const next=state();next.set('offer',offer.id);next.set('revision',offer.revision);next.set('pull',detail.row.pull_id);navigate(next);},onCapture:capture=>{const next=state();next.set('market',capture.market_id||detail.row.id);next.set('pull',capture.pull_id);next.delete('offer');next.delete('revision');navigate(next);}});
   if(query.get('offer')){$('input-title').textContent='Exact headline offer';inputCleanup?.();inputCleanup=renderMarketInput($('input-content'),detail);if(!$('input-detail').open)$('input-detail').showModal();}
   else $('game-detail').scrollIntoView({block:'start'});
   return;
  }
  const legacyKey=['bet_id','quote_key','id','line'].find(key=>query.has(key));
  if(legacyKey&&!query.get('bet')){
   const lookup=filters();if(query.get('event_id'))lookup.set('event_id',query.get('event_id'));lookup.set('token',value.token);lookup.set('limit','50');lookup.set(legacyKey==='bet_id'||legacyKey==='line'?'exact_bet_id':'contract_id',query.get(legacyKey));
   const resolved=await get('/api/research/catalog?'+lookup);if(version!==sequence)return;
   if(resolved.rows?.length===1){const row=resolved.rows[0],next=state();next.set('game',row.game_id);next.set('provider',row.provider);next.set('bet',row.id);next.set('revision',row.revision);for(const key of ['bet_id','quote_key','id','line'])next.delete(key);navigate(next,true);return;}
   if(resolved.rows?.length){$('catalog-status').textContent+=' Saved selection has several retained source observations; inspect an exact record below.';selectedGame=resolved.game||{title:'Saved exact bet observations',sport:resolved.rows[0].sport,identity_status:'separate source observations',records:resolved.rows.length};renderGame(resolved,query);return;}
   $('catalog-status').textContent+=' The bookmarked exact observation is no longer in current storage; no substitute has been selected.';
  }
  let game=query.get('game');if(!game&&query.get('game_key'))game='canonical:'+query.get('game_key');
  if(game){const gameQuery=filters();if(query.get('event_id'))gameQuery.set('event_id',query.get('event_id'));Object.entries({token:value.token,game_id:game,offset:query.get('record_offset')||'0',limit}).forEach(([k,v])=>gameQuery.set(k,v));let detail;
   try{detail=await get('/api/research/game?'+gameQuery);}catch(error){if(!error.snapshotExpired)throw error;value=await readGames(false);if(version!==sequence)return;showCatalog();gameQuery.set('token',value.token);detail=await get('/api/research/game?'+gameQuery);}
   if(version!==sequence)return;selectedGame=detail.game||value.rows.find(row=>row.id===game);renderGame(detail,query);if(query.get('capture')==='checkpoints'&&selectedGame?.experiment){const e=selectedGame.experiment;await inspectExperiment(e.id,e.revision,query.get('case'),null,{updateURL:false});}}
  await inspectInput(query,version);

 }catch(error){if(version===sequence){const message=error.status===429||error.status===503?'Stored reads are busy. Use Refresh data to try again.':error.message;$('catalog-status').textContent='Stored data could not load. '+message;if(query.get('offer')){$('input-content').replaceChildren(node('p',message+' The exact selection has not been substituted.'));if(!$('input-detail').open)$('input-detail').showModal();}if(query.get('market')||query.get('game')||query.get('game_key')){$('game-detail').hidden=false;$('game-title').textContent='Game could not load';$('game-content').replaceChildren(node('p',message));}else if(frame)$('catalog-status').textContent+=' The table below is the last successful read.';}}
 finally{loading=false;if(loadQueued){loadQueued=false;runLoad(sequence);}else{busy=false;controls();}}
}
$('catalog-filters').onsubmit=event=>{
 event.preventDefault();
 const q=filters(), previous=state();
 if($('data-rows').value!=='50')q.set('data_rows',$('data-rows').value);
 if($('data-view').value)q.set('view',$('data-view').value);
 if(previous.get('event_id')&&q.get('search')===previous.get('search'))q.set('event_id',previous.get('event_id'));
 if(q.get('provider')&&q.get('provider')!=='sportsgameodds')q.set('reference_scope','all');
 navigate(q);
};
$('clear').onclick=()=>navigate(new URLSearchParams());$('refresh').onclick=()=>{const q=state();q.delete('token');navigate(q,true);};
for(const [id,direction]of [['previous',-1],['next',1]])$(id).onclick=()=>{const q=state(),offset=Number(q.get('offset')||0);q.set('offset',String(direction>0?frame.next_offset:Math.max(0,offset-Number(rowsPerPage(q)))));for(const key of ['market','pull','offer','game','bet','revision','capture','record_offset'])q.delete(key);navigate(q);};
$('close-game').onclick=()=>{const q=state();for(const key of ['market','pull','offer','game','game_key','bet','revision','capture','record_offset','result_id','game_capture','dataset','saved_bet','selection','line','id','bet_id','quote_key','session','hash','cutoff','contract','candidate','reference','quantity','scenario','probability','basis','rule_version'])q.delete(key);navigate(q);};
$('close-detail').onclick=()=>$('input-detail').close();
$('input-detail').addEventListener('close',()=>{inputCleanup?.();inputCleanup=null;if(suppressInputClose){suppressInputClose=false;return;}const q=state();for(const key of ['offer','bet','revision','saved_bet','selection','line','id','bet_id','quote_key','contract'])q.delete(key);if(!hasSavedSession(q))q.delete('capture');history.pushState(null,'','/data?'+q);});
$('experiment-detail').addEventListener('close',()=>{if(suppressExperimentClose){suppressExperimentClose=false;return;}const q=state();if(q.get('capture')==='checkpoints'){q.delete('capture');q.delete('case');history.pushState(null,'','/data?'+q);}});
window.addEventListener('pagehide',()=>{if(frame?.token)fetch('/api/research/read?token='+encodeURIComponent(frame.token),{method:'DELETE',headers:{'Content-Type':'application/json'},keepalive:true});});
window.addEventListener('popstate',load);
load();
