import {bindBoardFilters} from './board-filters.js';
import {createModeSettings} from './mode-settings.js';
import {bindDialogClose} from './dialog-close.js';
import {journalAction} from './bet-journal-actions.js';
import {bookName} from './pregame-labels.js';
import {priceDisplay,hasVenuePrice,ratio} from './pregame-prices.js';
import {addMath} from './pregame-math.js';
import {freshness,feeRows} from './pregame-evidence.js';
const $=id=>document.getElementById(id);
const boardFilters=bindBoardFilters($('filters'));
const modeSettings=createModeSettings(()=>{offset=0;cancelRead();load();});
let offset=0,lastGood=null,running=false,checking=false,returnId,deadlineTimer,inspectionTimer,requestVersion=0,errorSource=null,activeRead,activeUpdate,dialogReturn,lastRowsFingerprint;
// The server allows 15s for a measured 8.9s cold scan; leave transport headroom.
// This recovery deadline is not an interaction-performance claim.
const READ_DEADLINE_MS=18000;
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const money=v=>'$'+ratio(v).toFixed(2);
function pick(r){let line=r.selection.signed_line,team=r.selection_label||r.selection.participant||'';if(line!==undefined&&line!==null)line=ratio(line);return r.family==='total'?(r.side==='over'?'Over ':'Under ')+line:team+(r.family==='spread'?' '+(line>0?'+':'')+line:' to win');}
function value(row,after=false){
 const display=priceDisplay(row,after),cell=node('span',undefined,'math-value arb-price-value');
 cell.append(node('span',display.primary));
 if(after||hasVenuePrice(row))addMath(cell,row,after?'after':'posted');
 if(display.price)cell.append(node('small',display.price.replace(/ (price|payout)$/,''),'price-equivalent'));
 if(display.secondary)cell.append(node('small',display.secondary,'american-equivalent'));
 return cell;
}
const official={kalshi:'https://kalshi.com/',polymarket_us:'https://polymarket.us/',novig:'https://www.novig.us/',prophetx:'https://www.prophetx.co/',fanduel:'https://sportsbook.fanduel.com/',draftkings:'https://sportsbook.draftkings.com/',betmgm:'https://sports.betmgm.com/',caesars:'https://sportsbook.caesars.com/'};
function leg(row,amount=false){
 const item=node('div',undefined,'arb-leg'),heading=node('div',undefined,'arb-leg-heading');
 heading.append(node('span',bookName(row.venue)),node('strong',pick(row)));
 const prices=node('div',undefined,'arb-prices');
 for(const [label,after]of [['Posted',false],['After fees',true]]){
  const column=node('div',undefined,'arb-price-column');
  column.append(node('small',label,'price-label'),value(row,after));prices.append(column);
 }
 item.append(heading,prices,freshness(row));
 if(amount){
  const context=node('div',undefined,'arb-leg-context');
  if(official[row.venue]){const link=node('a','Open '+(bookName(row.venue))+' ↗');link.href=official[row.venue];link.target='_blank';link.rel='noopener noreferrer';context.append(link);}
  context.append(node('p','Committed '+money(row.fee.committed_usd),'arb-context'),node('p','Source '+(row.times.source_at?new Date(row.times.source_at).toLocaleString():'time not supplied'),'arb-context'),node('p','Received '+new Date(row.times.received_at).toLocaleString(),'arb-context'));
  const fees=node('details');fees.append(node('summary','Fees for this modeled allocation'));for(const [label,value]of feeRows(row))fees.append(node('p',label+': '+value,'arb-context'));context.append(fees);
  item.append(context);
 }
 return item;
}
function card(pair){const d=node('article',undefined,'arb-card'),subject=node('div',undefined,'arb-subject'),h=node('h2'),open=node('button',pair.game,'arb-open');open.type='button';open.dataset.pairId=pair.id;open.setAttribute('aria-haspopup','dialog');open.setAttribute('aria-label','Inspect two-sided prices: '+pair.game);open.onclick=()=>inspect(pair);d.addEventListener('click',event=>{if(!event.target.closest('a,button,input,select,summary,details,[popover]'))inspect(pair);});h.append(open);subject.append(node('p',pair.league+' · '+new Date(pair.kickoff).toLocaleString('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+' ET','game-clock'),h,node('p',(pair.category==='market_book'?'Market ↔ Sportsbook':'Market ↔ Market')+' · '+({moneyline:'Winner',spread:'Spread',total:'Total'})[pair.family],'arb-context'));const result=node('div',undefined,'arb-return');result.append(node('strong',pair.display_return),node('small','Paired return after fees'),node('small','Instant size unknown'));d.append(subject,...pair.legs.map(r=>leg(r)),result);return d;}
function inspect(pair){dialogReturn={x:scrollX,y:scrollY,overflow:document.documentElement.style.overflow,focus:document.activeElement};document.documentElement.style.overflow='hidden';const frozen=structuredClone(pair);returnId=pair.id;const content=$('arb-content'),summary=node('div',undefined,'arb-summary');for(const [label,text]of [['Cash committed',money(frozen.committed_usd)],['Minimum modeled profit',money(frozen.minimum_profit_usd)],['After-fee return',frozen.display_return]]){const v=node('div',label);v.append(node('strong',text));summary.append(v);}const legs=node('div',undefined,'arb-detail-legs');legs.append(...frozen.legs.map(r=>leg(r,true)));const table=node('table',undefined,'arb-states'),head=node('thead'),tr=node('tr');for(const text of ['Completed-game outcome','Net receipts','Net profit'])tr.append(node('th',text));head.append(tr);const body=node('tbody');frozen.legs.forEach((row,i)=>{const tr=node('tr');for(const text of [pick(row)+' wins',money(frozen.receipts_usd[i]),money(frozen.profits_usd[i])])tr.append(node('td',text));body.append(tr);});table.append(head,body);const risk=node('p',frozen.settlement_note+' '+frozen.liquidity_note+' Both legs must fill at the modeled prices. Partial fills, price changes and different venue rules can create losses.','arb-risk'),math=node('details');math.append(node('summary','How this comparison is calculated'),node('p','Using up to $100 total, the model balances the two completed-game net receipts, repricing fees and legal quantity increments for each leg. State profit = both net receipts in that state − total cash committed. Paired return = the lower state profit ÷ total cash committed. This bounded allocation is illustrative, not a recommended stake or an execution maximum. Unused cash: '+money(frozen.unused_usd)+'. No sportsbook fair probability or EV is used.','comparison-context'));const link=node('a','Arbitrage assumptions, order types and sources ↗');link.href='/about#arbitrage';$('arb-title').textContent=frozen.game;content.replaceChildren(summary,legs,journalAction('arb',frozen,'Save arbitrage to My Bets'),table,risk,math,link);$('arb-details').showModal();clearTimeout(inspectionTimer);inspectionTimer=setTimeout(()=>$('arb-details').close(),Math.min(2147483647,Math.max(0,Date.parse(frozen.kickoff)-Date.now())));}
function query(){const q=new URLSearchParams({offset:String(offset),limit:'30'});for(const [key,v]of new FormData($('filters')))if(v&&key!=='alternates')q.set(key,v);return q;}
function setState(state,message){
 $('results').dataset.state=state;$('results').setAttribute('aria-busy',String(state==='loading'));
 $('count').textContent=message;document.querySelector('.status-line').hidden=false;
}
function showError(source,message){
 if(source==='updates'&&errorSource==='load')return;
 errorSource=source;$('error').textContent=message;$('error').hidden=false;
 setState(lastGood?'partial':'failed',lastGood?'Displayed comparisons are unverified.':'Comparisons unavailable.');
}
function showResultState(data){
 const partial=data.partial===true||data.completeness==='partial'||Number(data.excluded_pairs)>0;
 setState(partial?'partial':data.rows.length?'loaded':'empty',data.total+' price-arb '+(data.total===1?'candidate':'candidates')+(partial?' · Partial comparison results.':'')+(data.excluded_pairs?' · '+data.excluded_pairs+' '+(Number(data.excluded_pairs)===1?'pair':'pairs')+' could not be modeled.':''));
 if(!data.rows.length){const heading=$('results').querySelector('.empty h2');if(heading)heading.textContent=partial?'No positive pair in the completed comparisons.':'No positive after-fee pairs match this view.';}
}
function render(data){
 modeSettings.update(data.activity_mode);
 $('sort-order').textContent={return:'After-fee paired return ↓',newest:'Newest source first',oldest:'Oldest source first',start:'Game start time ↑'}[$('arb-sort').value];
 document.querySelector('.pagination').hidden=data.total<=30&&offset===0;
 lastGood=data;
 const book=$('book'),selectedBook=book.value,available=new Set(data.sportsbooks||[]);
 // An empty or filtered result must not silently clear the user's book filter.
 if(selectedBook)available.add(selectedBook);
 book.replaceChildren(new Option('All sportsbooks',''),...[...available].map(name=>new Option(bookName(name),name)));
 book.value=selectedBook;
 const results=$('results'),focused=document.activeElement,focusId=focused?.dataset.pairId,position={x:scrollX,y:scrollY};
 const fingerprint=JSON.stringify(data.rows);
 if(lastRowsFingerprint!==fingerprint){
  results.replaceChildren(...data.rows.map(card));lastRowsFingerprint=fingerprint;
  if(!data.rows.length){
   const empty=node('div',undefined,'empty');
   empty.append(node('h2','No positive after-fee pairs match this view.'),node('p','Both market-to-market and market-to-sportsbook prices are checked. No positive pair does not mean executable arbitrage is unavailable elsewhere.'));results.append(empty);
  }
  if(focusId)[...results.querySelectorAll('.arb-open')].find(b=>b.dataset.pairId===focusId)?.focus({preventScroll:true});
  scrollTo(position.x,position.y);
 }
 showResultState(data);
 $('previous').disabled=offset===0;$('next').disabled=offset+30>=data.total;
 $('page').textContent=data.total?`${offset+1}–${Math.min(offset+30,data.total)} of ${data.total}`:'0';
 errorSource=null;$('error').hidden=true;
 clearTimeout(deadlineTimer);
 if(data.refresh_at)deadlineTimer=setTimeout(load,Math.min(2147483647,Math.max(30,Date.parse(data.refresh_at)-Date.now()+30)));
}
function cancelRead(){requestVersion++;activeRead?.abort();activeUpdate?.abort();}
async function read(url,controller){
 const timer=setTimeout(()=>controller.abort('deadline'),READ_DEADLINE_MS);
 try{const response=await fetch(url,{cache:'no-store',signal:controller.signal});if(!response.ok)throw Error('HTTP '+response.status);return await response.json();}
 finally{clearTimeout(timer);}
}
async function load(){
 cancelRead();const version=requestVersion,controller=new AbortController();activeRead=controller;running=true;
 const refresh=$('refresh');refresh.setAttribute('aria-busy','true');refresh.querySelector('span').textContent='…';
 setState('loading',lastGood?'Updating… Previous results shown.':'Loading comparisons…');
 try{
  const data=await read('/api/pregame/arbs?'+query(),controller);
  if(version===requestVersion)render(data);
 }catch(e){
  if(version===requestVersion){const timeout=controller.signal.reason==='deadline';showError('load',lastGood?(timeout?'Comparison request timed out.':'Refresh failed.')+' Displayed comparisons are preserved but could not be verified; choose Refresh to retry.':(timeout?'Comparison request timed out.':'Comparisons could not be loaded.')+' Choose Refresh to retry.');}
 }finally{
  if(version===requestVersion){running=false;activeRead=null;refresh.removeAttribute('aria-busy');refresh.querySelector('span').textContent='↻';}
 }
}
async function checkUpdates(){
 if(running||checking||document.hidden||!lastGood)return;
 checking=true;const version=requestVersion,controller=new AbortController();activeUpdate=controller;
 try{
  const data=await read('/api/pregame/updates?'+new URLSearchParams({after:lastGood.cursor,...((lastGood.data_type||query().get('data_type'))?{data_type:lastGood.data_type||query().get('data_type')}: {})}),controller);
  if(version!==requestVersion)return;
  modeSettings.update(data.activity_mode,true);if(data.changed)load();
  else if(errorSource==='updates'){
   // A revision check verifies identity only; it does not renew source clocks.
   errorSource=null;$('error').hidden=true;showResultState(lastGood);
  }
 }catch(e){
  if(version===requestVersion)showError('updates','Update check failed. Displayed comparisons are preserved but could not be verified; choose Refresh to retry.');
 }finally{checking=false;if(activeUpdate===controller)activeUpdate=null;}
}
bindDialogClose($('arb-close'),$('arb-details'));$('arb-details').addEventListener('close',()=>{clearTimeout(inspectionTimer);if(dialogReturn)document.documentElement.style.overflow=dialogReturn.overflow;const target=[...document.querySelectorAll('.arb-open')].find(b=>b.dataset.pairId===returnId);(target||$('results')).focus({preventScroll:true});if(dialogReturn)scrollTo(dialogReturn.x,dialogReturn.y);dialogReturn=null;});$('refresh').onclick=load;$('previous').onclick=()=>{offset=Math.max(0,offset-30);cancelRead();load();};$('next').onclick=()=>{offset+=30;cancelRead();load();};let debounce;$('filters').onsubmit=e=>e.preventDefault();$('filters').oninput=e=>{offset=0;cancelRead();setState('loading',lastGood?'Updating… Previous results shown.':'Loading comparisons…');clearTimeout(debounce);debounce=setTimeout(load,e.target.name==='search'?180:120);};document.querySelector('a[href="/arbs"]').setAttribute('aria-current','page');load();setInterval(checkUpdates,1500);
