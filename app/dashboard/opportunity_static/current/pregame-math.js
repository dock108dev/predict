import {addEVPreview,dismissEVPreview} from './ev-preview.js';
import {rankingCatalog} from './pregame-ranking.js';
import {ratio} from './pregame-prices.js';
import {bindDismissControl} from './dialog-close.js';
// Explanations use the inspected calculation's cashflows, never current board state.
let nextId=0;
const number=ratio;
const fmt=value=>Number.isFinite(value)?value.toLocaleString('en-US',{maximumFractionDigits:5}):'Unavailable';
const money=value=>Number.isFinite(value)?'$'+value.toFixed(2):'Unavailable';
const probability=odds=>{const n=number(odds);return n>0?100/(n+100):-n/(-n+100);};
export function explanation(row,kind){
 if(kind!=='posted'&&!row.fee?.cashflows?.win)return ['Calculation unavailable','The stored price is inspectable, but complete fee and cashflow inputs are unavailable.'];
 if(['fair','ev','ranking'].includes(kind)&&!row.reference)return ['EV unavailable',row.ev_unavailable_reason?.replaceAll('_',' ')||'A complete exact-line probability reference is unavailable. The quoted price is not a zero-EV estimate.'];
 if(kind==='posted'){
  const decimal=number(row.raw.posted_decimal),cost=100/decimal;
  return ['Quoted price',`Payout multiple: ${fmt(decimal)}×. Price equivalent: ${fmt(cost)}% (${fmt(cost)}¢ per $1 payout).`,
   `American odds: ${row.display.posted_odds}.`,
   row.source.provider==='sportsgameodds'?`Converted from the aggregate feed's quoted ${row.display.posted_odds}. This is not a verified native order-book price or available size.`:`Source: ${row.source.provider}. Uses the stored quote; check the venue for current price and size.`];
 }
 const cash=row.fee.cashflows,committed=number(row.fee.committed_usd),win=number(cash.win.net_receipt_usd),loss=number(cash.loss.net_receipt_usd),p=number(row.reference?.probability);
 const rw=win/committed-1,rl=loss/committed-1,ev=number(row.raw.net_ev);
 const prices=row.reference?.prices||[],selected=prices.find(q=>q.side===row.reference?.selected_outcome);
 const rule=row.fee.evidence?.database_fee_rule,trace=row.fee.rounding_trace?.[0],feeMath=[];
 if(rule&&trace){
  const rate=number(rule.rate),price=1/number(row.raw.posted_decimal),quantity=number(cash.win.gross_receipt_usd),stake=committed-number(row.fee.entry_usd)-number(row.fee.reserve_usd||'0');
  if(rule.formula==='prophetx_commission')feeMath.push(`Commission = rate × gross profit = ${fmt(rate)} × (${money(quantity)} − ${money(stake)}) = ${money(number(trace.raw))} before rounding.`);
  else feeMath.push(`Raw fee = rate × payout units × price × (1 − price)${rule.formula==='kalshi_taker'?' × multiplier':''} = ${fmt(rate)} × ${fmt(quantity)} × ${fmt(price)} × ${fmt(1-price)}${rule.formula==='kalshi_taker'?' × '+fmt(number(rule.multiplier)):''} = ${money(number(trace.raw))}.`);
  const rounding={polymarket_taker:'nearest cent, ties to even',novig_pregame:'nearest $0.00001, half up',prophetx_nhl_taker:'nearest cent, half up',prophetx_commission:'up to the next cent',kalshi_taker:'charge up to $0.000001, then committed cash up to balance precision'}[rule.formula];
  feeMath.push(`Rounding: ${rounding||'documented schedule'}. Entry ${money(number(trace.entry))}; settlement ${money(number(trace.settlement))}.`);
 }
 if(kind==='after')return ['After-fee odds',...feeMath,
  `Committed cash: ${money(committed)}; entry fee: ${money(number(row.fee.entry_usd))}.`,
  `Winning total fees (including the acquisition fee already committed): ${money(number(cash.win.total_fee_usd))}; net winning receipt: ${money(win)}.`,
  `Additional winning settlement charge: ${money(number(cash.win.settlement_fee_usd??String(number(cash.win.total_fee_usd)-number(row.fee.entry_usd))))}. Net winning profit = receipt − committed cash = ${money(win-committed)}.`,
  `After-fee decimal odds = net winning receipt ÷ committed cash = ${money(win)} ÷ ${money(committed)} = ${fmt(number(row.raw.after_fee_decimal))}.`,
  `Effective price = 100 ÷ after-fee decimal odds = ${fmt(100/number(row.raw.after_fee_decimal))}%. This includes modeled fees; it is not the posted venue price.`,
  `After-fee payout: ${fmt(number(row.raw.after_fee_decimal))}× (${row.display.after_fees} American). Losing receipt: ${money(loss)}.`];
 if(kind==='fair'){
  const decimal=number(row.reference.fair_decimal_odds ?? row.raw.fair_decimal);
  return ['Fair odds',...(['lowest-no-vig-probability-1','lowest-no-vig-two-trusted-books-2'].includes(row.reference.selection_policy)?["Reference: the lowest no-vig win probability, requiring complete exact-line pairs from at least two trusted books.",'Eligible estimates: '+Object.entries(row.reference.candidate_probabilities||{}).map(([book,value])=>book+' '+fmt(100*number(value))+'%').join('; ')+'.']:[]),...prices.map(q=>`${q.side}${q===selected?' (selected)':''}: ${q.price_american} → implied probability ${fmt(100*probability(q.price_american))}%.`),
   selected?`Remove the book's margin: ${fmt(probability(selected.price_american))} ÷ ${fmt(prices.reduce((sum,q)=>sum+probability(q.price_american),0))} = ${fmt(p)} (${fmt(p*100)}%).`:`Fair probability: ${fmt(p*100)}%.`,
   `Fair decimal odds = 1 ÷ ${fmt(p)} = ${fmt(decimal)}.`,
   `American odds = ${decimal>=2?'100 × (decimal − 1)':'−100 ÷ (decimal − 1)'} → ${row.display.fair_odds}.`];
 }
 if(kind==='ev')return ['Net expected value',
  'EV is modeled expected profit relative to total cash committed, conditional on the reference probability and fee inputs. It does not establish current executable size.',
  `Fair win probability p = ${fmt(p*100)}%.`,
  `Win return = ${money(win)} ÷ ${money(committed)} − 1 = ${fmt(rw)}. Loss return = ${money(loss)} ÷ ${money(committed)} − 1 = ${fmt(rl)}.`,
  `Net EV = p × win return + (1 − p) × loss return.`,
  `${fmt(p)} × ${fmt(rw)} + ${fmt(1-p)} × ${fmt(rl)} = ${fmt(ev)} → ${row.display.net_ev}.`];
 if(kind==='ranking'){
  const rank=row.ranking;
  if(!rank)return ['Ranking unavailable','Refresh to load this ranking. The quoted prices and Net EV remain available.'];
  const f=number(row.raw.opportunity_score)/10000;
  const formula=rankingCatalog.methods[rank.method].explanation;
  return [rank.label,formula,`Reference win probability: ${fmt(p*100)}%. Win return: ${fmt(rw)}. Loss return: ${fmt(rl)}.`,
   ...(rank.method==='growth'?[`Model-optimal Kelly fraction f = ${fmt(f)}. Growth is shown in natural-log basis points.`]:[]),
   `Displayed value: ${rank.display} ${rank.unit}. All eligible picks are sorted before pagination.`,
   'The probability estimate is a model input. This is not a stake recommendation or a guarantee of profit.'];
 }
 throw Error('Unsupported calculation detail: '+kind);
}
let activeMath;
const dismissMath=()=>activeMath?.close();
document.addEventListener('scroll',event=>{
 if(!activeMath||activeMath.popover.contains(event.target))return;
 const target=event.target===document?document.scrollingElement:event.target;
 const before=activeMath.scrollOffsets.get(target);
 // Focusing a lower comparison value can queue a scroll event before opening.
 // Dismiss only for movement after the popover's actual opening position.
 if(!before||before[0]!==target.scrollTop||before[1]!==target.scrollLeft)dismissMath();
},true);
window.addEventListener('resize',dismissMath);
document.addEventListener('close',event=>{if(activeMath&&event.target.contains(activeMath.button))dismissMath();},true);
document.addEventListener('focusin',event=>{if(activeMath&&event.target!==activeMath.button&&!activeMath.popover.contains(event.target))dismissMath();});
document.addEventListener('keydown',event=>{
 if(event.key==='Escape'&&activeMath?.popover.matches(':popover-open')){event.preventDefault();event.stopImmediatePropagation();activeMath.close(true);}
},true);
export function addMath(cell,row,kind){
 const value=cell.querySelector(':scope > span:not(.mobile-label)');
 const button=document.createElement('button');button.type='button';button.className='math-trigger';button.textContent=value.textContent;
 button.dataset.focusKey=row.id+'-'+kind;
 const lines=explanation(row,kind);
 button.setAttribute('aria-label',lines[0]+': '+value.textContent+'. Show calculation');button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-expanded','false');
 value.replaceWith(button);
 if(kind==='ev')addEVPreview(button,cell,row);
 let popover;
 const close=(restore=false)=>{if(popover?.matches(':popover-open'))popover.hidePopover();button.setAttribute('aria-expanded','false');if(activeMath?.button===button)activeMath=null;if(restore&&button.isConnected)button.focus({preventScroll:true});};
 // The board needs the numeric controls now; build explanatory content only on demand.
 const ensurePopover=()=>{
  if(popover)return popover;
  popover=document.createElement('div');popover.className='math-popover';popover.id='math-'+(++nextId);popover.setAttribute('popover','auto');popover.setAttribute('role','dialog');
  const heading=document.createElement('div');heading.className='math-heading';
  const title=document.createElement('strong');title.id=popover.id+'-title';title.textContent=lines[0];popover.setAttribute('aria-labelledby',title.id);
  const done=document.createElement('button');done.type='button';done.className='math-close';done.textContent='Close';done.setAttribute('aria-label','Close calculation');heading.append(title,done);
  const body=document.createElement('div');body.className='math-body';
  lines.slice(1).forEach(line=>{const p=document.createElement('p');p.textContent=line;body.append(p);});
  const note=document.createElement('small');note.textContent='Inputs shown rounded; calculations use the stored exact values.';body.append(note);popover.append(heading,body);
  cell.append(popover);button.setAttribute('aria-controls',popover.id);
  bindDismissControl(done,()=>close(true),()=>popover.matches(':popover-open'));
  popover.addEventListener('toggle',event=>{if(event.newState==='closed'){button.setAttribute('aria-expanded','false');if(activeMath?.popover===popover)activeMath=null;}});
  return popover;
 };
 button.onclick=()=>{
  dismissEVPreview();
  if(popover?.matches(':popover-open')){close(true);return;}
  dismissMath();if(!button.isConnected)return;ensurePopover().showPopover();
  const header=button.closest('dialog')?.querySelector('.dialog-heading');
  const safeTop=Math.max(12,(header?.getBoundingClientRect().bottom||0)+8);
  popover.style.maxHeight=Math.max(40,innerHeight-safeTop-12)+'px';
  const box=button.getBoundingClientRect();
  popover.style.left=Math.max(12,Math.min(innerWidth-popover.offsetWidth-12,box.right-popover.offsetWidth))+'px';
  const below=box.bottom+8,above=box.top-popover.offsetHeight-8;
  popover.style.top=Math.max(safeTop,Math.min(innerHeight-popover.offsetHeight-12,below+popover.offsetHeight<=innerHeight-12?below:above))+'px';
  const scrollOffsets=new Map();for(let parent=button.parentElement;parent;parent=parent.parentElement)scrollOffsets.set(parent,[parent.scrollTop,parent.scrollLeft]);
  scrollOffsets.set(document.scrollingElement,[document.scrollingElement.scrollTop,document.scrollingElement.scrollLeft]);
  button.setAttribute('aria-expanded','true');activeMath={button,popover,close,scrollOffsets};
 };
}
