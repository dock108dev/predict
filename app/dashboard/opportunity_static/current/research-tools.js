import {bookName} from './pregame-labels.js';
import {ratio} from './pregame-prices.js';
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
const money=v=>Number.isFinite(ratio(v))?'$'+ratio(v).toFixed(2):'Unavailable';
const official={kalshi:'https://kalshi.com/',polymarket_us:'https://polymarket.us/',novig:'https://www.novig.us/',prophetx:'https://www.prophetx.co/',fanduel:'https://sportsbook.fanduel.com/',draftkings:'https://sportsbook.draftkings.com/',betmgm:'https://sports.betmgm.com/',caesars:'https://sportsbook.caesars.com/',betrivers:'https://www.betrivers.com/'};
export function sizeEvidence(row){
 const size=row.available_size,section=node('p',undefined,'size-evidence');
 section.append(node('strong',size?.status==='observed'?`Observed size: ${size.quantity} ${size.unit} at this price`:'Available size: Unknown'));
 section.append(node('small',size?.status==='observed'?`${size.reason} Source ${size.source_at||'unknown'}; received ${size.received_at}.`:'No price-specific quantity is supplied. Illustrative cash does not establish a fillable amount.'));
 return section;
}
export function verification(row,pick){
 const section=node('section',undefined,'venue-verification'),linkInfo=row.verification_link;
 const summary=[row.game,new Date(row.kickoff).toLocaleString('en-US',{timeZone:'America/New_York',dateStyle:'medium',timeStyle:'short'})+' ET',(row.period||'full_game').replaceAll('_',' '),row.family,pick,bookName(row.venue),'Source '+(row.posted?.units==='american_odds'?row.posted.value:row.display.posted_odds)+' American'].join(' · ');
 if(linkInfo?.url||official[row.venue]){const link=node('a',linkInfo?.scope==='market'?'Open retained market link ↗':'Open '+bookName(row.venue)+' home ↗ (generic)');link.href=linkInfo?.url||official[row.venue];link.target='_blank';link.rel='noopener noreferrer';section.append(link);}
 const copy=node('button','Copy venue check');copy.type='button';const status=node('span');status.setAttribute('role','status');
 copy.onclick=async()=>{try{await navigator.clipboard.writeText(summary);status.textContent='Copied';}catch{status.textContent='Select and copy the summary below.';detail.open=true;}};
 const detail=node('details'),text=node('p',summary);detail.append(node('summary','Exact opportunity to verify'),text);section.append(copy,status,detail);return section;
}
export function oldestLeg(pair){
 const ages=pair.legs.map(r=>Date.parse(r.times?.source_at));
 if(!ages.every(Number.isFinite))return 'Older leg: age unknown';
 const minutes=Math.max(0,Math.floor((Date.now()-Math.min(...ages))/60000));
 return 'Older leg: '+(minutes<60?minutes+'m':Math.floor(minutes/60)+'h '+minutes%60+'m')+' ago';
}
// This component has no journal dependency. Recording always uses the inspected quote.
export function amountResearch(kind,snapshot,renderResult,{dataType='all'}={}){
 const frozen=structuredClone(snapshot),section=node('section',undefined,'amount-research');
 const heading=node('h3','Explore an amount'),intro=node('p','Read-only research · total cash budget, including acquisition fees. No quote or bet is saved.','comparison-context');
 const form=node('form'),label=node('label','Illustrative cash budget ($)'),input=node('input');input.type='number';input.min='0.01';input.max='1000000';input.step='0.01';input.value=kind==='arb'?String(ratio(snapshot.basis_usd||'100')):String(ratio(snapshot.fee?.comparison_basis_usd||'100'));input.required=true;input.setAttribute('aria-label','Illustrative cash budget');label.append(input);
 const presets=node('div',undefined,'amount-presets');for(const value of [25,100,500]){const button=node('button','$'+value);button.type='button';button.onclick=()=>{input.value=String(value);form.requestSubmit();};presets.append(button);}
 const apply=node('button','Evaluate amount');apply.type='submit';const status=node('p',undefined,'comparison-context');status.setAttribute('role','status');const output=node('div',undefined,'amount-result'),overview=kind==='arb'?node('div',undefined,'amount-overview'):null;
 const draw=result=>{renderResult(output,result);if(overview){const summary=output.querySelector('.arb-summary');if(summary)overview.replaceChildren(summary);}};
 let revision=0,controller;
 form.onsubmit=async event=>{event.preventDefault();if(!form.reportValidity())return;const token=++revision;controller?.abort();controller=new AbortController();const requestController=controller,requestedAmount=input.value;status.textContent='Evaluating modeled cashflows… Previous calculation shown.';output.setAttribute('aria-busy','true');const timer=setTimeout(()=>requestController.abort(),12000);
  try{const response=await fetch('/api/pregame/research?'+new URLSearchParams({data_type:dataType||'all'}),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,snapshot:frozen,amount:requestedAmount}),signal:requestController.signal});const data=await response.json();if(token!==revision)return;if(!response.ok)throw Error(data.error||'Amount calculation unavailable.');draw(data.result);status.textContent='Modeled for up to '+money(requestedAmount)+' total cash. Size remains unverified. No records saved.';}
  catch(e){if(token===revision)status.textContent=(e.name==='AbortError'?'Amount request timed out. Choose Evaluate amount to retry.':e.message)+' Previous calculation is preserved.';}
  finally{clearTimeout(timer);if(token===revision)output.removeAttribute('aria-busy');}
 };
 draw(frozen);form.append(label,presets,apply);if(overview)section.append(overview,heading,intro,form,status,output);else section.append(output,heading,intro,form,status);return section;
}
