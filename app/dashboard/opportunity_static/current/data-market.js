import {dateTime,venue,readable,percent,odds,selection,number} from './workspace-format.js';

const node=(tag,text,cls)=>{const value=document.createElement(tag);if(text!==undefined)value.textContent=text;if(cls)value.className=cls;return value;};
function cell(row,label,...values){const cell=node('td');cell.dataset.label=label;for(const [i,value]of values.filter(v=>v!==null&&v!==undefined&&v!=='').entries())cell.append(node(i?'small':'strong',value));row.append(cell);return cell;}
const referenceBasis=offer=>{const ref=offer?.reference||offer?.calculation_payload?.reference;return ref?[venue(ref.book),number(ref.probability)===null?null:(number(ref.probability)*100).toFixed(2)+'% probability'].filter(Boolean).join(' · '):null;};
const stateLabel=row=>({in_progress:'Capture in progress',running:'Capture in progress',partial:'Partial capture',failed:'Capture failed',cancelled:'Capture cancelled',coverage_uncertain:'Coverage uncertain',legacy_unverified:'Acquisition membership unverified'})[row.state]||readable(row.reason||row.state);
function action(text,query,onNavigate){const a=node('a',text,'research-button');a.href='/data?'+query;a.onclick=event=>{if(event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();onNavigate(query);};return a;}
export function marketRow(row,query,onNavigate){
 const tr=node('tr');tr.dataset.market=row.id;const offer=row.headline;
 cell(tr,'Game / start',row.title,`${row.sport||''} · ${dateTime(row.start_at)}`,row.identity_status==='source_local'?'Source-local identity':null);
 cell(tr,'Market / exact offer',readable(row.family),offer?selection(offer):'No eligible main offer',offer?.main_role==='alternate'?'Alternate winner':null);
 cell(tr,'Venue / odds',offer?venue(offer.venue||offer.represented_venue||offer.book):null,offer?odds(offer.price,offer.price_units):null);
 const exact=new URLSearchParams(query);exact.set('market',row.id);exact.set('pull',row.pull_id);for(const key of ['game','game_key','bet','revision','offer'])exact.delete(key);
 const ev=cell(tr,'Screening EV');if(offer&&percent(offer.calculation?.net_ev_percent)!==null){exact.set('offer',offer.id);exact.set('revision',offer.revision);const link=action(percent(offer.calculation.net_ev_percent),exact,onNavigate);link.className='research-button market-ev catalog-status-'+offer.calculation.status;link.title='Inspect this exact offer and its stored calculation';ev.append(link);}else ev.append(node('strong',row.state==='complete'?readable(row.reason||'No matching reference pair in this pull'):stateLabel(row)));
 cell(tr,'Capture / references',dateTime(row.received_at),offer?.reference_basis||row.reference_basis||referenceBasis(offer)||(offer?'Same-pull reference evidence':null),row.fee_mode?.enabled===true?'Captured with fees included':null);
 const expand=new URLSearchParams(exact);expand.delete('offer');expand.delete('revision');cell(tr,'Offers').append(action('Offers & history',expand,onNavigate));return tr;
}
function referenceLabel(ref,value){
 const facts=ref.facts||ref,side=facts.side,event=value.snapshot?.event||{},source=value.snapshot?.source_event||{};
 let label=facts.outcome;
 if(side==='home'||side==='away'){
  const sourceName=source.teams?.[side]?.name||facts.teams?.[side]?.name;
  const participant=Object.entries(event.participants||{}).find(([,identity])=>identity===event[side]);
  label=sourceName||participant?.[0]||`${side==='home'?'Home':'Away'} team name unavailable`;
 }else if(side==='over'||side==='under')label=side==='over'?'Over':'Under';
 const offer={...facts,family:facts.family||facts.market,outcome:label||'Selection identity unresolved'};
 return [venue(facts.venue||facts.book||facts.original_bookmaker_id),selection(offer),odds(facts.price??facts.price_american,facts.price_units),dateTime(facts.received_at||facts.times?.received_at)].join(' · ');
}
function offerTable(root,offers,onSelect){const table=node('table',undefined,'catalog-table'),head=node('thead'),titles=node('tr');for(const text of ['Selection / line','Venue / odds','Stored EV','Inspect'])titles.append(node('th',text));head.append(titles);const body=node('tbody');for(const offer of offers){const row=node('tr');cell(row,'Selection / line',selection(offer),offer.main_role==='alternate'?'Alternate':offer.main_role!=='main'?'Main status uncertain':null);cell(row,'Venue / odds',venue(offer.venue||offer.represented_venue||offer.book),odds(offer.price,offer.price_units));cell(row,'Stored EV',percent(offer.calculation?.net_ev_percent)||readable(offer.calculation?.reason||'No matching reference pair in this pull'));const button=node('button','Inspect');button.onclick=()=>onSelect(offer);cell(row,'Inspect').append(button);body.append(row);}table.append(head,body);const scroll=node('div',undefined,'catalog-scroll');scroll.append(table);root.append(scroll);if(!offers.length)root.append(node('p','No received offers in this captured selection.'));}
export function renderMarket(root,value,{positive=false,includeAlternates=false,onSelect,onCapture}){
 root.replaceChildren();const row=value.row;root.append(node('p',`${readable(row.family)} · ${dateTime(row.received_at)} · ${row.state==='complete'?'Captured':stateLabel(row)}`));
 if(row.reason)root.append(node('p',readable(row.reason),'experiment-notice'));
 const related=node('div',undefined,'data-browser-links');
 for(const [title,params] of [['Open original odds pull',{evidence:'pulls',pull:row.pull_id}],
   ['Captures',{evidence:'checkpoints',event_id:row.event_id}],['Game scores',{evidence:'populations',event_id:row.event_id}]]){
  if(Object.values(params).some(value=>!value))continue;
  const anchor=node('a',title,'research-button');anchor.href='/data?'+new URLSearchParams(params);related.append(anchor);
 }
 if(related.childElementCount)root.append(related);
 const tabs=node('div',undefined,'market-offer-tabs'),content=node('div');root.append(tabs,content);
 const offers=value.offers||[],eligible=offers.filter(offer=>offer.main_role==='main'||includeAlternates&&offer.main_role==='alternate'),focused=positive?eligible.filter(offer=>number(offer.calculation?.net_ev_percent)>0):eligible;
 function select(label,render){const button=node('button',label);button.onclick=()=>{for(const other of tabs.children)other.setAttribute('aria-pressed',String(other===button));content.replaceChildren();render();};tabs.append(button);return button;}
 const first=select(positive?'Positive offers':'Main offers',()=>offerTable(content,focused,onSelect));
 select('Other offers',()=>offerTable(content,offers.filter(offer=>!focused.includes(offer)&&offer.main_role!=='alternate'),onSelect));
 select('Reference inputs',()=>{const references=value.reference_inputs||[];if(!references.length)content.append(node('p','No matching reference pair in this pull.'));else for(const ref of references){const p=node('p');p.textContent=referenceLabel(ref,value);content.append(p);}});
 select('Alternates',()=>offerTable(content,offers.filter(offer=>offer.main_role==='alternate'),onSelect));
 select('History',()=>{for(const capture of value.history||[]){const button=node('button',`${capture.pull_id===row.previous_capture?.pull_id?'Previous capture':'Capture'} · ${dateTime(capture.received_at||capture.requested_at)} · ${readable(capture.state)}`);button.onclick=()=>onCapture(capture);content.append(button);}if(!value.history?.length)content.append(node('p','No earlier capture retained for this market.'));});first.onclick();
}
export function renderMarketInput(root,value){
 root.replaceChildren();const offer=value.selected_offer,row=value.row;if(!offer){root.append(node('p','The exact offer is absent from this captured snapshot. No replacement has been selected.'));return ()=>{};}
 root.append(node('h3',`${row.title} · ${selection(offer)}`));
 const summary=node('div',undefined,'market-inspector-summary');summary.append(node('strong',`${readable(row.family)} · ${venue(offer.venue||offer.represented_venue||offer.book)} · ${odds(offer.price,offer.price_units)}`),node('p',`Stored screening EV ${percent(offer.calculation?.net_ev_percent)||'unavailable'} · ${dateTime(row.received_at)}`));
 const payload=offer.calculation_payload||{},reference=payload.reference||offer.reference;const mode=offer.fee_mode||payload.fee_mode||value.fee_mode;
 summary.append(node('p',mode?(mode.enabled?'Captured with fees enabled':'Fees OFF'):'Captured fee treatment not recorded'));
 if(reference)summary.append(node('p',`Reference ${venue(reference.book)} · probability ${number(reference.probability)===null?'not available':(number(reference.probability)*100).toFixed(2)+'%'}`));
 if(offer.calculation?.reason)summary.append(node('p',readable(offer.calculation.reason)));root.append(summary);
 const references=node('section');references.append(node('h3','Supporting reference prices in this pull'));const prices=reference?.prices||value.reference_inputs||[];
 for(const ref of prices)references.append(node('p',referenceLabel(ref,value)));
 if(!prices.length)references.append(node('p','No matching reference pair in this pull.'));root.append(references);
 root.append(node('p','Stored screening calculation. Price availability, exact contract and settlement limitations remain applicable.'));
 const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)+'\n'],{type:'application/json'})),download=node('a','Export this exact offer & supporting calculation','research-button');download.href=url;download.download='predict-market-offer.json';root.append(download);
 const details=node('details',undefined,'market-evidence');details.append(node('summary','Normalized record and calculation evidence'),node('pre',JSON.stringify(value,null,2)));root.append(details);
 const related=node('div',undefined,'data-browser-links');
 for(const [title,params] of [['Open original odds pull',{evidence:'pulls',pull:row.pull_id}],
   ['Captures',{evidence:'checkpoints',event_id:row.event_id}]]){
  if(Object.values(params).some(item=>!item))continue;
  const anchor=node('a',title,'research-button');anchor.href='/data?'+new URLSearchParams(params);related.append(anchor);
 }
 if(related.childElementCount)root.append(related);
 return ()=>URL.revokeObjectURL(url);
}
