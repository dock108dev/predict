import {bookName,venues} from './pregame-labels.js';
import {priceDisplay,isContractVenue} from './pregame-prices.js';
import {addMath} from './pregame-math.js';
const $=id=>document.getElementById(id);
const initial=new URLSearchParams(location.search), browse=location.pathname==='/browse-odds'||location.pathname==='/game';
const gameView=location.pathname==='/game', gameBoard=location.pathname==='/browse-odds'&&!initial.has('bet_id')&&!initial.has('id')&&!initial.has('line')&&!initial.has('quote_key');
let gameSequence=0,gameReturnKey,comparisonTrigger,gameTimer;
let offset=0, total=0, cursor='', refreshTimer, running=false, checking=false, queued=false, lastGood=null, sequence=0, comparisonSequence=0, inspectionTimer, comparisonReturnId;
const filters=$('filters');
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function pick(row){const s=row.selection;const team=row.selection_label||(s.participant||'').split(':').pop();let line=s.signed_line||'';if(line.includes('/')){const [a,b]=line.split('/');line=String(Number(a)/Number(b));}if(row.family==='total')return `${s.predicate==='over'?'Over':'Under'} ${line}`;return `${team}${row.family==='spread'?` ${Number(line)>0?'+':''}${line}`:' to win'}`;}

