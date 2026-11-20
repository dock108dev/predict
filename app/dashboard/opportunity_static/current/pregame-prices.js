// Source-price presentation only. Stored quotes and financial inputs stay intact.
export const ratio=value=>{const [a,b='1']=String(value).split('/');return Number(a)/Number(b);};
const siteFormats={kalshi:'cents',polymarket_us:'cents',novig:'percent',prophetx:'percent'};
export const isContractVenue=row=>siteFormats[row.venue]==='cents';
export const isPercentageVenue=row=>siteFormats[row.venue]==='percent';
export const hasVenuePrice=row=>Boolean(row.posted?.value!=null||row.native_price?.text);
const percentage=value=>(100*value).toLocaleString('en-US',{maximumFractionDigits:2,useGrouping:false});
function impliedPrice(value,units){
 const n=ratio(value);if(!Number.isFinite(n))return null;
 const p=units==='american_odds'?(n>=100?100/(n+100):n<=-100?-n/(100-n):null):
  units==='probability'?n:units==='cents_per_contract'||units==='percent'?n/100:units==='decimal_odds'&&n>1?1/n:null;
 return p>0&&p<1?p:null;
}
export function priceDisplay(row,after=false){
 const american=(after?row.display?.after_fees:row.display?.posted_odds)||'Unavailable';
 if(after)return {primary:american,secondary:'',price:''};
 const native=row.native_price,posted=row.posted||{},value=posted.value,units=posted.units;
 if(native?.text)return {primary:native.text,secondary:native.format==='american'?'':'('+american+')',price:''};
 if(value===null||value===undefined)return {primary:american,secondary:'',price:'Source price unavailable'};
 const format=siteFormats[row.venue],p=impliedPrice(value,units);
 if(format&&p!==null)return {primary:percentage(p)+(format==='cents'?'¢':'%'),secondary:'('+american+')',price:''};
 const text=String(value);
 const primary=units==='american_odds'?text:units==='cents_per_contract'?text+'¢':
  units==='probability'?percentage(ratio(text))+'%':units==='decimal_odds'?text+'×':
  units==='percent'?text+'%':text+' '+(units||'units unknown').replaceAll('_',' ');
 return {primary,secondary:units==='american_odds'?'':'('+american+')',price:''};
}
