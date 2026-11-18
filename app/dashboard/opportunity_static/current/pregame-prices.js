// Venue-style equivalents of the stored posted price; no quote or tick is invented.
export const ratio=value=>{const [a,b='1']=String(value).split('/');return Number(a)/Number(b);};
export const isContractVenue=row=>['kalshi','polymarket_us'].includes(row.venue);
const fixed=value=>value.toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:2});
export function priceDisplay(row,after=false){
 const american=after?row.display.after_fees:row.display.posted_odds;
 if(!isContractVenue(row))return {primary:american,secondary:'',price:''};
 const decimal=ratio(after?row.raw.after_fee_decimal:row.raw.posted_decimal);
 if(!Number.isFinite(decimal)||decimal<=1)return {primary:american,secondary:'',price:''};
 const cost=100/decimal;
 return {primary:row.venue==='kalshi'&&!after?fixed(cost)+'¢':decimal.toFixed(2)+'×',
         secondary:'('+american+')',
         price:row.venue==='polymarket_us'&&!after?fixed(cost)+'% price':!after?decimal.toFixed(2)+'× payout':''};
}
