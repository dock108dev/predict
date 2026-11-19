import {journalAction} from './bet-journal-actions.js';
import {bookName,venues} from './pregame-labels.js';
import {priceDisplay,hasVenuePrice} from './pregame-prices.js';
import {addMath} from './pregame-math.js';
import {rankingCatalog} from './pregame-ranking.js';
import {freshness,freshnessText,payoutExample,feeRows} from './pregame-evidence.js';
const $=id=>document.getElementById(id);
const initial=new URLSearchParams(location.search), browse=location.pathname==='/browse-odds'||location.pathname==='/game';
const gameView=location.pathname==='/game', gameBoard=location.pathname==='/browse-odds'&&!initial.has('bet_id')&&!initial.has('id')&&!initial.has('line')&&!initial.has('quote_key');
let gameSequence=0,gameReturnKey,comparisonTrigger,gameTimer,activeComparison;
let offset=0, total=0, cursor='', refreshTimer, feedbackTimer, running=false, checking=false, lastGood=null, sequence=0, comparisonSequence=0, inspectionTimer, comparisonReturnId,boardController,gameController,lastRendered,displayedQuery;
const dialogReturns=new Map(),lockProperties=['position','top','left','width'];let lockedPage;
function showDialog(dialog,trigger=document.activeElement){
 const parent=trigger?.closest('dialog');dialogReturns.set(dialog,{trigger,parent,parentScroll:parent?.querySelector('#game-content')?.scrollTop||0});
 if(!lockedPage){lockedPage={x:scrollX,y:scrollY,style:document.body.getAttribute('style'),properties:lockProperties.map(name=>[name,document.body.style.getPropertyValue(name),document.body.style.getPropertyPriority(name)])};Object.assign(document.body.style,{position:'fixed',top:-scrollY+'px',left:-scrollX+'px',width:'100%'});}
 dialog.showModal();
}
function restoreDialog(dialog,fallback){
 const saved=dialogReturns.get(dialog);dialogReturns.delete(dialog);
 const eligible=target=>target?.isConnected&&(!target.closest('dialog')||target.closest('dialog').open);
 const target=eligible(saved?.trigger)?saved.trigger:fallback;
 if(!document.querySelector('dialog[open]')&&lockedPage){const page=lockedPage;lockedPage=null;for(const [name,value,priority]of page.properties){if(value)document.body.style.setProperty(name,value,priority);else document.body.style.removeProperty(name);}if(page.style===null&&!document.body.style.length)document.body.removeAttribute('style');scrollTo(page.x,page.y);}
 const restore=()=>{target?.focus({preventScroll:true});if(saved?.parent?.open)saved.parent.querySelector('#game-content').scrollTop=saved.parentScroll;};restore();requestAnimationFrame(restore);
}
const filters=$('filters');
const rankingSelect=$('ranking'),rankingKey='predict-opportunity-ranking-v1';
const rankingMethods=rankingCatalog.methods;
rankingSelect.replaceChildren(...Object.entries(rankingMethods).map(([key,info])=>{const option=node('option',info.label);option.value=key;return option;}));
let savedRanking;try{savedRanking=localStorage.getItem(rankingKey);}catch(e){}
rankingSelect.value=Object.hasOwn(rankingMethods,initial.get('sort'))?initial.get('sort'):Object.hasOwn(rankingMethods,savedRanking)?savedRanking:rankingCatalog.default;
let appliedRanking=rankingSelect.value;
function rankInfo(row){return row.ranking||{...rankingMethods[appliedRanking],display:'—'};}
function rankHeading(){const {label,column,unit}=rankingMethods[appliedRanking];$('ranking-column').replaceChildren(node('span',column.toUpperCase()),node('small',unit,'ranking-unit'));$('ranking-column').setAttribute('aria-label',label+' ('+unit+')');}
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function pick(row){const s=row.selection;const team=row.selection_label||(s.participant||'').split(':').pop();let line=s.signed_line||'';if(line.includes('/')){const [a,b]=line.split('/');line=String(Number(a)/Number(b));}if(row.family==='total')return `${s.predicate==='over'?'Over':'Under'} ${line}`;return `${team}${row.family==='spread'?` ${Number(line)>0?'+':''}${line}`:' to win'}`;}

