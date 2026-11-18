import {journalAction} from './bet-journal-actions.js';
import {bookName} from './pregame-labels.js';
import {priceDisplay,isContractVenue,ratio} from './pregame-prices.js';
import {addMath} from './pregame-math.js';
const $=id=>document.getElementById(id);
let offset=0,lastGood=null,running=false,checking=false,queued=false,returnId,deadlineTimer,inspectionTimer,requestVersion=0,errorSource=null;
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const money=v=>'$'+ratio(v).toFixed(2);
function pick(r){let line=r.selection.signed_line,team=r.selection_label||r.selection.participant||'';if(line!==undefined&&line!==null)line=ratio(line);return r.family==='total'?(r.side==='over'?'Over ':'Under ')+line:team+(r.family==='spread'?' '+(line>0?'+':'')+line:' to win');}
function value(row,after=false){
 const display=priceDisplay(row,after),cell=node('span',undefined,'math-value arb-price-value');
 cell.append(node('span',display.primary));
 if(after||isContractVenue(row))addMath(cell,row,after?'after':'posted');
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
 item.append(heading,prices);
 if(amount){
  const context=node('div',undefined,'arb-leg-context');
  if(official[row.venue]){const link=node('a','Open '+(bookName(row.venue))+' ↗');link.href=official[row.venue];link.target='_blank';link.rel='noopener noreferrer';context.append(link);}
  context.append(node('p','Committed '+money(row.fee.committed_usd),'arb-context'),node('p','Source '+new Date(row.times.source_at||row.times.received_at).toLocaleString(),'arb-context'),node('p','Received '+new Date(row.times.received_at).toLocaleString(),'arb-context'));
  item.append(context);
 }
 return item;
}
function card(pair){const d=node('article',undefined,'arb-card'),subject=node('div',undefined,'arb-subject'),h=node('h2'),open=node('button',pair.game,'arb-open');open.type='button';open.dataset.pairId=pair.id;open.setAttribute('aria-haspopup','dialog');open.setAttribute('aria-label','Inspect two-sided prices: '+pair.game);open.onclick=()=>inspect(pair);h.append(open);subject.append(node('p',pair.league+' · '+new Date(pair.kickoff).toLocaleString('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+' ET','game-clock'),h,node('p',(pair.category==='market_book'?'Market ↔ Sportsbook':'Market ↔ Market')+' · '+({moneyline:'Winner',spread:'Spread',total:'Total'})[pair.family],'arb-context'));const result=node('div',undefined,'arb-return');result.append(node('strong',pair.display_return),node('small','Paired return after fees'),node('small','Instant size unknown'));d.append(subject,...pair.legs.map(r=>leg(r)),result);return d;}
function inspect(pair){const frozen=structuredClone(pair);returnId=pair.id;const content=$('arb-content'),summary=node('div',undefined,'arb-summary');for(const [label,text]of [['Cash committed',money(frozen.committed_usd)],['Minimum modeled profit',money(frozen.minimum_profit_usd)],['After-fee return',frozen.display_return]]){const v=node('div',label);v.append(node('strong',text));summary.append(v);}const legs=node('div',undefined,'arb-detail-legs');legs.append(...frozen.legs.map(r=>leg(r,true)));const table=node('table',undefined,'arb-states'),head=node('thead'),tr=node('tr');for(const text of ['Completed-game outcome','Net receipts','Net profit'])tr.append(node('th',text));head.append(tr);const body=node('tbody');frozen.legs.forEach((row,i)=>{const tr=node('tr');for(const text of [pick(row)+' wins',money(frozen.receipts_usd[i]),money(frozen.profits_usd[i])])tr.append(node('td',text));body.append(tr);});table.append(head,body);const risk=node('p',frozen.settlement_note+' '+frozen.liquidity_note+' Both legs must fill at the modeled prices. Partial fills, price changes and different venue rules can create losses.','arb-risk'),math=node('details');math.append(node('summary','How this comparison is calculated'),node('p','Using up to $100 total, the model balances the two completed-game net receipts, repricing fees and legal quantity increments for each leg. State profit = both net receipts in that state − total cash committed. Paired return = the lower state profit ÷ total cash committed. This bounded allocation is illustrative, not a recommended stake or an execution maximum. Unused cash: '+money(frozen.unused_usd)+'. No sportsbook fair probability or EV is used.','comparison-context'));const link=node('a','Arbitrage assumptions, order types and sources ↗');link.href='/about#arbitrage';$('arb-title').textContent=frozen.game;content.replaceChildren(summary,legs,journalAction('arb',frozen,'Save arbitrage to My Bets'),table,risk,math,link);$('arb-details').showModal();clearTimeout(inspectionTimer);inspectionTimer=setTimeout(()=>$('arb-details').close(),Math.min(2147483647,Math.max(0,Date.parse(frozen.kickoff)-Date.now())));}
function query(){const q=new URLSearchParams({offset:String(offset),limit:'30'});for(const [key,v]of new FormData($('filters')))if(v&&key!=='alternates')q.set(key,v);return q;}
function showError(source,message){
 if(source==='updates'&&errorSource==='load')return;
 errorSource=source;$('error').textContent=message;$('error').hidden=false;
}
function render(data){
 lastGood=data;
 const book=$('book'),selectedBook=book.value,available=new Set(data.sportsbooks||[]);
 // An empty or filtered result must not silently clear the user's book filter.
 if(selectedBook)available.add(selectedBook);
 book.replaceChildren(new Option('All sportsbooks',''),...[...available].map(name=>new Option(bookName(name),name)));
 book.value=selectedBook;
 const results=$('results');results.replaceChildren(...data.rows.map(card));
 if(!data.rows.length){
  const empty=node('div',undefined,'empty');
  empty.append(node('h2','No positive after-fee pairs match this view.'),node('p','Both market-to-market and market-to-sportsbook prices are checked. No positive pair does not mean executable arbitrage is unavailable elsewhere.'));results.append(empty);
 }
 $('count').textContent=data.total+' price-arb '+(data.total===1?'candidate':'candidates');
 $('previous').disabled=offset===0;$('next').disabled=offset+30>=data.total;
 $('page').textContent=data.total?`${offset+1}–${Math.min(offset+30,data.total)} of ${data.total}`:'0';
 errorSource=null;$('error').hidden=true;
 clearTimeout(deadlineTimer);
 if(data.refresh_at)deadlineTimer=setTimeout(load,Math.min(2147483647,Math.max(30,Date.parse(data.refresh_at)-Date.now()+30)));
}
async function load(){
 if(running){queued=true;return;}
 running=true;const version=requestVersion;
 try{
  const response=await fetch('/api/pregame/arbs?'+query(),{cache:'no-store'});
  if(!response.ok)throw Error('Read failed');
  const data=await response.json();
  if(version===requestVersion)render(data);
 }catch(e){
  if(version===requestVersion)showError('load',lastGood?'Refresh failed. Displayed comparisons are preserved; verify current prices before acting.':'Comparisons could not be loaded. Choose Refresh to retry.');
 }finally{
  running=false;if(queued){queued=false;load();}
 }
}
async function checkUpdates(){
 if(running||checking||document.hidden||!lastGood)return;
 checking=true;
 try{
  const response=await fetch('/api/pregame/updates?after='+encodeURIComponent(lastGood.cursor),{cache:'no-store'});
  if(!response.ok)throw Error('Update check failed');
  const data=await response.json();
  if(errorSource==='updates'){errorSource=null;$('error').hidden=true;}
  if(data.changed)load();
 }catch(e){
  showError('updates','Update check failed. Displayed comparisons are preserved; verify current prices before acting.');
 }finally{checking=false;}
}
$('arb-close').onclick=()=>$('arb-details').close();$('arb-details').addEventListener('close',()=>{clearTimeout(inspectionTimer);const target=[...document.querySelectorAll('.arb-open')].find(b=>b.dataset.pairId===returnId);(target||$('results')).focus({preventScroll:true});});$('refresh').onclick=load;$('previous').onclick=()=>{offset=Math.max(0,offset-30);requestVersion++;load();};$('next').onclick=()=>{offset+=30;requestVersion++;load();};let debounce;$('filters').onsubmit=e=>e.preventDefault();$('filters').oninput=e=>{offset=0;requestVersion++;clearTimeout(debounce);debounce=setTimeout(load,e.target.name==='search'?180:0);};document.querySelector('a[href="/arbs"]').setAttribute('aria-current','page');load();setInterval(checkUpdates,1500);
