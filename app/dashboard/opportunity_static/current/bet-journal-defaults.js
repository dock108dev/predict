// Editable sizing suggestions use the saved quote, never a newer board price.
const ratio=value=>{if(value===null||value===undefined||value==='')return null;const [a,b='1']=String(value).split('/'),n=Number(a)/Number(b);return Number.isFinite(n)?n:null;};
const amount=value=>value===null?'':String(Math.round(value*100)/100);
function decimal(row){
  const raw=ratio(row.raw?.posted_decimal);if(raw>1)return raw;
  const p=row.posted||{},value=ratio(p.value);
  if(value!==null){
    if(p.units==='decimal_odds'&&value>1)return value;
    if(['probability','contract_price','price','dollars'].includes(p.units)&&value>0&&value<1)return 1/value;
    if(['cents','price_cents'].includes(p.units)&&value>0&&value<100)return 100/value;
    if(p.units==='american_odds'&&Math.abs(value)>=100)return value>0?1+value/100:1+100/-value;
  }
  const american=ratio(row.display?.posted_odds);return Math.abs(american)>=100?(american>0?1+american/100:1+100/-american):null;
}
function suggestedLeg(row,stake){
  const d=decimal(row),contract=['kalshi','polymarket_us'].includes(row.venue);
  const american=d>1?(d>=2?100*(d-1):-100/(d-1)):null;
  return {quote_id:row.id,stake:amount(stake),price:contract?(d>1?String(Number((1/d).toFixed(8))):''):(row.display?.posted_odds||row.posted?.value||(american!==null?String(Number(american.toFixed(6))):'')),units:contract?'probability':'american_odds'};
}
export function suggestedTrades(entry){
  const rows=entry.kind==='arb'?entry.snapshot.legs:[entry.snapshot];
  if(entry.kind!=='arb'){
    const d=decimal(rows[0]),stake=d>1?(d<2?100/(d-1):100):null;
    return [suggestedLeg(rows[0],stake)];
  }
  // Balance the two modeled decisive-state receipts on a $200 stake budget.
  // Fees scale the saved model for an editable estimate, not an executable fill.
  const deltas=rows.map(row=>{
    const cost=ratio(row.fee?.committed_usd),entry=ratio(row.fee?.entry_usd),win=ratio(row.fee?.cashflows?.win?.net_receipt_usd),loss=ratio(row.fee?.cashflows?.loss?.net_receipt_usd),stake=cost!==null&&entry!==null?cost-entry:null;
    return stake>0&&win!==null&&loss!==null?(win-loss)/stake:decimal(row);
  });
  if(deltas.some(value=>!(value>0)))return rows.map(row=>suggestedLeg(row,null));
  const first=Math.max(.01,Math.min(199.99,Math.round(20000*deltas[1]/(deltas[0]+deltas[1]))/100));
  return [suggestedLeg(rows[0],first),suggestedLeg(rows[1],Math.round((200-first)*100)/100)];
}