function referenceQuote(row){return row.reference?.prices?.find(p=>p.side===row.reference.selected_outcome);}
function referencePrice(row){return referenceQuote(row)?.price_american ?? 'Unavailable';}
function ticket(row,compare=true){
 const article=node('article',undefined,'ticket board-row');
 const date=new Date(row.kickoff),opts={timeZone:'America/New_York'};
 article.append(node('div',row.league,'league-cell'));
 const start=node('div',undefined,'start-cell');start.append(node('strong',date.toLocaleTimeString('en-US',{...opts,hour:'numeric',minute:'2-digit'})),node('span',date.toLocaleDateString('en-US',{...opts,weekday:'short',month:'short',day:'numeric'})));article.append(start);
 const body=node('div',undefined,'subject'),context=node('p',undefined,'context');context.append(node('strong',row.league),node('time',date.toLocaleString('en-US',{...opts,weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+' ET'));
 const title=node('h2',undefined,'pick');
 if(compare){const open=node('button',pick(row),'row-open');open.type='button';open.dataset.quoteId=row.id;open.dataset.focusKey='compare-'+row.id;open.setAttribute('aria-label','Compare prices for '+pick(row));open.setAttribute('aria-haspopup','dialog');open.setAttribute('aria-controls','comparison');open.onclick=()=>openComparison(row);title.append(open);}else title.textContent=pick(row);
 const link=node('a',row.game,'game');link.dataset.focusKey='game-link-'+row.id;link.href='/game?'+new URLSearchParams({game_key:row.game_key});link.setAttribute('aria-label','Open Game: '+row.game);body.append(context,title,link);article.append(body);
 const cell=(cls,label,value)=>{const d=node('div',undefined,'board-number '+cls);d.append(node('span',label,'mobile-label'),node('span',value));article.append(d);return d;};
 const venue=cell('venue','Venue',venues[row.venue]||row.venue);
 const posted=priceDisplay(row),after=priceDisplay(row,true),postedCell=cell('posted','Price',posted.primary),afterCell=cell('after','After fees',after.primary);
 if(hasVenuePrice(row)){addMath(postedCell,row,'posted');appendPriceContext(postedCell,posted);appendPriceContext(afterCell,after);}
 addMath(afterCell,row,'after');
 const fair=cell('fair','Fair odds',row.display.fair_odds||'Unavailable');if(row.reference){fair.append(node('small',bookName(row.reference.book)+' ('+referencePrice(row)+')','reference'));addMath(fair,row,'fair');}
 addMath(cell('ev'+((row.display.net_ev||'').startsWith('-')?' negative':''),'Net EV',row.display.net_ev),row,'ev');const rank=rankInfo(row),score=cell('score',rank.column+(rank.unit==='log bp'?' (log bp)':rank.unit==='pp'?' (pp)':''),rank.display);addMath(score,row,'ranking');
 const metadata=node('div',undefined,'ticket-meta');article.insertBefore(metadata,venue);metadata.append(venue,score);body.append(freshness(row));
 return article;
}
function query(){const data=new FormData(filters),q=new URLSearchParams({limit:'30',offset:String(offset)});for(const name of ['search','league','family','venue','sort'])if(data.get(name))q.set(name,data.get(name));if(data.get('alternates'))q.set('lines','all');if(browse)q.set('browse','1');if(gameBoard)q.set('view','games');if(gameView)q.set('view','game');for(const name of ['game_key','bet_id','id'])if(initial.has(name))q.set(name,initial.get(name));if(initial.has('line'))q.set('bet_id',initial.get('line'));if(initial.has('quote_key'))q.set('id',initial.get('quote_key'));return q;}
async function get(q,updates=false,controller=new AbortController()){
 const timer=setTimeout(()=>controller.abort(new DOMException('Stored-price request exceeded 12 seconds.','TimeoutError')),12000);
 try{const response=await fetch(`/api/pregame${updates?'/updates':''}?${q}`,{cache:'no-store',signal:controller.signal});if(!response.ok)throw Error(`HTTP ${response.status}`);return await response.json();}finally{clearTimeout(timer);}
}
function render(packet){
 displayedQuery=query().toString();
 const fingerprint=JSON.stringify([query().toString(),packet.rows,packet.games,packet.total,packet.sort]);
 if(lastRendered===fingerprint){lastGood=packet;cursor=packet.cursor;total=packet.total;schedule(packet.refresh_at);return;}lastRendered=fingerprint;
 const result=$('results'),active=document.activeElement,restoreFocus=result.contains(active),focusKey=active?.dataset.focusKey;
 appliedRanking=packet.sort||rankingSelect.value;rankHeading();document.querySelector('.status-line').hidden=false;document.querySelector('.pagination').hidden=gameView||(packet.total<=30&&offset===0);lastGood=packet;cursor=packet.cursor;total=packet.total;result.replaceChildren();
 if(gameBoard&&packet.games?.length)result.append(...packet.games.map(gameCard));else if(gameView&&packet.rows.length)result.append(gameMarkets(packet.rows,true));else if(packet.rows.length)result.append(...packet.rows.map(row=>ticket(row)));else{const empty=node('div',undefined,'empty');empty.append(node('h2',browse?'No odds match these filters.':'No positive opportunities in this view.'));if(browse){empty.append(node('p','Try another league, market or venue.'));}else{const link=node('a','Browse odds →');link.href='/browse-odds';empty.append(link);}result.append(empty);}
 $('board-columns').hidden=gameBoard||gameView||!packet.rows.length;$('count').textContent=`${total} ${gameBoard?(total===1?'game':'games'):browse?(total===1?'bet':'bets'):(total===1?'opportunity':'opportunities')}`;$('previous').disabled=offset===0;$('next').disabled=offset+30>=total;$('page').textContent=total?`${offset+1}–${Math.min(offset+30,total)} of ${total}`:'0';schedule(packet.refresh_at);
 // A response can redraw the list just after a dialog restored its trigger.
 // Preserve keyboard identity across replacement without moving dialog/filter focus.
 if(restoreFocus){
  const target=[...result.querySelectorAll('[data-focus-key]')].find(e=>e.dataset.focusKey===focusKey);
  (target||result).focus({preventScroll:true});
 }
}
function schedule(deadline){clearTimeout(refreshTimer);if(deadline)refreshTimer=setTimeout(()=>load(),Math.min(2147483647,Math.max(30,Date.parse(deadline)-Date.now()+30)));}
async function load(manual=false){
 const token=++sequence;boardController?.abort();const controller=boardController=new AbortController();running=true;
 const refresh=$('refresh'),icon=refresh.querySelector('span');clearTimeout(feedbackTimer);refresh.disabled=true;refresh.setAttribute('aria-busy','true');icon.textContent='…';$('results').setAttribute('aria-busy','true');
 $('request-status').textContent=lastGood?'Updating prices… Displayed prices await verification.':'Loading stored prices…';$('practice-recovery').hidden=false;
 try{const packet=await get(query(),false,controller);if(token!==sequence)return;render(packet);$('error').hidden=true;delete $('error').dataset.source;$('request-status').textContent='';$('practice-recovery').hidden=true;icon.textContent=manual?'✓':'↻';refreshComparison();}
 catch(e){if(token!==sequence)return;icon.textContent='↻';$('request-status').textContent='';$('error').textContent=(e.name==='TimeoutError'?'The stored-price request timed out. ':'')+(lastGood?'Refresh failed. Your displayed odds are preserved but could not be verified.'+(displayedQuery!==query().toString()?' Results from the previous filters are still displayed.':''):'Odds could not be loaded. Choose Refresh to retry.');$('error').hidden=false;$('error').dataset.source='load';if(!lastGood){$('count').textContent='';document.querySelector('.status-line').hidden=true;}}
 finally{if(token===sequence){running=false;refresh.disabled=false;refresh.removeAttribute('aria-busy');$('results').removeAttribute('aria-busy');feedbackTimer=setTimeout(()=>{icon.textContent='↻';},1800);}}
}
function details(row){const detail=node('details'),dl=node('dl'),summary=node('summary','Fee and calculation details');summary.dataset.focusKey='details-'+row.id;detail.append(summary);const add=(label,value)=>dl.append(node('dt',label),node('dd',value));
 add('Trusted reference books',Object.keys(row.reference?.candidate_probabilities||{}).map(bookName).join(', ')||'Not recorded');add('Source route',row.source.provider);add('Source timestamp',row.times.source_at||'Not supplied');add('Received',row.times.received_at);add('Calculated',row.calculated_at);for(const [label,value]of feeRows(row))add(label,value);
 add('Fee terms',row.fee.classification==='conservative'?'Highest applicable documented charge where account terms are unresolved.':row.fee.classification.replaceAll('_',' '));
 const evidence=row.fee.evidence||{},rule=evidence.database_fee_rule;add('Fee schedule',rule?.id||evidence.schedule_version||evidence.version||evidence.product||'Verified venue schedule');
 if(rule){add('Fee formula',rule.formula.replaceAll('_',' '));add('Fee coefficient',rule.rate);if(rule.multiplier!=='1')add('Market multiplier',rule.multiplier);add('Balance precision',`$${rule.balance_precision}`);add('Applies from',rule.effective_from);if(rule.effective_to)add('Applies until',rule.effective_to);}else if(evidence.fee_rate!==undefined)add('Fee coefficient',evidence.fee_rate);
 if(evidence.account_profile)add('Account profile',`${evidence.account_profile.membership} · ${evidence.account_profile.channel}`);
 const source=evidence.source_url||rule?.source_url;if(source?.startsWith('https://')){const link=node('a','Official fee terms ↗');link.href=source;link.target='_blank';link.rel='noopener noreferrer';dl.append(node('dt','Fee source'),node('dd'));dl.lastChild.append(link);}
 for(const price of row.reference?.prices||[])add(`${row.reference.book} · ${price.side}`,`${price.price_american} · ${price.source_at}`);
 add('Method','Fair probability removes the same-book margin. Net EV weights net cash receipts by fair probabilities. Calculations use exact arithmetic until display rounding.');detail.append(dl);return detail;}
function quoteTable(headers, rows, className){
 const table=node('table',undefined,className),head=node('thead'),heading=node('tr'),body=node('tbody');table.setAttribute('role','table');head.setAttribute('role','rowgroup');body.setAttribute('role','rowgroup');heading.setAttribute('role','row');
 headers.forEach(label=>{const th=node('th',label);th.scope='col';th.setAttribute('role','columnheader');heading.append(th);});head.append(heading);
 rows.forEach(values=>{const tr=node('tr');tr.setAttribute('role','row');values.forEach((value,index)=>{const td=node('td');td.setAttribute('role','cell');td.dataset.label=headers[index];td.append(value);tr.append(td);});body.append(tr);});table.append(head,body);
 const scroll=node('div',undefined,'comparison-scroll');scroll.tabIndex=0;scroll.setAttribute('role','region');scroll.setAttribute('aria-label',headers[0]+' price comparison');scroll.append(table);return scroll;
}
function appendPriceContext(cell,display){if(display.price)cell.append(node('small',display.price,'price-equivalent'));if(display.secondary)cell.append(node('small',display.secondary,'american-equivalent'));}
function venuePrice(row,after=false){const display=priceDisplay(row,after),cell=node('span',undefined,'math-value');cell.append(node('span',display.primary));if(after||hasVenuePrice(row))addMath(cell,row,after?'after':'posted');appendPriceContext(cell,display);return cell;}
function mathValue(row,kind,value){const cell=node('span',undefined,'math-value');if(!row.reference||value===null||value===undefined){cell.append(node('span',kind==='ev'?'EV unavailable':'Unavailable'));const reason=row.ev_unavailable_reason?.replaceAll('_',' ')||'Reference probability not available';cell.append(node('small',reason,'unavailable-reason'));return cell;}cell.append(node('span',value));addMath(cell,row,kind);if(kind==='fair')cell.append(node('small',bookName(row.reference.book)+' ('+referencePrice(row)+')','reference'));return cell;}
function exchangePrices(rows){const previous=new Map([...$('comparison-content').querySelectorAll('.journal-action')].map(e=>[e.dataset.quoteId,e]));return quoteTable(['Venue','Price','After fees','Fair odds','Net EV',rankingMethods[appliedRanking].column,'My Bets'],rows.map(r=>{const label='Save '+bookName(r.venue)+' to My Bets',action=r.reference?journalAction('ev',r,label,previous.get(r.id)):node('span','EV unavailable; price remains inspectable.','unavailable-reason'),button=action.querySelector('button');action.dataset.quoteId=r.id;if(button){button.dataset.shortLabel='Save';button.dataset.focusKey='save-'+r.id;button.setAttribute('aria-label',label);if(!button.disabled)button.textContent='Save';}const venue=node('span',venues[r.venue]||r.venue);venue.append(freshness(r));return [venue,venuePrice(r),venuePrice(r,true),mathValue(r,'fair',r.display.fair_odds),mathValue(r,'ev',r.display.net_ev),mathValue(r,'ranking',rankInfo(r).display),action];}),'exchange-prices');}
function sportsbookPrices(selected,quotes=[],state='loading'){
 const section=node('section',undefined,'sportsbook-comparison');section.append(node('h3','Sportsbook prices'));
 const reference=referenceQuote(selected),rows=[];
 if(reference)rows.push({book:selected.reference?.book,posted_odds:reference.price_american,source_at:reference.source_at,received_at:reference.received_at,is_reference:true});
 rows.push(...quotes.filter(q=>!reference||q.book!==selected.reference?.book));
 if(rows.length){const values=rows.map(q=>{const book=node('span',bookName(q.book));if(q.is_reference)book.append(node('small','Reference used','reference-used'));return [book,q.posted_odds,freshnessText({times:{source_at:q.source_at}})+' · '+(q.source_at?new Date(q.source_at).toLocaleString([],{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'Source time not supplied')];});section.append(quoteTable(['Sportsbook','Posted odds','Source time'],values.slice(0,6),'sportsbook-prices'));if(values.length>6){const more=node('details');more.append(node('summary','More sportsbooks ('+(values.length-6)+')'),quoteTable(['Sportsbook','Posted odds','Source time'],values.slice(6),'sportsbook-prices'));section.append(more);}}
 else if(state==='loaded')section.append(node('p','No matching stored sportsbook price for this exact line.','comparison-context'));
 if(state==='loaded'&&reference&&!quotes.some(q=>q.book!==selected.reference?.book))section.append(node('p','No other sportsbooks quote this exact line in this snapshot.','comparison-context'));
 return section;
}
function comparisonStatus(state){
 const status=node('p',state==='loading'?'Checking other sportsbooks… Comparison is incomplete.':state==='failed'?'Comparison failed. Displayed prices could not be verified.':'Comparison complete for this stored snapshot.','comparison-context comparison-status');status.setAttribute('role','status');
 if(state==='failed'){const retry=node('button','Retry comparison');retry.type='button';retry.onclick=()=>refreshComparison();status.append(' ',retry);}return status;
}
function renderComparison(rows,quotes=[],state='loading'){
 const content=$('comparison-content'),selected=rows.find(r=>r.id===comparisonReturnId)||rows[0];
 if(!selected){content.replaceChildren(node('p','This line is no longer available. No matching stored price is available for this exact line. Choose another line or retry.','comparison-context'));return;}
 const expanded=new Set([...content.querySelectorAll('details[open]')].map(e=>e.querySelector('summary')?.textContent));
 const focused=content.contains(document.activeElement)?document.activeElement.dataset.focusKey:null;
 const scroll=content.scrollTop;
 const game=node('p',selected.game,'comparison-context'),selectedPrice=node('div',undefined,'selected-quote'),offers=node('section',undefined,'exchange-comparison'),evidence=node('section',undefined,'calculation-evidence');
 selectedPrice.append(node('strong','Selected quote · '+(venues[selected.venue]||selected.venue)),venuePrice(selected));for(const button of selectedPrice.querySelectorAll('[data-focus-key]'))button.dataset.focusKey='selected-'+button.dataset.focusKey;offers.append(node('h3','Exchange prices'),exchangePrices(rows));
 for(const [index,row]of rows.entries()){const detail=details(row);if(index)detail.querySelector('summary').textContent=(venues[row.venue]||row.venue)+' · Fee and calculation details';detail.open=expanded.has(detail.querySelector('summary').textContent);evidence.append(detail);}
 content.replaceChildren(game,selectedPrice,comparisonStatus(state),freshness(selected),payoutExample(selected),offers,sportsbookPrices(selected,quotes,state),evidence);for(const detail of content.querySelectorAll('details'))detail.open=expanded.has(detail.querySelector('summary')?.textContent);
 if(focused)[...content.querySelectorAll('[data-focus-key]')].find(e=>e.dataset.focusKey===focused)?.focus({preventScroll:true});
 content.scrollTop=scroll;
}
async function refreshComparison(){
 const active=activeComparison;if(!active||!$('comparison').open)return;
 if(active.loading){active.pending=true;return;}if(active.controller.signal.aborted)active.controller=new AbortController();active.loading=true;active.state='loading';
 $('comparison-content').querySelector('.comparison-status')?.replaceWith(comparisonStatus('loading'));
 try{const data=await get(new URLSearchParams({bet_id:active.selected.bet_id,...(active.selected.game_key?{game_key:active.selected.game_key}:{}),lines:'all',browse:'1',sort:appliedRanking}),false,active.controller);
 if(active!==activeComparison||!$('comparison').open||Date.parse(active.selected.kickoff)<=Date.now())return;
 const fingerprint=JSON.stringify([data.rows,data.sportsbooks||[]]);active.rows=data.rows;active.quotes=data.sportsbooks||[];active.state='loaded';if(active.fingerprint!==fingerprint){renderComparison(active.rows,active.quotes,'loaded');active.fingerprint=fingerprint;}else $('comparison-content').querySelector('.comparison-status')?.replaceWith(comparisonStatus('loaded'));
 }catch(e){if(active===activeComparison&&$('comparison').open){active.state='failed';renderComparison(active.rows,active.quotes,'failed');}}
 finally{active.loading=false;if(active===activeComparison&&active.pending){active.pending=false;active.controller=new AbortController();refreshComparison();}}
}
async function openComparison(selected){
 comparisonTrigger=document.activeElement;
 ++comparisonSequence;clearTimeout(inspectionTimer);comparisonReturnId=selected.id;
 activeComparison?.controller.abort();activeComparison={selected:structuredClone(selected),rows:[selected],quotes:[],loading:false,pending:false,state:'loading',controller:new AbortController()};
 inspectionTimer=setTimeout(()=>$('comparison').close(),Math.min(2147483647,Math.max(0,Date.parse(selected.kickoff)-Date.now())));
 $('comparison-title').textContent=pick(selected);renderComparison([selected]);showDialog($('comparison'),comparisonTrigger);
 await refreshComparison();
}

const families={moneyline:'Winner',spread:'Spread',total:'Total'};
function gameBet(row,interactive=false,annotate=true){
 const item=node('article',undefined,'game-bet');const heading=node('h4');
 if(interactive){const open=node('button',pick(row),'line-open');open.type='button';open.dataset.quoteId=row.id;open.dataset.focusKey='compare-'+row.id;open.setAttribute('aria-label','Compare prices for '+pick(row));open.onclick=()=>openComparison(row);if(!annotate)open.append(node('small','Compare prices →','line-action-label'));heading.append(open);}else heading.textContent=pick(row);
 const subject=node('div',undefined,'line-subject');subject.append(heading,node('span',(venues[row.venue]||row.venue)+(interactive&&annotate?' · '+(row.main?'Main':'Alternate'):''),'line-venue'));item.append(subject);
 const values=node('div',undefined,'line-values');
 for(const [label,value] of [['Price',venuePrice(row)],['After fees',venuePrice(row,true)],['Fair',mathValue(row,'fair',row.display.fair_odds)],['Net EV',mathValue(row,'ev',row.display.net_ev)]]){const cell=node('div');cell.append(node('small',label),value);values.append(cell);}item.append(values,freshness(row));return item;
}
function gameMarkets(rows,interactive=false,annotate=true){
 const grid=node('div',undefined,'game-markets');for(const [family,label]of Object.entries(families)){const lines=rows.filter(r=>r.family===family);if(!lines.length)continue;const market=node('section',undefined,'game-market');market.append(node('h3',label));for(const row of lines.sort((a,b)=>Number(b.main)-Number(a.main)||Number(a.selection.signed_line||0)-Number(b.selection.signed_line||0)||pick(a).localeCompare(pick(b))))market.append(gameBet(row,interactive,annotate));grid.append(market);}return grid;
}
function gameCard(game){
 const card=node('article',undefined,'game-card'),head=node('header'),date=new Date(game.kickoff),opts={timeZone:'America/New_York'};
 const title=node('h2'),open=node('button',game.game,'game-open');open.type='button';open.dataset.gameKey=game.game_key;open.dataset.focusKey='game-'+game.game_key;open.setAttribute('aria-haspopup','dialog');open.onclick=()=>openGame(game);title.append(open);head.append(title,node('p',game.league+' · '+date.toLocaleString('en-US',{...opts,weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+' ET','game-clock'),node('span','View all lines →','game-hint'));card.append(head,gameMarkets(game.rows,true,false));return card;
}
async function openGame(game){
 clearTimeout(gameTimer);gameTimer=setTimeout(()=>$('game-lines').close(),Math.min(2147483647,Math.max(0,Date.parse(game.kickoff)-Date.now())));
 gameController?.abort();const controller=gameController=new AbortController();const token=++gameSequence;gameReturnKey=game.game_key;$('game-title').textContent=game.game;const content=$('game-content');content.replaceChildren(node('p','Loading alternate lines…','comparison-context'),gameMarkets(game.rows,true));showDialog($('game-lines'));
 try{const q=new URLSearchParams(query());q.set('view','game');q.set('game_key',game.game_key);q.set('lines','all');const data=await get(q,false,controller);if(token!==gameSequence||!$('game-lines').open)return;content.replaceChildren(gameMarkets(data.rows,true));if(!data.rows.length)content.append(node('p','No current lines match these filters.'));}
 catch(e){if(token===gameSequence){const message=node('p','Alternate lines could not be loaded. Main lines are preserved.','comparison-context'),retry=node('button','Retry');retry.onclick=()=>{$('game-lines').close();openGame(game);};content.prepend(message,retry);}}
}
$('game-close').onclick=()=>$('game-lines').close();$('game-lines').addEventListener('close',()=>{clearTimeout(gameTimer);gameController?.abort();gameSequence++;if($('comparison').open)$('comparison').close();const target=[...document.querySelectorAll('.game-open')].find(b=>b.dataset.gameKey===gameReturnKey);restoreDialog($('game-lines'),target||$('results'));});

$('close').onclick=()=>$('comparison').close();$('comparison').addEventListener('close',()=>{comparisonSequence++;activeComparison?.controller.abort();activeComparison=null;clearTimeout(inspectionTimer);const eligible=button=>button?.isConnected&&(!button.closest('dialog')||button.closest('dialog').open);const target=eligible(comparisonTrigger)?comparisonTrigger:[...document.querySelectorAll('.row-open,.line-open')].find(button=>button.dataset.quoteId===comparisonReturnId&&eligible(button));restoreDialog($('comparison'),target||$('results'));});$('refresh').onclick=()=>load(true);$('previous').onclick=()=>{offset=Math.max(0,offset-30);load();};$('next').onclick=()=>{offset+=30;load();};
let searchTimer;filters.addEventListener('submit',event=>event.preventDefault());filters.addEventListener('input',event=>{clearTimeout(searchTimer);offset=0;sequence++;boardController?.abort();$('request-status').textContent='Updating filters…';searchTimer=setTimeout(()=>load(),event.target.name==='search'?180:0);});
rankingSelect.addEventListener('change',()=>{try{localStorage.setItem(rankingKey,rankingSelect.value);}catch(e){}clearTimeout(searchTimer);offset=0;sequence++;load();});
$('alternates-field').hidden=true;if(browse){$('sort-order').textContent=gameBoard?'Game start time ↑':'Main and alternate lines';$('results').setAttribute('aria-label',gameBoard?'Games by start time':'Game lines');}
if(browse){$('ranking-field').hidden=true;$('sort-order').hidden=false;}
if(browse){$('title').textContent=location.pathname==='/game'?'Game odds':'Browse odds';document.title='Predict · Browse odds';}
if(gameView)document.querySelector('.heading-flag').textContent='Pregame · Main & alternate lines';
for(const link of document.querySelectorAll('.masthead nav a'))if(new URL(link.href).pathname===location.pathname)link.setAttribute('aria-current','page');
load();setInterval(async()=>{if(running||checking||document.hidden)return;checking=true;try{const p=await get(new URLSearchParams({after:cursor}),true);if(p.changed)load();else if($('error').dataset.source==='updates'){$('error').hidden=true;delete $('error').dataset.source;}}catch(e){$('error').textContent=lastGood?'Update check failed. Your displayed odds are preserved.':'Odds could not be loaded. Choose Refresh to retry.';$('error').hidden=false;$('error').dataset.source='updates';}finally{checking=false;}},500);
