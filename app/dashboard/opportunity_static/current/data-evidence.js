import {dateTime,venue,selection,percent,odds,number} from './workspace-format.js';
import {referenceOnly,tradingContext} from './workspace-scope.js';
const node=(tag,text,cls)=>{const value=document.createElement(tag);if(text!==undefined)value.textContent=text;if(cls)value.className=cls;return value;};
const known=value=>value===null||value===undefined||value===''?'Not recorded':String(value);
const json=value=>JSON.stringify(value,null,2);
function grid(parent,values){const dl=node('dl',undefined,'research-detail-grid');for(const [key,value]of Object.entries(values))dl.append(node('dt',key),node('dd',known(value)));parent.append(dl);}
function section(parent,title){const value=node('section');value.append(node('h3',title));parent.append(value);return value;}
function evidence(parent,title,value){const details=node('details');details.append(node('summary',title),node('pre',json(value)));parent.append(details);return details;}
function table(parent,columns,rows){const value=node('table',undefined,'research-evidence-table'),head=node('thead'),headRow=node('tr');for(const title of columns)headRow.append(node('th',title));head.append(headRow);const body=node('tbody');for(const cells of rows){const tr=node('tr');for(const cell of cells)tr.append(node('td',known(cell)));body.append(tr);}value.append(head,body);parent.append(value);}
export function renderInput(root,value){
 root.replaceChildren();
 root.append(node('h3',`${value.title} · ${selection(value)}`));
 const summary=node('div',undefined,'market-inspector-summary');summary.append(node('strong',`${value.family} · ${venue(value.original_bookmaker_id)} · ${odds(value.price,value.price_units)}`),node('p',`Stored EV ${percent(value.calculation?.net_ev_percent)||'unavailable'} · captured ${dateTime(value.times?.received_at||value.captured_at)}`));
 const reference=value.calculation_payload?.reference;
 if(reference)summary.append(node('p',`Reference ${venue(reference.book)} · probability ${number(reference.probability)===null?'not recorded':(number(reference.probability)*100).toFixed(2)+'%'}`));
 if(value.calculation?.reason)summary.append(node('p',value.calculation.reason.replaceAll('_',' ')));root.append(summary);
 if(reference?.prices){const inputs=section(root,'Supporting reference prices');table(inputs,['Book','Selection / line','Odds','Received'],reference.prices.map(row=>[venue(row.venue),selection(row),odds(row.price_american),dateTime(row.received_at)]));}

 const mode=value.fee_mode||value.calculation_payload?.fee_mode;
 if(mode)root.append(node('p',mode.enabled?'Calculation captured with fees enabled.':'Calculation captured with fees off: all fees assumed to be 0.'));
 const download=node('a','Export this exact input & result','research-button');
 // The selected record is already captured. Keep its export usable after the
 // bounded SQL paging lease expires while the owner reads the calculation.
 const exportUrl=URL.createObjectURL(new Blob([json(value)+'\n'],{type:'application/json'}));
 download.href=exportUrl;download.download='predict-research-record.json';root.append(download);
 const advanced=node('details');advanced.append(node('summary','Source identities, revisions, exact arithmetic and reproduction evidence'));root.append(advanced);root=advanced;
 const source=section(root,'1. Received source input');
 grid(source,{Provider:value.provider,'Original bookmaker / venue ID':value.original_bookmaker_id,'Represented venue':value.represented_venue,'Venue equivalence':value.venue_equivalence,'Source event ID':value.event_id,'Source market / odd ID':value.source_market_id,'Original price':value.price,'Price units':value.price_units,Outcome:value.outcome,'Exact line':value.line,'Source available':value.available,'Availability reason':value.availability_reason,'Source time':value.times.source_at,'Receipt time':value.times.received_at,'Receipt hash':value.receipt_sha256,'Source revision':value.source_revision});
 if(value.raw_observations)table(source,['Outcome','Side','Price','Units','Disposition'],value.raw_observations.map(row=>[row.label,row.side,row.price,row.units,row.disposition]));
 evidence(source,'Retained source record',value.source_input);
 const identity=section(root,'2. Identity & settlement');
 grid(identity,{'Canonical event':value.identity.event_id,'Canonical contract':value.identity.contract_id,'Mapping status':value.identity.mapping_status,Settlement:value.identity.settlement,'Market family':value.family,'Source period':value.period,'Canonical period':value.identity.market?.period});
 evidence(identity,'Exact market, participant, line, outcome and result policy',value.contract||value.identity);
 if(referenceOnly(value)||tradingContext(value)){
  const context=tradingContext(value),reference=section(root,context?'3. Trading market context':'3. Reference price evidence');reference.append(node('p',context?'This retained exchange observation is trading-side context. Numeric calculation support for this market is unavailable.':'Reference only. This sportsbook price can inform prediction market calculations; it is not a sportsbook trading result.'));
  evidence(reference,'Retained source and calculation history',value.calculation_payload||value.historical_conditional_calculation||value.source_input);
  const retention=section(root,'4. Original-response retention & reproduction');grid(retention,{'Original response':value.original_response?.state,'Retention reason':value.original_response?.reason});evidence(retention,'Original-response capture metadata',value.original_response);evidence(retention,context?'Complete exported trading-market observation':'Complete exported reference observation',value);return ()=>URL.revokeObjectURL(exportUrl);
 }
 const probability=section(root,'3. Probability inputs & policy');
 const payload=value.calculation_payload,ref=payload?.reference;
 grid(probability,{'Screening policy':value.probability_policy,'Selected screening book':ref?.book,'Screening probability':ref?.probability,'Probability conditioning':ref?.conditioning});
 if(ref?.prices)table(probability,['Book','Outcome','Line','American odds','Source time','Receipt time'],ref.prices.map(row=>[row.venue,row.side,row.line,row.price_american,row.source_at,row.received_at]));
 if(value.coherent_probability){const baseline=value.coherent_probability;grid(probability,{'Evaluation baseline':baseline.policy_version,'Whole-pair book':baseline.book,'Complementary probabilities':json(baseline.probabilities),'Exceptional outcomes':baseline.exceptional_outcomes,'Baseline ID':baseline.baseline_id});evidence(probability,'Frozen coherent baseline inputs',baseline);}
 else probability.append(node('p','Coherent evaluation baseline unavailable for this stored record.'));
 for(const [policy,baseline]of Object.entries(payload?.alternative_probabilities||{})){probability.append(node('h4','Optional comparison baseline · '+policy));grid(probability,{'Whole-pair book':baseline.book,'Complementary probabilities':baseline.probabilities?json(baseline.probabilities):null,'Availability reason':baseline.reason,'Selected outcome probability':baseline.probability});evidence(probability,'Exact optional baseline inputs',baseline);}
 const fee=section(root,'4. Fees, quantity & cashflows');
 const finance=payload?.fee||value.price_payload?.fee;
 if(finance){grid(fee,{'Fee classification':finance.classification,'Purchase USD':finance.purchase_usd,'Entry USD':finance.entry_usd,'Reserve USD':finance.reserve_usd,'Committed USD':finance.committed_usd,Quantity:finance.quantity,'Quantity increment':finance.quantity_increment});table(fee,['Settlement state','Exact cashflow'],Object.entries(finance.cashflows||{}).map(([state,cashflow])=>[state,json(cashflow)]));evidence(fee,'Fee applicability, schedule and rounding evidence',value.fee_input||finance);}
 else fee.append(node('p','Fee-qualified cashflows unavailable. '+(value.calculation.reason||'No fee result retained.')));
 const result=section(root,'5. Calculation result');
 grid(result,{Status:value.calculation.status,'Unavailable reason':value.calculation.reason,'Calculation freshness':value.calculation.freshness,'Exact net EV ratio':value.calculation.net_ev_ratio,'Net EV percent':value.calculation.net_ev_percent,'Displayed net EV':value.calculation.display,'Calculation version':value.calculation_version,'Input revision':value.calculation_revision,'Calculated at':value.times.calculated_at,'Eligibility deadline':value.times.valid_until});
 if(ref&&finance){result.append(node('p',`EV = p × (win net receipt / committed cash − 1) + (1 − p) × (loss net receipt / committed cash − 1). Frozen p = ${ref.probability}; committed cash = ${finance.committed_usd}.`));}
 if(value.calculation_association){result.append(node('p',value.calculation_association));grid(result,{'Calculation source time':value.calculation_input_times?.source_at,'Calculation receipt time':value.calculation_input_times?.received_at});}
 evidence(result,'Exact calculation payload',payload);
 if(value.historical_conditional_calculation){result.append(node('p','The previous numeric result assumed venue fee applicability that has not been established. It is retained as a historical conditional witness. Current net EV remains unavailable.'));evidence(result,'Historical conditional calculation · venue fee applicability unestablished',value.historical_conditional_calculation);}
 const retention=section(root,'6. Original-response retention & reproduction');
 grid(retention,{'Original response':value.original_response?.state,'Retention reason':value.original_response?.reason});evidence(retention,'Original-response capture metadata',value.original_response);retention.append(node('p',value.reproduction));evidence(retention,'Complete exported record',value);
 return ()=>URL.revokeObjectURL(exportUrl);
}
