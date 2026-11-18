import {ratio} from './pregame-prices.js';
// Explanations use the inspected calculation's cashflows, never current board state.
let nextId=0;
const number=ratio;
const fmt=value=>Number.isFinite(value)?value.toLocaleString('en-US',{maximumFractionDigits:5}):'Unavailable';
const money=value=>Number.isFinite(value)?'$'+value.toFixed(2):'Unavailable';
const probability=odds=>{const n=number(odds);return n>0?100/(n+100):-n/(-n+100);};
export function explanation(row,kind){
 const cash=row.fee.cashflows,committed=number(row.fee.committed_usd),win=number(cash.win.net_receipt_usd),loss=number(cash.loss.net_receipt_usd),p=number(row.reference?.probability);
 const rw=win/committed-1,rl=loss/committed-1,ev=number(row.raw.net_ev);
 const prices=row.reference?.prices||[],selected=prices.find(q=>q.side===row.reference?.selected_outcome);
 if(kind==='posted'){
  const decimal=number(row.raw.posted_decimal),cost=100/decimal;
  return ['Quoted price',`Payout multiple: ${fmt(decimal)}×. Price equivalent: ${fmt(cost)}% (${fmt(cost)}¢ per $1 payout).`,
   `American odds: ${row.display.posted_odds}.`,
   row.source.provider==='sportsgameodds'?`Converted from the aggregate feed's quoted ${row.display.posted_odds}. This is not a verified native order-book price or available size.`:`Source: ${row.source.provider}. Uses the stored quote; check the venue for current price and size.`];
 }
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
  `Winning fees: ${money(number(cash.win.total_fee_usd))}; net winning receipt: ${money(win)}.`,
  `After-fee decimal odds = net winning receipt ÷ committed cash = ${money(win)} ÷ ${money(committed)} = ${fmt(number(row.raw.after_fee_decimal))}.`,
  `After-fee payout: ${fmt(number(row.raw.after_fee_decimal))}× (${row.display.after_fees} American). Losing receipt: ${money(loss)}.`];
 if(kind==='fair'){
  const decimal=number(row.reference.fair_decimal_odds ?? row.raw.fair_decimal);
  return ['Fair odds',...(['lowest-no-vig-probability-1','lowest-no-vig-two-trusted-books-2'].includes(row.reference.selection_policy)?["Reference: the lowest no-vig win probability, requiring complete exact-line pairs from at least two trusted books.",'Eligible estimates: '+Object.entries(row.reference.candidate_probabilities||{}).map(([book,value])=>book+' '+fmt(100*number(value))+'%').join('; ')+'.']:[]),...prices.map(q=>`${q.side}${q===selected?' (selected)':''}: ${q.price_american} → implied probability ${fmt(100*probability(q.price_american))}%.`),
   selected?`Remove the book's margin: ${fmt(probability(selected.price_american))} ÷ ${fmt(prices.reduce((sum,q)=>sum+probability(q.price_american),0))} = ${fmt(p)} (${fmt(p*100)}%).`:`Fair probability: ${fmt(p*100)}%.`,
   `Fair decimal odds = 1 ÷ ${fmt(p)} = ${fmt(decimal)}.`,
   `American odds = ${decimal>=2?'100 × (decimal − 1)':'−100 ÷ (decimal − 1)'} → ${row.display.fair_odds}.`];
 }
 if(kind==='ev')return ['Net expected value',
  `Fair win probability p = ${fmt(p*100)}%.`,
  `Win return = ${money(win)} ÷ ${money(committed)} − 1 = ${fmt(rw)}. Loss return = ${money(loss)} ÷ ${money(committed)} − 1 = ${fmt(rl)}.`,
  `Net EV = p × win return + (1 − p) × loss return.`,
  `${fmt(p)} × ${fmt(rw)} + ${fmt(1-p)} × ${fmt(rl)} = ${fmt(ev)} → ${row.display.net_ev}.`];
 const simple=rl===-1&&rw>0;
 return ['Opportunity Score',ev<=0?'Nonpositive Net EV produces a score of 0.':simple?`Score = 10,000 × min(1, Net EV ÷ win return).`:'Score = 10,000 × f, where f maximizes p × log(1 + f × win return) + (1 − p) × log(1 + f × loss return), bounded by 0–1 and positive remaining wealth.',
  ...(ev>0&&simple?[`10,000 × min(1, ${fmt(ev)} ÷ ${fmt(rw)}) = ${fmt(number(row.raw.opportunity_score))}.`]:[]),
  `Displayed score: ${row.display.opportunity_score}. This ranks the opportunity; it is not a stake recommendation.`];
}
export function addMath(cell,row,kind){
 const value=cell.querySelector(':scope > span:not(.mobile-label)');
 const button=document.createElement('button');button.type='button';button.className='math-trigger';button.textContent=value.textContent;
 const lines=explanation(row,kind),popover=document.createElement('div');popover.className='math-popover';popover.id='math-'+(++nextId);popover.setAttribute('popover','auto');popover.setAttribute('role','tooltip');
 const title=document.createElement('strong');title.textContent=lines[0];popover.append(title);
 lines.slice(1).forEach(line=>{const p=document.createElement('p');p.textContent=line;popover.append(p);});
 const note=document.createElement('small');note.textContent='Inputs shown rounded; calculations use the stored exact values.';popover.append(note);
 button.setAttribute('aria-label',lines[0]+': '+value.textContent+'. Show calculation');button.setAttribute('aria-describedby',popover.id);button.setAttribute('aria-expanded','false');
 value.replaceWith(button);cell.append(popover);
 let pinned=false,timer;
 const close=()=>{clearTimeout(timer);if(popover.matches(':popover-open'))popover.hidePopover();pinned=false;button.setAttribute('aria-expanded','false');};
 const show=()=>{clearTimeout(timer);if(!popover.isConnected)return;if(!popover.matches(':popover-open'))popover.showPopover();const box=button.getBoundingClientRect();popover.style.left=Math.max(10,Math.min(innerWidth-popover.offsetWidth-10,box.right-popover.offsetWidth))+'px';popover.style.top=Math.max(10,box.bottom+8+popover.offsetHeight>innerHeight?box.top-popover.offsetHeight-8:box.bottom+8)+'px';button.setAttribute('aria-expanded','true');};
 button.addEventListener('pointerenter',event=>{if(event.pointerType!=='touch')show();});
 button.addEventListener('pointerleave',()=>{if(!pinned)timer=setTimeout(close,150);});
 button.addEventListener('focus',show);button.addEventListener('blur',()=>{if(!pinned)close();});
 button.addEventListener('click',()=>{if(pinned)close();else{pinned=true;show();}});
 popover.addEventListener('pointerenter',()=>clearTimeout(timer));popover.addEventListener('pointerleave',()=>{if(!pinned)close();});
 popover.addEventListener('toggle',event=>{if(event.newState==='closed'){pinned=false;button.setAttribute('aria-expanded','false');}});
 button.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();}});
}
