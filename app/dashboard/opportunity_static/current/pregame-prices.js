// Render recorded units. Venue identity never establishes a native price.
export const ratio=value=>{const [a,b='1']=String(value).split('/');return Number(a)/Number(b);};
export const isContractVenue=row=>['kalshi','polymarket_us'].includes(row.venue);
export const isPercentageVenue=row=>['novig','prophetx'].includes(row.venue);
export const hasVenuePrice=row=>Boolean(row.posted?.value!=null||row.native_price?.text);
function probabilityText(value){
 if(!/^\d+(?:\.\d+)?$/.test(value))return value+' probability';
 const [whole,fraction='']=value.split('.'),digits=fraction.padEnd(2,'0');
 return String(BigInt(whole+digits.slice(0,2)))+(digits.length>2?'.'+digits.slice(2):'')+'%';
}
export function priceDisplay(row,after=false){
 const american=(after?row.display?.after_fees:row.display?.posted_odds)||'Unavailable';
 if(after)return {primary:american,secondary:'',price:''};
 const native=row.native_price,posted=row.posted||{},value=posted.value,units=posted.units;
 if(native?.text)return {primary:native.text,secondary:native.format==='american'?'':'('+american+')',price:''};
 const normalized=units==='american_odds'&&['sportsgameodds','the_odds_api'].includes(row.source?.provider)&&
   (isContractVenue(row)||isPercentageVenue(row));
 if(value===null||value===undefined||normalized)return {primary:units==='american_odds'&&value!=null?String(value):american,secondary:'',price:'Native format unavailable'};
 const text=String(value);
 const primary=units==='american_odds'?text:
   units==='cents_per_contract'?text+'¢':units==='probability'?probabilityText(text):
   units==='decimal_odds'?text+'×':units==='percent'?text+'%':text+' '+(units||'units unknown').replaceAll('_',' ');
 return {primary,secondary:units==='american_odds'?'':'('+american+')',price:''};
}