function referenceQuote(row){return row.reference.prices.find(p=>p.side===row.reference.selected_outcome);}
function referencePrice(row){return referenceQuote(row)?.price_american ?? 'Unavailable';}
function ticket(row,compare=true){
 const article=node('article',undefined,'ticket board-row');
 const date=new Date(row.kickoff),opts={timeZone:'America/New_York'};
 article.append(node('div',row.league,'league-cell'));
 const start=node('div',undefined,'start-cell');start.append(node('strong',date.toLocaleTimeString('en-US',{...opts,hour:'numeric',minute:'2-digit'})),node('span',date.toLocaleDateString('en-US',{...opts,weekday:'short',month:'short',day:'numeric'})));article.append(start);
 const body=node('div',undefined,'subject'),context=node('p',undefined,'context');context.append(node('strong',row.league),node('time',date.toLocaleString('en-US',{...opts,weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+' ET'));
 const title=node('h2',undefined,'pick');
 if(compare){const open=node('button',pick(row),'row-open');open.type='button';open.dataset.quoteId=row.id;open.setAttribute('aria-label','Compare prices for '+pick(row));open.setAttribute('aria-haspopup','dialog');open.setAttribute('aria-controls','comparison');open.onclick=()=>openComparison(row);title.append(open);}else title.textContent=pick(row);
 const link=node('a',row.game,'game');link.href='/game?'+new URLSearchParams({game_key:row.game_key});link.setAttribute('aria-label','Open Game: '+row.game);body.append(context,title,link);article.append(body);
 const cell=(cls,label,value)=>{const d=node('div',undefined,'board-number '+cls);d.append(node('span',label,'mobile-label'),node('span',value));article.append(d);return d;};
 cell('venue','Venue',venues[row.venue]||row.venue);
 const posted=priceDisplay(row),after=priceDisplay(row,true),postedCell=cell('posted','Price',posted.primary),afterCell=cell('after','After fees',after.primary);
 if(isContractVenue(row)){addMath(postedCell,row,'posted');appendPriceContext(postedCell,posted);appendPriceContext(afterCell,after);}
 addMath(afterCell,row,'after');
 const fair=cell('fair','Fair odds',row.display.fair_odds);fair.append(node('small',bookName(row.reference.book)+' ('+referencePrice(row)+')','reference'));addMath(fair,row,'fair');
 addMath(cell('ev'+(row.display.net_ev.startsWith('-')?' negative':''),'Net EV',row.display.net_ev),row,'ev');addMath(cell('score','Opportunity Score',row.display.opportunity_score),row,'score');
 return article;
}
function query(){const data=new FormData(filters),q=new URLSearchParams({limit:'30',offset:String(offset)});for(const name of ['search','league','family','venue'])if(data.get(name))q.set(name,data.get(name));if(data.get('alternates'))q.set('lines','all');if(browse)q.set('browse','1');if(gameBoard)q.set('view','games');if(gameView)q.set('view','game');for(const name of ['game_key','bet_id','id'])if(initial.has(name))q.set(name,initial.get(name));if(initial.has('line'))q.set('bet_id',initial.get('line'));if(initial.has('quote_key'))q.set('id',initial.get('quote_key'));return q;}
async function get(q,updates=false){const response=await fetch(`/api/pregame${updates?'/updates':''}?${q}`,{cache:'no-store'});if(!response.ok)throw Error(`HTTP ${response.status}`);return response.json();}
function render(packet){lastGood=packet;cursor=packet.cursor;total=packet.total;const result=$('results');result.replaceChildren();
 if(gameBoard&&packet.games?.length)result.append(...packet.games.map(gameCard));else if(gameView&&packet.rows.length)result.append(gameMarkets(packet.rows,true));else if(packet.rows.length)result.append(...packet.rows.map(row=>ticket(row)));else{const empty=node('div',undefined,'empty');empty.append(node('p','THE BOARD IS CLEAR','eyebrow'),node('h2',browse?'No odds match these filters.':'No positive opportunities in this view.'),node('p',browse?'Try another league, market or venue.':'Browse odds to compare available prices, or change your filters.'));const link=node('a','Browse odds ↗');link.href='/browse-odds';empty.append(link);result.append(empty);}
 $('board-columns').hidden=gameBoard||gameView||!packet.rows.length;$('count').textContent=`${total} ${gameBoard?(total===1?'game':'games'):browse?(total===1?'bet':'bets'):(total===1?'opportunity':'opportunities')}`;$('previous').disabled=offset===0;$('next').disabled=offset+30>=total;$('page').textContent=total?`${offset+1}–${Math.min(offset+30,total)} of ${total}`:'0';schedule(packet.refresh_at);
}
function schedule(deadline){clearTimeout(refreshTimer);if(deadline)refreshTimer=setTimeout(()=>load(),Math.min(2147483647,Math.max(30,Date.parse(deadline)-Date.now()+30)));}
async function load(){if(running){queued=true;return;}running=true;const token=++sequence;try{const packet=await get(query());if(token===sequence){render(packet);$('error').hidden=true;}}catch(e){$('error').textContent=lastGood?'Refresh failed. Your displayed odds are preserved.':'Odds could not be loaded. Choose Refresh to retry.';$('error').hidden=false;if(!lastGood)$('count').textContent='Odds could not be loaded.';}finally{running=false;if(queued){queued=false;load();}}}
function dollars(value){const [a,b='1']=String(value).split('/');return '$'+(Number(a)/Number(b)).toFixed(2);}
function details(row){const detail=node('details'),dl=node('dl');detail.append(node('summary','Fee and calculation details'));const add=(label,value)=>dl.append(node('dt',label),node('dd',value));
 add('Source route',row.source.provider);add('Source timestamp',row.times.source_at||'Not supplied');add('Received',row.times.received_at);add('Calculated',row.calculated_at);add('Fee basis','$100 internal comparison basis · Posted price');add('Cash committed',dollars(row.fee.committed_usd));add('Entry fee',dollars(row.fee.entry_usd));for(const [state,cash]of Object.entries(row.fee.cashflows)){add(`${state==='win'?'Winning':'Losing'} fee`,dollars(cash.total_fee_usd));add(`${state==='win'?'Winning':'Losing'} receipt`,dollars(cash.net_receipt_usd));}
 add('Fee terms',row.fee.classification==='conservative'?'Highest applicable documented charge where account terms are unresolved.':row.fee.classification.replaceAll('_',' '));
 const evidence=row.fee.evidence||{},rule=evidence.database_fee_rule;add('Fee schedule',rule?.id||evidence.schedule_version||evidence.version||evidence.product||'Verified venue schedule');
 if(rule){add('Fee formula',rule.formula.replaceAll('_',' '));add('Fee coefficient',rule.rate);if(rule.multiplier!=='1')add('Market multiplier',rule.multiplier);add('Balance precision',`$${rule.balance_precision}`);add('Applies from',rule.effective_from);if(rule.effective_to)add('Applies until',rule.effective_to);}else if(evidence.fee_rate!==undefined)add('Fee coefficient',evidence.fee_rate);
 if(evidence.account_profile)add('Account profile',`${evidence.account_profile.membership} · ${evidence.account_profile.channel}`);
 const source=evidence.source_url||rule?.source_url;if(source?.startsWith('https://')){const link=node('a','Official fee terms ↗');link.href=source;link.target='_blank';link.rel='noopener noreferrer';dl.append(node('dt','Fee source'),node('dd'));dl.lastChild.append(link);}
 for(const price of row.reference.prices)add(`${row.reference.book} · ${price.side}`,`${price.price_american} · ${price.source_at}`);
 add('Method','Fair probability removes the same-book margin. Net EV weights net cash receipts by fair probabilities. Calculations use exact arithmetic until display rounding.');detail.append(dl);return detail;}
function quoteTable(headers, rows, className){
 const table=node('table',undefined,className),head=node('thead'),heading=node('tr'),body=node('tbody');
 headers.forEach(label=>{const th=node('th',label);th.scope='col';heading.append(th);});head.append(heading);
 rows.forEach(values=>{const tr=node('tr');values.forEach(value=>{const td=node('td');td.append(value);tr.append(td);});body.append(tr);});table.append(head,body);
 const scroll=node('div',undefined,'comparison-scroll');scroll.tabIndex=0;scroll.setAttribute('role','region');scroll.setAttribute('aria-label',headers[0]+' price comparison');scroll.append(table);return scroll;
}
function appendPriceContext(cell,display){if(display.price)cell.append(node('small',display.price,'price-equivalent'));if(display.secondary)cell.append(node('small',display.secondary,'american-equivalent'));}
function venuePrice(row,after=false){const display=priceDisplay(row,after),cell=node('span',undefined,'math-value');cell.append(node('span',display.primary));if(after||isContractVenue(row))addMath(cell,row,after?'after':'posted');appendPriceContext(cell,display);return cell;}
function mathValue(row,kind,value){const cell=node('span',undefined,'math-value');cell.append(node('span',value));addMath(cell,row,kind);if(kind==='fair')cell.append(node('small',bookName(row.reference.book)+' ('+referencePrice(row)+')','reference'));return cell;}
function exchangePrices(rows){return quoteTable(['Venue','Price','After fees','Fair odds','Net EV','Score'],rows.map(r=>[venues[r.venue]||r.venue,venuePrice(r),venuePrice(r,true),mathValue(r,'fair',r.display.fair_odds),mathValue(r,'ev',r.display.net_ev),mathValue(r,'score',r.display.opportunity_score)]),'exchange-prices');}
function sportsbookPrices(selected,quotes=[]){
 const section=node('section',undefined,'sportsbook-comparison');section.append(node('h3','Sportsbook prices'),node('p','Posted odds for this exact pick and line.','comparison-context'));
 const reference=referenceQuote(selected),rows=[];
 if(reference)rows.push({book:selected.reference.book,posted_odds:reference.price_american,source_at:reference.source_at,received_at:reference.received_at,is_reference:true});
 rows.push(...quotes.filter(q=>!reference||q.book!==selected.reference.book));
 if(rows.length){const values=rows.map(q=>{const book=node('span',bookName(q.book));if(q.is_reference)book.append(node('small','Reference used','reference-used'));return [book,q.posted_odds,q.source_at?new Date(q.source_at).toLocaleString([],{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}):'Not supplied'];});section.append(quoteTable(['Sportsbook','Posted odds','Source time'],values.slice(0,6),'sportsbook-prices'));if(values.length>6){const more=node('details');more.append(node('summary','More sportsbooks ('+(values.length-6)+')'),quoteTable(['Sportsbook','Posted odds','Source time'],values.slice(6),'sportsbook-prices'));section.append(more);}}
 else section.append(node('p','No matching sportsbook quotes are available in this snapshot.','comparison-context'));
 if(reference&&!quotes.some(q=>q.book!==selected.reference.book))section.append(node('p','No other sportsbooks quote this exact line in this snapshot.','comparison-context'));
 return section;
}
async function openComparison(selected){
 comparisonTrigger=document.activeElement;
 const token=++comparisonSequence;clearTimeout(inspectionTimer);const frozen=structuredClone(selected);comparisonReturnId=selected.id;
 inspectionTimer=setTimeout(()=>$('comparison').close(),Math.min(2147483647,Math.max(0,Date.parse(frozen.kickoff)-Date.now())));
 $('comparison-title').textContent=pick(frozen);const content=$('comparison-content');
 const game=node('p',frozen.game,'comparison-context'),offers=node('section',undefined,'exchange-comparison'),books=node('div'),evidence=node('section',undefined,'calculation-evidence');
 offers.append(node('h3','Exchange prices'),exchangePrices([frozen]));evidence.append(node('h3','Calculation details'),details(frozen));
 content.replaceChildren(game,offers,books,evidence);$('comparison').showModal();
 try{const data=await get(new URLSearchParams({bet_id:frozen.bet_id,lines:'all',browse:'1'}));if(!$('comparison').open||token!==comparisonSequence||Date.parse(frozen.kickoff)<=Date.now())return;
 const others=data.rows.filter(r=>r.id!==frozen.id);offers.replaceChildren(node('h3','Exchange prices'),exchangePrices([frozen,...others]));books.replaceChildren(sportsbookPrices(frozen,data.sportsbooks||[]));
 for(const row of others){const detail=details(row);detail.querySelector('summary').textContent=(venues[row.venue]||row.venue)+' · Fee and calculation details';evidence.append(detail);}
 }catch(e){books.replaceChildren(sportsbookPrices(frozen));content.append(node('p','Comparison refresh failed. The selected odds are preserved.','comparison-context'));}
}

const families={moneyline:'Winner',spread:'Spread',total:'Total'};
function gameBet(row,interactive=false){
 const item=node('article',undefined,'game-bet');const heading=node('h4');
 if(interactive){const open=node('button',pick(row),'line-open');open.type='button';open.dataset.quoteId=row.id;open.setAttribute('aria-label','Compare prices for '+pick(row));open.onclick=()=>openComparison(row);heading.append(open);}else heading.textContent=pick(row);
 const subject=node('div',undefined,'line-subject');subject.append(heading,node('span',(venues[row.venue]||row.venue)+(interactive?' · '+(row.main?'Main':'Alternate'):''),'line-venue'));item.append(subject);
 const values=node('div',undefined,'line-values');
 for(const [label,value] of [['Price',venuePrice(row)],['After fees',venuePrice(row,true)],['Fair',mathValue(row,'fair',row.display.fair_odds)],['Net EV',mathValue(row,'ev',row.display.net_ev)]]){const cell=node('div');cell.append(node('small',label),value);values.append(cell);}item.append(values);return item;
}
function gameMarkets(rows,interactive=false){
 const grid=node('div',undefined,'game-markets');for(const [family,label]of Object.entries(families)){const lines=rows.filter(r=>r.family===family);if(!lines.length)continue;const market=node('section',undefined,'game-market');market.append(node('h3',label));for(const row of lines.sort((a,b)=>Number(b.main)-Number(a.main)||Number(a.selection.signed_line||0)-Number(b.selection.signed_line||0)||pick(a).localeCompare(pick(b))))market.append(gameBet(row,interactive));grid.append(market);}return grid;
}
function gameCard(game){
 const card=node('article',undefined,'game-card'),head=node('header'),date=new Date(game.kickoff),opts={timeZone:'America/New_York'};head.append(node('p',game.league+' · '+date.toLocaleString('en-US',{...opts,weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+' ET','game-clock'));
 const title=node('h2'),open=node('button',game.game,'game-open');open.type='button';open.dataset.gameKey=game.game_key;open.setAttribute('aria-haspopup','dialog');open.onclick=()=>openGame(game);title.append(open);head.append(title,node('span','All lines & comparisons ↗','game-hint'));card.append(head,gameMarkets(game.rows));return card;
}
async function openGame(game){
 clearTimeout(gameTimer);gameTimer=setTimeout(()=>$('game-lines').close(),Math.min(2147483647,Math.max(0,Date.parse(game.kickoff)-Date.now())));
 const token=++gameSequence;gameReturnKey=game.game_key;$('game-title').textContent=game.game;const content=$('game-content');content.replaceChildren(node('p','Loading alternate lines…','comparison-context'),gameMarkets(game.rows,true));$('game-lines').showModal();
 try{const q=new URLSearchParams(query());q.set('view','game');q.set('game_key',game.game_key);q.set('lines','all');const data=await get(q);if(token!==gameSequence||!$('game-lines').open)return;content.replaceChildren(node('p','Select a line to compare venues and sportsbooks. All available main and alternate lines are shown.','comparison-context'),gameMarkets(data.rows,true));if(!data.rows.length)content.append(node('p','No current lines match these filters.'));}
 catch(e){if(token===gameSequence){const message=node('p','Alternate lines could not be loaded. Main lines are preserved.','comparison-context'),retry=node('button','Retry');retry.onclick=()=>{$('game-lines').close();openGame(game);};content.prepend(message,retry);}}
}
$('game-close').onclick=()=>$('game-lines').close();$('game-lines').addEventListener('close',()=>{clearTimeout(gameTimer);gameSequence++;if($('comparison').open)$('comparison').close();const target=[...document.querySelectorAll('.game-open')].find(b=>b.dataset.gameKey===gameReturnKey);(target||$('results')).focus({preventScroll:true});});

$('close').onclick=()=>$('comparison').close();$('comparison').addEventListener('close',()=>{comparisonSequence++;clearTimeout(inspectionTimer);const eligible=button=>button?.isConnected&&(!button.closest('dialog')||button.closest('dialog').open);const target=eligible(comparisonTrigger)?comparisonTrigger:[...document.querySelectorAll('.row-open,.line-open')].find(button=>button.dataset.quoteId===comparisonReturnId&&eligible(button));(target||$('results')).focus({preventScroll:true});});$('refresh').onclick=()=>load();$('previous').onclick=()=>{offset=Math.max(0,offset-30);sequence++;load();};$('next').onclick=()=>{offset+=30;sequence++;load();};
let searchTimer;filters.addEventListener('submit',event=>event.preventDefault());filters.addEventListener('input',event=>{clearTimeout(searchTimer);offset=0;sequence++;searchTimer=setTimeout(()=>load(),event.target.name==='search'?180:0);});
$('alternates-field').hidden=true;document.querySelector('.pagination').hidden=gameView;if(browse){$('sort-order').textContent=gameBoard?'Game start time ↑':'Main and alternate lines';$('results').setAttribute('aria-label',gameBoard?'Games by start time':'Game lines');}
if(browse){$('title').textContent=location.pathname==='/game'?'Game odds':'Browse odds';document.title='Predict · Browse odds';}
for(const link of document.querySelectorAll('.masthead nav a'))if(new URL(link.href).pathname===location.pathname)link.setAttribute('aria-current','page');
load();setInterval(async()=>{if(running||checking||document.hidden)return;checking=true;try{const p=await get(new URLSearchParams({after:cursor}),true);if(p.changed)load();}catch(e){$('error').textContent=lastGood?'Update check failed. Your displayed odds are preserved.':'Odds could not be loaded. Choose Refresh to retry.';$('error').hidden=false;}finally{checking=false;}},500);
