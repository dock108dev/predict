import {ratio} from './pregame-prices.js';

// Original source clocks stay inspectable; age is a quiet timestamp, never a banner.
const number=value=>value===null||value===undefined||value===''?NaN:ratio(value);
const money=value=>Number.isFinite(value)?(value<0?'-$':'$')+Math.abs(value).toFixed(2):'Unavailable';
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
function ageText(clock,now){
 const ms=Date.parse(clock),age=now-ms;
 if(!Number.isFinite(ms))return 'age unknown';
 if(age<0)return 'future timestamp · verify clock';
 if(age<60000)return Math.floor(age/1000)+'s ago';
 if(age<3600000)return Math.floor(age/60000)+'m ago';
 if(age<86400000)return Math.floor(age/3600000)+'h '+Math.floor(age%3600000/60000)+'m ago';
 return Math.floor(age/86400000)+'d ago';
}
export function freshnessText(row,now=Date.now()){
 const quote=row.times?.source_at,prices=row.reference?.prices||[];
 const clocks=prices.map(p=>Date.parse(p.source_at));
 const reference=clocks.length&&clocks.every(Number.isFinite)?Math.min(...clocks):NaN;
 const texts=['Quote '+ageText(quote,now)];
 if(row.reference)texts.push('Reference '+(Number.isFinite(reference)?ageText(new Date(reference).toISOString(),now):'age unknown'));
 return texts.join(' · ');
}
export function freshness(row){
 const e=node('span',freshnessText(row),'quote-evidence');
 e.dataset.evidence=JSON.stringify({times:row.times,reference:row.reference?{prices:row.reference.prices}:null});
 e.title='Original quote: '+(row.times?.source_at||'not supplied')+'. Reference timestamps: '+((row.reference?.prices||[]).map(p=>p.source_at||'unknown').join(', ')||'not supplied')+'. Calculation time does not renew these prices.';
 return e;
}
setInterval(()=>{for(const e of document.querySelectorAll('[data-evidence]')){e.textContent=freshnessText(JSON.parse(e.dataset.evidence));}},30000);

export function feeRows(row){
 const fee=row.fee||{},cash=fee.cashflows||{},entry=number(fee.entry_usd),committed=number(fee.committed_usd),reserve=number(fee.reserve_usd??'0');
 const rows=[['Stake / purchase amount',money(committed-entry-reserve)],['Total upfront cash committed',money(committed)],['Acquisition fee (included upfront)',money(entry)]];
 if(reserve)rows.push(['Reserved cash (included upfront)',money(reserve)]);
 for(const [state,label] of [['win','Winning'],['loss','Losing']]){
  const c=cash[state]||{},total=number(c.total_fee_usd),settlement=number(c.settlement_fee_usd??(Number.isFinite(total)&&Number.isFinite(entry)?total-entry:undefined));
  rows.push([label+' additional settlement charge',money(settlement)],[label+' total fees (includes acquisition fee)',money(total)],[label+' total receipt after fees',money(number(c.net_receipt_usd))],[label+' net profit',money(number(c.net_receipt_usd)-committed)]);
 }
 return rows;
}
export function payoutExample(row){
 const section=node('section',undefined,'payout-example'),fee=row.fee||{},cash=fee.cashflows||{};
 const committed=number(fee.committed_usd),entry=number(fee.entry_usd),reserve=number(fee.reserve_usd??'0'),win=number(cash.win?.net_receipt_usd);
 section.append(node('h3','What this price means'));
 if(!Number.isFinite(committed)||!Number.isFinite(win)){section.append(node('p','Price available; payout and fees are not fully available. Verify the venue terms.'));return section;}
 section.append(node('p',money(committed-entry-reserve)+' stake / purchase → '+money(committed)+' committed upfront → '+money(win)+' total returned if this pick wins → '+money(win-committed)+' net profit.','payout-summary'));
 const loss=node('p','If it loses: '+money(number(cash.loss?.net_receipt_usd))+' returned; '+money(number(cash.loss?.net_receipt_usd)-committed)+' net profit. This is an illustrative calculation; available size is unknown.');
 const detail=node('details'),dl=node('dl');detail.append(node('summary','Upfront and outcome fees'),loss);
 for(const [label,value]of feeRows(row))dl.append(node('dt',label),node('dd',value));detail.append(dl);section.append(detail);
 if(row.reference&&row.raw?.net_ev!==null&&row.raw?.net_ev!==undefined)detail.append(node('p','Modeled EV '+(row.display.net_ev||'unavailable')+' means expected profit of '+money(number(row.raw.net_ev)*committed)+' on '+money(committed)+' committed, conditional on the reference probability and these fee inputs. It is not a promised return.'));
 else detail.append(node('p','Price available; EV unavailable'+(row.ev_unavailable_reason?': '+row.ev_unavailable_reason.replaceAll('_',' '):'. Probability inputs are not available.')));
 return section;
}
