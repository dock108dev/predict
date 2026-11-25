import {bookName} from './pregame-labels.js';
import {bindDialogClose} from './dialog-close.js';
import {createDraftGuard} from './journal-editor-state.js';
import {priceDisplay} from './pregame-prices.js';
import {suggestedTrades} from './bet-journal-defaults.js';

const $=id=>document.getElementById(id), initial=new URLSearchParams(location.search);
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
const ratio=value=>{if(value===null||value===undefined||value==='')return null;const [a,b='1']=String(value).split('/'),n=Number(a)/Number(b);return Number.isFinite(n)?n:null;};
const money=value=>{const n=ratio(value);return n===null?'Unavailable':n.toLocaleString('en-US',{style:'currency',currency:'USD'});};
const percent=(value,unit='%')=>{const n=ratio(value);return n===null?'Unavailable':(n>0?'+':'')+(n*100).toFixed(2)+unit;};
const decimal=value=>{const n=ratio(value);return n===null?'':String(Number(n.toFixed(8)));};
const when=value=>value?new Date(value).toLocaleString('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})+' ET':'Not supplied';
const exactWhen=value=>value?new Date(value).toLocaleString('en-US',{timeZone:'America/New_York',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',second:'2-digit'})+' ET':'Not supplied';
const localInput=value=>{if(!value)return '';const date=new Date(value);return new Date(date-date.getTimezoneOffset()*60000).toISOString().slice(0,19);};
const iso=value=>value?new Date(value).toISOString():null;
const legs=entry=>entry.kind==='arb'?entry.snapshot.legs:[entry.snapshot];
let packet=null,tab=['log','research'].includes(initial.get('view'))?initial.get('view'):'placed',editing=null,returnFocus=null,loading=false,initialOpened=false,offset=0,sequence=0,queued=false;

function pick(row){
  const s=row.selection||{},line=ratio(s.signed_line),team=row.selection_label||(s.participant||'').split(':').pop();
  if(row.family==='total')return (s.predicate==='over'||row.side==='over'?'Over ':'Under ')+(line??'');
  return (team||row.game||'Selection')+(row.family==='spread'?' '+(line>0?'+':'')+(line??''):' to win');
}
function observedPrice(row){
  const display=priceDisplay(row);return [display.primary,display.secondary,display.price].filter(Boolean).join(' ');
}
function tradeDecimal(trade){
  const n=ratio(trade?.price);if(n===null)return null;
  return trade.units==='probability'?(n>0&&n<1?1/n:null):trade.units==='decimal_odds'?(n>1?n:null):Math.abs(n)>=100?(n>0?1+n/100:1-100/n):null;
}
function priceText(d,row){
  if(!(d>1))return 'Unavailable';const american=d>=2?100*(d-1):-100/(d-1),odds=(american>=0?'+':'')+Math.round(american);
  return odds+' · '+(100/d).toFixed(2)+'% equivalent';
}
function tradePrice(trade,row={}){return trade?priceText(tradeDecimal(trade),row):'Not entered';}
function cashflows(trade){
  const stake=ratio(trade?.stake),d=tradeDecimal(trade),fees=['entry_fee','win_fee','loss_fee'].map(k=>ratio(trade?.[k]));
  if(!(stake>0)||!(d>1)||fees.some(v=>v===null))return null;
  const [entry,win,loss]=fees;return {cost:stake+entry,win:stake*d-win,loss:-loss,netDecimal:(stake*d-win)/(stake+entry)};
}
function priceStrip(row,trade){
  const strip=node('div',undefined,'journal-entry-prices'),flows=cashflows(trade);
  const priceMetric=(label,d)=>{const [primary,equivalent]=priceText(d,row).split(' · ');return metric(label,primary,equivalent);};
  const after=priceMetric('After fees',flows?.netDecimal);if(flows)after.append(node('small',(ratio(trade.entry_fee)>0?'Entry fee '+money(trade.entry_fee)+' · ':'')+'Win fee '+money(trade.win_fee)));
  strip.append(priceMetric('Entry · before fees',tradeDecimal(trade)),after,metric('Win return',flows?money(flows.win):'Unavailable',flows?'Total paid '+money(flows.cost):undefined));return strip;
}
function metric(label,value,help){const d=node('div',undefined,'journal-figure');d.append(node('span',label),node('strong',value));if(help)d.append(node('small',help));return d;}
function closeAge(seconds){if(seconds===null||seconds===undefined)return '';if(seconds<60)return Math.round(seconds)+'s before kickoff';if(seconds<3600)return Math.round(seconds/60)+'m before kickoff';return (seconds/3600).toFixed(1)+'h before kickoff';}

function quoteHistory(entry){
  const details=node('details',undefined,'journal-history');details.append(node('summary','Quote history'));
  const status=node('p','Open to load the retained quote trail.'),list=node('ol',undefined,'journal-history-list'),controls=node('div',undefined,'journal-history-controls'),older=node('button','← Older'),newer=node('button','Newer →');older.type=newer.type='button';controls.append(older,newer);controls.hidden=true;details.append(status,list,controls);
  let quotes=null,page=0,busy=false;
  function render(){
    const end=Math.max(0,quotes.length-page*100),start=Math.max(0,end-100),rows=quotes.slice(start,end);
    status.textContent=quotes.length?`Showing ${start+1}–${end} of ${quotes.length} retained observations · oldest first within this page.`:'No additional quote observations have been retained.';
    list.start=start+1;list.replaceChildren(...rows.map(quote=>{
      const item=node('li'),heading=node('p',undefined,'journal-history-quote');heading.append(node('strong',bookName(quote.venue)+' · '+pick(quote)+' · '+observedPrice(quote)));
      const ev=quote.raw?.net_ev!==null&&quote.raw?.net_ev!==undefined?percent(quote.raw.net_ev):quote.display?.net_ev;
      if(ev)heading.append(node('span','Net EV '+ev));item.append(heading);
      const ref=quote.reference;if(ref){const p=ratio(ref.probability);item.append(node('p','Fair reference: '+bookName(ref.book||'Unknown')+(ref.fair_odds?' · '+ref.fair_odds:'')+(p!==null?' · '+(p*100).toFixed(2)+'% fair probability':'')));}
      item.append(node('p','Recorded '+exactWhen(quote.observed_at)+' · Source '+exactWhen(quote.times?.source_at)+' · Received '+exactWhen(quote.times?.received_at),'journal-history-clocks'));return item;
    }));
    controls.hidden=quotes.length<=100;older.disabled=start===0;newer.disabled=page===0;
  }
  older.onclick=()=>{page++;render();};newer.onclick=()=>{page=Math.max(0,page-1);render();};
  details.addEventListener('toggle',async()=>{
    if(!details.open||quotes||busy)return;busy=true;status.textContent='Loading quote history…';
    try{const response=await fetch('/api/bet-journal/'+encodeURIComponent(entry.id),{cache:'no-store'});if(!response.ok)throw Error('Read failed');const data=await response.json();quotes=(data.quotes||[]).slice().sort((a,b)=>Date.parse(a.observed_at)-Date.parse(b.observed_at));render();}
    catch(e){status.textContent='Quote history could not be loaded. Close and reopen to retry.';}finally{busy=false;}
  });return details;
}

function drawSummary(){
  const s=packet.summary||{},all=packet.entries||[],placed=all.filter(e=>e.decision==='placed'),settled=placed.filter(e=>e.metrics?.realized_profit_usd!==null&&e.metrics?.realized_profit_usd!==undefined);
  const profit=settled.reduce((sum,e)=>sum+(ratio(e.metrics.realized_profit_usd)||0),0);
  const count=s.counts||{},settledCount=s.settled??settled.length;
  const stats=[['Placed bets',count.placed??placed.length],['Settled bets',settledCount],['Net profit',money(settledCount?s.realized_profit_usd??profit:null)],['Settled ROI',percent(s.realized_roi)]];
  $('summary').replaceChildren(...stats.map(([label,value])=>{const d=node('div',undefined,'journal-stat');d.append(node('span',label),node('strong',String(value)));return d;}));
  const performance=[
    ['Entry expected profit',money(s.expected_profit_usd),(s.expected_count??0)+' trades with entry EV'],
    ['Settled ROI',percent(s.realized_roi),settledCount+' settled trades'],
    ['Mean price CLV',percent(s.average_price_clv),(s.clv_leg_count??0)+' legs · before fees'],
    ['Closes captured',(s.closes_captured??0)+' / '+(s.closes_due??0),s.closes_due?'Due pregame closes':'No closes due yet'],
    ['Result − expected',money(s.realized_minus_expected_usd),(s.matched_settled_count??0)+' matched settled trades'],
  ];
  $('performance').replaceChildren(...performance.map(([label,value,coverage])=>{const d=node('div');d.append(node('span',label),node('strong',value),node('small',coverage));return d;}));
  const monitor=packet.monitor||{},at=monitor.monitor_checked_at||monitor.sampled_at||monitor.last_sample_at||monitor.updated_at||monitor.at;
  $('monitor').textContent=monitor.monitor_state==='error'||monitor.error?'Tracking needs attention. The last quote sample failed; saved records are preserved.':at?'Quote tracking last checked '+when(at)+'. Close means the last captured pregame quote; each leg shows its actual timestamp.':'Automatic tracking starts with available quotes. Missing closing quotes stay unavailable.';
}
function priceDetails(entry){
  const m=entry.metrics||{},details=node('details',undefined,'journal-details');details.append(node('summary','Observed → actual → '+(m.close_state==='closed'?'close':'latest')+' · prices & CLV'));
  if(m.deferred){
    const status=node('p','Open to load closing prices and analysis.');status.setAttribute('role','status');details.append(status);
    let busy=false,loaded=false;
    details.addEventListener('toggle',async()=>{
      if(!details.open||busy||loaded)return;busy=true;status.textContent='Loading closing prices and analysis…';
      try{
        const response=await fetch('/api/bet-journal/'+encodeURIComponent(entry.id),{cache:'no-store'});if(!response.ok)throw Error('Read failed');const data=await response.json();
        if(!data.entry||data.entry.id!==entry.id||data.entry.metrics?.deferred)throw Error('Incomplete record');
        if(!details.isConnected)return;
        const full=priceDetails(data.entry);status.replaceWith(...Array.from(full.children).slice(1));loaded=true;
      }catch(e){if(details.isConnected)status.textContent='Closing analysis could not be loaded. Close and reopen to retry.';}finally{busy=false;}
    });return details;
  }
  const grid=node('div',undefined,'journal-prices');
  legs(entry).forEach((row,i)=>{
    const data=m.legs?.[i]||{},trade=entry.trade?.legs?.[i],quote=data.close_quote||data.latest_quote;
    const leg=node('section',undefined,'journal-price-leg');leg.append(node('h3',bookName(row.venue)+' · '+pick(row)));
    const values=node('div',undefined,'journal-price-grid');
    for(const [label,value,time]of [['Observed',observedPrice(row),row.times?.source_at||row.times?.received_at],['Actual',tradePrice(trade,row),entry.trade?.placed_at],[data.close_quote?'Last pregame close':'Latest captured',quote?observedPrice(quote):'Unavailable',quote?.times?.source_at||quote?.times?.received_at]]){
      const p=node('p',label);p.append(node('strong',value),node('small',time?when(time):'Time unavailable'));values.append(p);
    }
    leg.append(values);
    const clv=node('p','Price CLV '+percent(data.clv)+' · Fair-value CLV'+(data.close_reference_basis==='harder_line_probability_lower_bound'?' bound':data.close_reference_basis==='alternate_line_interpolation'?' estimate':'')+' '+percent(data.fair_clv)+' · before fees');
    if(data.close_quote&&data.close_gap_seconds!==undefined)clv.append(node('small',' · '+closeAge(data.close_gap_seconds)));
    leg.append(clv); if(data.close_reference_basis==='harder_line_probability_lower_bound')leg.append(node('p',data.close_reference_quote?.reference?.estimate_note||'Estimated conservative value from a harder line. Exact closing line unavailable.'));
    if(data.price_slippage!==null&&data.price_slippage!==undefined)leg.append(node('p','Actual price vs observed: '+percent(data.price_slippage)+' in decimal payout · before fees.'));
    if(data.entry_reference_book||data.close_reference_book)leg.append(node('p','Fair reference: '+bookName(data.entry_reference_book||'unavailable')+(data.entry_reference_at?' · known '+when(data.entry_reference_at):'')+' at '+(entry.trade?.placed_at?'placement':'observation')+' → '+bookName(data.close_reference_book||'unavailable')+' at close.'));
    if(data.entry_reference_gap_seconds!==null&&data.entry_reference_gap_seconds!==undefined)leg.append(node('p','Entry reference source age: '+Math.round(data.entry_reference_gap_seconds)+' seconds at '+(entry.trade?.placed_at?'placement':'observation')+'.'));
    if(data.close_reference_book&&data.reference_gap_seconds!==null&&data.reference_gap_seconds!==undefined)leg.append(node('p','Closing reference recorded '+closeAge(data.reference_gap_seconds)+'.'));
    grid.append(leg);
  });
  const figures=node('div',undefined,'journal-figures'),actual=m.basis==='reported_trade',estimated=(m.legs||[]).some(l=>l.close_reference_basis==='alternate_line_interpolation'),bound=(m.legs||[]).some(l=>l.close_reference_basis==='harder_line_probability_lower_bound');
  if(entry.kind==='arb')figures.append(metric('Observed paired return',percent(m.observed_arb_return??entry.snapshot.return_rate)),metric(actual?'Actual minimum profit':'Modeled minimum profit',money(m.entry_min_profit_usd),percent(m.entry_arb_return)+' paired return'),metric('Closing quote model return',percent(m.close_arb_return),money(m.close_min_profit_usd)+' modeled profit · '+money(m.close_cost_usd)+' basis'),metric('Entry EV',percent(m.entry_ev)));
  else figures.append(metric('Observed EV',percent(m.observed_ev??entry.snapshot.raw?.net_ev)),metric(actual?'Actual entry EV':'Modeled entry EV',percent(m.entry_ev),m.entry_ev_usd!=null?money(m.entry_ev_usd)+' expected profit':undefined));
  figures.append(metric('Entry EV at close'+(bound?' (bound)':estimated?' (estimated)':''),percent(m.close_ev),m.close_ev_usd!=null?money(m.close_ev_usd)+' at closing fair probability':undefined));details.append(figures);
  if(entry.kind==='ev'&&m.close_market_ev!=null)details.append(node('p','Closing offer EV'+(estimated?' (estimated)':'')+' '+percent(m.close_market_ev)+' · Entry EV at close keeps your original trade cashflows fixed.'));
  if(['closed','missing'].includes(m.close_state))details.append(closingPrices(entry));
  details.append(grid,node('p','Price CLV = actual decimal payout ÷ closing market decimal payout − 1. Fair-value CLV uses the closing no-vig reference probability. Positive values mean the entry price beat that benchmark.'));
  if(m.reasons?.length)details.append(node('p','Unavailable metrics: '+m.reasons.map(v=>String(v).replaceAll('_',' ')).join(' · ')));
  if(m.basis==='observed_model')details.append(node('p','Entry metrics currently use the observed modeled comparison. Enter the actual trade to measure what you got.'));
  if(m.entry_probability_basis)details.append(node('p',m.entry_probability_basis));
  const change=entry.kind==='arb'?m.arb_return_slippage:m.ev_slippage;
  if(change!==null&&change!==undefined)details.append(node('p',(entry.kind==='arb'?'Paired return':'Entry EV')+' changed '+percent(change,' percentage points')+' from the original observation.'));
  if(m.realized_minus_entry_ev_usd!==null&&m.realized_minus_entry_ev_usd!==undefined)details.append(node('p','Reported result minus entry expected profit: '+money(m.realized_minus_entry_ev_usd)+'.'));
  details.append(quoteHistory(entry));
  return details;
}
function closingPrices(entry){
  const section=node('section',undefined,'journal-closes');section.setAttribute('aria-label','Closing prices');
  legs(entry).forEach((row,i)=>{
    const data=entry.metrics?.legs?.[i]||{},market=data.close_quote,fair=data.closing_fair;
    const grid=node('div',undefined,'journal-closing-grid');
    const venue=node('div',undefined,'journal-close');venue.append(node('span','Exact-pick close · '+bookName(row.venue)),node('strong',pick(row)+' · '+(market?observedPrice(market):'Unavailable')));
    venue.append(node('small',market?'Last captured '+when(market.times?.source_at):'No pregame quote retained for this exact pick.'));
    const reference=node('div',undefined,'journal-close'),estimated=fair?.basis==='alternate_line_interpolation',bound=fair?.basis==='harder_line_probability_lower_bound';
    reference.append(node('span',(estimated?'Estimated fair close':bound?'Fair close bound':'Closing fair odds')+(fair?' · '+bookName(fair.book):'')),node('strong',fair?(fair.fair_odds||'Unavailable'):'Unavailable'));
    if(fair){
      reference.append(node('small',pick({...row,selection:fair.selection})+(fair.posted_odds?' · '+(fair.posted_estimated?'estimated book price ':'book price ')+fair.posted_odds:'')+' · oldest input '+when(fair.source_at)));
      if(estimated){
        reference.append(node('small','Alternate bracket: '+[...fair.alternate_lines].sort((a,b)=>ratio(a.selection.signed_line)-ratio(b.selection.signed_line)).map(alt=>pick({...row,selection:alt.selection})+' · '+alt.fair_odds+' fair').join(' ↔ ')));
        reference.append(node('small','Interpolated fair probability '+(ratio(fair.probability)*100).toFixed(2)+'% · range '+fair.probability_range.map(p=>(ratio(p)*100).toFixed(2)+'%').join('–')));
      }else if(bound)reference.append(node('small','One-sided estimate from a harder alternate; an exact closing pair was unavailable.'));
      reference.append(node('small','Best eligible book under the board’s reference policy.'));
    }else reference.append(node('small','No qualified exact pair or alternate bracket retained.'));
    grid.append(venue,reference);section.append(grid);
  });return section;
}
function card(entry){
  const snapshot=entry.snapshot,m=entry.metrics||{},article=node('article',undefined,'journal-entry');article.dataset.entryId=entry.id;
  const settled=Boolean(entry.trade?.result),head=node('header',undefined,'journal-entry-head'),subject=node('div'),caption=node('p',(entry.kind==='arb'?'ARBITRAGE':'EV BET')+' · '+(snapshot.league||'')+' · '+when(snapshot.kickoff),'journal-caption');caption.append(node('span',settled?'Settled':entry.decision,'journal-decision '+entry.decision));
  subject.append(caption,node('h2',entry.kind==='arb'?snapshot.game:pick(snapshot)));if(entry.kind!=='arb')subject.append(node('p',snapshot.game,'journal-observed'));
  const edit=node('button',entry.decision==='observed'?'Record bet':entry.decision==='placed'&&!settled?'Set result':'Edit bet');edit.type='button';edit.onclick=()=>openEditor(entry,edit);head.append(subject,edit);article.append(head);
  if(entry.trade){
    legs(entry).forEach((row,i)=>{const trade=entry.trade.legs?.[i],line=node('section',undefined,'journal-position');line.append(node('h3',bookName(trade?.venue||row.venue)+(entry.kind==='arb'?' · '+pick(row):'')+' · '+money(trade?.stake)+' staked'));line.append(priceStrip(row,trade));article.append(line);});
    const settlement=m.settlement,result=node('div',undefined,'journal-result-line');result.append(node('span',settled?'Net result':'Result pending'),node('strong',settled?money(m.realized_profit_usd):'Pick Win / Loss / Tie'));
    if(settled){const outcomes=entry.trade.result.outcomes;result.append(node('span',outcomes?outcomes.map(v=>v==='push'?'Tie · refund':v==='win'?'Win':'Loss').join(' / '):'Cash adjustment'));if(settlement?.total_receipts_usd!=null)result.append(node('span','Returned '+money(settlement.total_receipts_usd)));if(m.realized_roi!=null)result.append(node('span',percent(m.realized_roi)+' ROI'));if(settlement?.state==='unavailable')result.append(node('span','Saved fee terms unavailable; adjust returned cash to record the actual result.'));}article.append(result);
  }else{
    article.append(node('p',legs(entry).map(row=>bookName(row.venue)+' · '+(entry.kind==='arb'?pick(row)+' · ':'')+observedPrice(row)).join(' / '),'journal-observed'));
    if(entry.kind==='arb'){const observed=node('div',undefined,'journal-entry-prices journal-observed-arb');observed.append(metric('Observed paired return',percent(snapshot.return_rate)),metric('Modeled minimum profit',money(snapshot.minimum_profit_usd)),metric('Modeled total paid',money(snapshot.committed_usd??snapshot.basis_usd)));article.append(observed);}
    else article.append(node('p','Enter stake and entry price to track your return.','journal-observed'));
  }
  article.append(priceDetails(entry));if(entry.notes)article.append(node('p',entry.notes,'journal-notes'));return article;
}
function render(){
  if(!packet)return;drawSummary();$('bets-tab').setAttribute('aria-pressed',String(tab==='placed'));$('research-tab').setAttribute('aria-pressed',String(tab==='research'));$('log-tab').setAttribute('aria-pressed',String(tab==='log'));
  document.querySelector('.status-line>span').textContent=tab==='placed'?'Open bets first':'Newest observed first';
  const entries=packet.entries||[],total=packet.total??entries.length;
  $('count').textContent=total+' '+(total===1?'record':'records');$('results').replaceChildren(...entries.map(card));
  $('previous').disabled=offset===0;$('next').disabled=offset+entries.length>=total;$('page').textContent=total?`${offset+1}–${Math.min(offset+entries.length,total)} of ${total}`:'0';
  if(!entries.length){const empty=node('div',undefined,'journal-empty');empty.append(node('h2',tab==='placed'?'Your next bet starts with a saved quote.':'No logged opportunities match this view.'),node('p',tab==='placed'?'Save an EV bet or arbitrage comparison, then enter the odds, stake and fees you actually got. Positive market-to-market arbs are logged in the Opportunity log.':'Unique, positive market-to-market arbs are logged automatically. EVs appear only when you save them to My Bets.'));const link=node('a','Browse opportunities →');link.href='/';empty.append(link);$('results').append(empty);}
}
function query(){const q=new URLSearchParams({view:tab,limit:'100',offset:String(offset),defer_observed:'1'});for(const [k,v]of new FormData($('filters')))if(v)q.set(k,v);return q;}
async function load(){
  if(loading){queued=true;return;}loading=true;const token=sequence;$('refresh').disabled=true;
  try{
    const response=await fetch('/api/bet-journal?'+query(),{cache:'no-store'});if(!response.ok)throw Error('Read failed');const next=await response.json();if(token!==sequence)return;
    packet=next;render();$('error').hidden=true;
    if(!initialOpened&&initial.has('entry')){initialOpened=true;const selectedResponse=await fetch('/api/bet-journal/'+encodeURIComponent(initial.get('entry')),{cache:'no-store'});if(selectedResponse.ok){const data=await selectedResponse.json();openEditor(data.entry);}else{$('error').textContent='The requested entry could not be found in this journal.';$('error').hidden=false;}}
  }catch(e){$('error').textContent=packet?'Journal refresh failed. Your displayed records are preserved.':'The journal could not be loaded. Choose Refresh to retry.';$('error').hidden=false;if(!packet)$('count').textContent='Journal unavailable';}
  finally{loading=false;$('refresh').disabled=false;if(queued){queued=false;load();}}
}
function field(label,name,value='',{required=false,help,type='number'}={}){
  const wrap=node('label',undefined,'journal-field');wrap.append(document.createTextNode(label));if(help)wrap.append(node('small',help));
  const input=node('input');input.name=name;input.type=type;input.value=value??'';input.required=required;
  if(type==='number'){input.step='any';input.inputMode='decimal';}if(type==='text')input.inputMode='decimal';wrap.append(input);return wrap;
}
function legEditor(row,i,values){
  const fieldset=node('fieldset');fieldset.append(node('legend',bookName(row.venue)+' · '+pick(row)));
  fieldset.append(node('p','Original quote · '+observedPrice(row)+' · '+bookName(row.venue),'journal-observed-detail'));
  const grid=node('div',undefined,'journal-form-grid'),price=field('Entry price · before fees','price-'+i,decimal(values.price),{type:'text'}),input=price.querySelector('input');input.dataset.originalValue=input.value;input.dataset.exactValue=values.price;
  const unitWrap=node('label','Price format','journal-field'),unit=node('select');unit.name='units-'+i;unit.append(new Option('American odds','american_odds'),new Option('Contract price (0–1)','probability'));unit.value=values.units;unit.dataset.originalValue=values.units;unitWrap.append(unit);
  grid.append(field('Stake placed ($)','stake-'+i,decimal(values.stake),{required:true}),price);fieldset.append(grid);
  const format=node('details',undefined,'journal-price-format'),formatLabel=node('summary');const describeFormat=()=>{formatLabel.textContent='Price format · '+(unit.value==='probability'?'Contract price (0–1)':'American odds');};describeFormat();unit.addEventListener('change',describeFormat);format.append(formatLabel,unitWrap);fieldset.append(format);
  const actualOptions=node('details',undefined,'journal-price-format');actualOptions.append(node('summary','Actual venue & fees'));
  const venueWrap=node('label','Actual venue','journal-field'),venue=node('select');venue.name='actual-venue-'+i;
  for(const key of new Set([row.venue,'kalshi','polymarket_us','novig','prophetx','fanduel','draftkings','pinnacle','betmgm','caesars']))venue.append(new Option(bookName(key),key));venue.value=values.venue||row.venue;venueWrap.append(venue);
  const override=node('label',undefined,'journal-manual'),checkbox=node('input');checkbox.type='checkbox';checkbox.name='actual-fees-'+i;checkbox.checked=values.fee_basis==='user_reported';override.append(checkbox,node('span','Use actual fees instead of the saved schedule'));
  const feeInputs=node('div',undefined,'journal-form-grid');feeInputs.hidden=!checkbox.checked;
  for(const [key,label]of [['entry_fee','Entry fee paid ($)'],['win_fee','Additional fee if won ($)'],['loss_fee','Additional fee if lost ($)']]){const wrap=field(label,key+'-'+i,decimal(values[key]));wrap.querySelector('input').min='0';feeInputs.append(wrap);}
  checkbox.onchange=()=>feeInputs.hidden=!checkbox.checked;venue.onchange=()=>{if(venue.value!==row.venue){checkbox.checked=true;feeInputs.hidden=false;}};
  actualOptions.append(venueWrap,override,node('p','Entry fees are paid upfront. Outcome fees are additional charges, deducted once from returned cash. Changing venues requires explicit fees.','journal-observed-detail'),feeInputs);fieldset.append(actualOptions);
  const preview=node('div',undefined,'journal-leg-preview');preview.id='leg-preview-'+i;fieldset.append(preview);
  const group=node('div',undefined,'journal-outcomes');group.setAttribute('role','group');group.setAttribute('aria-label','Result · '+bookName(row.venue));
  for(const [value,label]of [['pending','Pending'],['win','Win'],['loss','Loss'],['push','Tie · refund']]){const wrap=node('label'),radio=node('input');radio.type='radio';radio.name='outcome-'+i;radio.value=value;radio.checked=(editing.trade?.result?.outcomes?.[i]||'pending')===value;wrap.append(radio,node('span',label));group.append(wrap);}fieldset.append(group);fieldset.querySelector('[name="stake-'+i+'"]').min='.01';return fieldset;
}
let previewTimer,previewSequence=0;
function showPreview(entry){
  legs(entry).forEach((row,i)=>{const target=$('leg-preview-'+i);if(target)target.replaceChildren(priceStrip(row,entry.trade?.legs?.[i]));});
  const m=entry.metrics||{},settlement=m.settlement,target=$('settlement-preview');target.replaceChildren();
  const hasResult=Boolean(entry.trade?.result),figures=node('div',undefined,'journal-preview-total');figures.append(metric('Returned cash',hasResult?money(settlement?.total_receipts_usd):'Pending'),metric('Net profit',hasResult?money(m.realized_profit_usd):'Pending'),metric('ROI',hasResult?percent(m.realized_roi):'Pending'));target.append(figures);if(settlement?.state==='unavailable')target.append(node('p','This quote has incomplete fee terms. Enter a cash adjustment for the actual returned amount.','journal-observed-detail'));
}
async function updatePreview(){
  if(!editing)return;const request=++previewSequence,id=editing.id;
  let trade;try{trade=tradeFromForm();}catch(e){$('settlement-preview').replaceChildren(node('p',e.message,'journal-observed-detail'));return;}
  try{const response=await fetch('/api/bet-journal/'+encodeURIComponent(id)+'/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision:$('edit-form').elements.decision.value,trade})});if(!response.ok)throw Error('Preview unavailable');const data=await response.json();if(editing?.id===id&&request===previewSequence)showPreview(data.entry);}
  catch(e){if(editing?.id===id&&request===previewSequence){for(const row of document.querySelectorAll('.journal-leg-preview'))row.replaceChildren(node('p','After-fee preview unavailable. Your entries are preserved.','journal-observed-detail'));$('settlement-preview').replaceChildren();}}
}
$('edit-form').addEventListener('input',event=>{
  if(event.target.name?.startsWith('outcome-')){$('edit-form').elements.manual_result.checked=false;$('settlement').open=false;}
  if(['notes','result_notes','placed_at'].includes(event.target.name))return;
  previewSequence++;clearTimeout(previewTimer);
  if(/^(stake|price|units)-/.test(event.target.name))for(const row of document.querySelectorAll('.journal-leg-preview'))row.replaceChildren(node('p','Calculating after-fee return…','journal-observed-detail'));
  $('settlement-preview').replaceChildren(node('p','Calculating result…','journal-preview-total journal-observed-detail'));previewTimer=setTimeout(updatePreview,250);
});
let editorBusy=false,saveAttempt;
const draftGuard=createDraftGuard({dialog:$('editor'),form:$('edit-form'),busy:()=>editorBusy,onRestore:()=>updatePreview()});
function lockEditor(locked){editorBusy=locked;for(const field of $('edit-form').querySelectorAll('input,select,textarea,button'))if(field.id!=='cancel')field.disabled=locked;}
async function openEditor(entry,trigger){
  lockEditor(false);saveAttempt=null;editing=structuredClone(entry);const session=editing;returnFocus=trigger||document.activeElement;const form=$('edit-form'),snapshot=entry.snapshot;
  $('editor-title').textContent=entry.kind==='arb'?snapshot.game:pick(snapshot);$('entry-context').replaceChildren(node('p',snapshot.game+' · '+when(snapshot.kickoff),'journal-observed-detail'),node('p',entry.trade?'Edit your entry or pick the result. Tie refunds the stake.':entry.kind==='arb'?'Suggested $200 total stake, split across both legs. Confirm what you placed.':'Suggested stake: win $100 at negative odds; stake $100 at positive odds. Confirm what you placed.','journal-observed-detail'));
  form.elements.decision.value=['saved','observed'].includes(entry.decision)?'placed':entry.decision;form.elements.notes.value=entry.notes||'';form.elements.placed_at.value=localInput(entry.trade?.placed_at);form.elements.settled_at.value=localInput(entry.trade?.result?.settled_at);form.elements.result_notes.value=entry.trade?.result?.notes||'';
  const defaults=suggestedTrades(entry);if(initial.get('record')==='1'&&!entry.trade){for(const value of defaults)value.stake='';$('entry-context').lastChild.textContent='Enter the stake and odds you actually got. The original source quote stays fixed.';}$('trade-legs').replaceChildren(...legs(entry).map((row,i)=>legEditor(row,i,entry.trade?.legs?.[i]||defaults[i])));
  $('result-legs').replaceChildren(...legs(entry).map((row,i)=>field('Leg '+(i+1)+' · '+bookName(row.venue)+' · net returned cash ($)','receipt-'+i,entry.trade?.result?.receipts_usd?.[i]??'',{help:'After all settlement charges; includes any returned stake'})));
  form.elements.manual_result.checked=Boolean(entry.trade?.result?.receipts_usd);$('more-options').open=false;$('settlement').open=form.elements.manual_result.checked;$('delete-confirmation').hidden=true;$('delete').disabled=false;$('confirm-delete').disabled=false;$('edit-status').textContent='';$('audit-data').textContent=JSON.stringify({original_snapshot:entry.snapshot},null,2);$('audit').open=false;$('save').disabled=false;
  draftGuard.start(entry.id);if(!$('editor').open)$('editor').showModal();document.querySelector('.journal-editor-body').scrollTop=0;showPreview(entry);updatePreview();
  try{const response=await fetch('/api/bet-journal/'+encodeURIComponent(entry.id),{cache:'no-store'});if(!response.ok)return;const data=await response.json();if(editing===session)$('audit-data').textContent=JSON.stringify({original_snapshot:entry.snapshot,history:data.history,quote_observations:data.quotes},null,2);}catch(e){/* Editing remains available with the loaded snapshot. */}
}
function tradeFromForm(){
  const form=$('edit-form'),values=new FormData(form),actual=legs(editing).map((row,i)=>{
    const stake=values.get('stake-'+i);if(!stake||Number(stake)<=0)throw Error('Enter the stake placed for each leg.');
    const leg={quote_id:row.id,stake},price=form.elements['price-'+i],units=form.elements['units-'+i];
    if(editing.trade?.legs?.[i]||price.value!==price.dataset.originalValue||units.value!==units.dataset.originalValue){leg.price=price.value===price.dataset.originalValue&&units.value===units.dataset.originalValue?price.dataset.exactValue:price.value;leg.units=units.value;}
    const venue=values.get('actual-venue-'+i);if(venue!==row.venue||editing.trade?.legs?.[i]?.venue)leg.venue=venue;
    if(form.elements['actual-fees-'+i].checked)for(const key of ['entry_fee','win_fee','loss_fee'])leg[key]=values.get(key+'-'+i);
    return leg;
  });
  const trade={automatic:true,legs:actual,placed_at:iso(values.get('placed_at')),result:null};
  const result={settled_at:iso(values.get('settled_at')),notes:values.get('result_notes')||''};
  if(form.elements.manual_result.checked){
    const receipts=legs(editing).map((_,i)=>values.get('receipt-'+i)||null);if(receipts.some(v=>v===null))throw Error('Enter returned cash for every leg to record an adjustment.');trade.result={...result,receipts_usd:receipts};
  }else{
    const outcomes=legs(editing).map((_,i)=>values.get('outcome-'+i)||'pending');
    if(outcomes.some(v=>v!=='pending')){if(outcomes.some(v=>v==='pending'))throw Error('Pick a result for each leg, or leave all legs Pending.');trade.result={...result,outcomes};}
  }
  return trade;
}
function validateFields(){
 const form=$('edit-form');let first;
 for(const error of form.querySelectorAll('.field-error'))error.remove();for(const input of form.querySelectorAll('[aria-invalid]')){input.removeAttribute('aria-invalid');input.removeAttribute('aria-describedby');}
 const invalid=(input,message)=>{const text=node('small',message,'field-error');text.id=input.name+'-error';input.setAttribute('aria-invalid','true');input.setAttribute('aria-describedby',text.id);input.closest('label').append(text);input.closest('details')?.setAttribute('open','');first||=input;};
 legs(editing).forEach((row,i)=>{
  const stake=form.elements['stake-'+i],price=form.elements['price-'+i],units=form.elements['units-'+i].value;
  if(!stake.value||!Number.isFinite(Number(stake.value))||Number(stake.value)<=0)invalid(stake,'Enter a stake greater than $0.');
  const odds=ratio(price.value);if(odds===null||(units==='american_odds'?Math.abs(odds)<100||Math.abs(odds)>1000000:odds<=0||odds>=1))invalid(price,units==='american_odds'?'Use odds of +100 or higher, or −100 or lower.':'Use a contract price greater than 0 and less than 1.');
  if(form.elements['actual-fees-'+i].checked)for(const key of ['entry_fee','win_fee','loss_fee']){const input=form.elements[key+'-'+i];if(input.value===''||!Number.isFinite(Number(input.value))||Number(input.value)<0)invalid(input,'Enter a nonnegative fee; use 0 only when known.');}
 });
 if(first){first.focus();$('edit-status').textContent='Check the highlighted fields.';return false;}return true;
}
$('edit-form').noValidate=true;
$('edit-form').onsubmit=async event=>{
  event.preventDefault();if(!editing||editorBusy)return;$('edit-status').textContent='';
  if(!validateFields())return;
  let payload;try{payload={revision:editing.revision,decision:$('edit-form').elements.decision.value,notes:$('edit-form').elements.notes.value,trade:tradeFromForm()};}catch(e){$('edit-status').textContent=e.message;return;}
  const fingerprint=JSON.stringify(payload);if(saveAttempt?.fingerprint!==fingerprint)saveAttempt={fingerprint,id:crypto.randomUUID()};payload.request_id=saveAttempt.id;
  const target=editing;previewSequence++;clearTimeout(previewTimer);lockEditor(true);$('edit-status').textContent='Saving changes…';
  try{
    const response=await fetch('/api/bet-journal/'+encodeURIComponent(target.id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),data=await response.json();
    if(response.status===409)throw Error('This record changed in another session. Close and Refresh to load that version before saving. Your edits are still shown here.');
    if(!response.ok)throw Error(data.message||data.error||'The change could not be saved.');
    if(editing===target){draftGuard.saved();$('editor').close();}$('count').textContent='Bet saved.';await load();
  }catch(e){if(editing===target)$('edit-status').textContent=(e.message||'Changes could not be saved.')+' Your entries are preserved; retry.';}finally{if(editing===target)lockEditor(false);}
};

$('delete').onclick=()=>{$('delete-confirmation').hidden=false;$('confirm-delete').focus();};
$('keep').onclick=()=>{$('delete-confirmation').hidden=true;$('delete').focus();};
$('confirm-delete').onclick=async()=>{
  if(!editing)return;const target=editing;previewSequence++;clearTimeout(previewTimer);lockEditor(true);$('edit-status').textContent='Deleting…';
  try{
    const response=await fetch('/api/bet-journal/'+encodeURIComponent(target.id),{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:target.revision})}),data=await response.json();
    if(response.status===409)throw Error('This record changed in another session. Close and Refresh before deleting it.');
    if(!response.ok)throw Error(data.error||'The bet could not be deleted.');
    if(editing===target){returnFocus=$('results');$('editor').close();}
    if(packet?.entries?.length===1)offset=Math.max(0,offset-100);sequence++;await load();
  }catch(e){if(editing===target)$('edit-status').textContent=e.message||'Could not delete. Your record is preserved.';}
  finally{if(editing===target)lockEditor(false);}
};
for(const id of ['editor-close','cancel'])bindDialogClose($(id),$('editor'),()=>draftGuard.requestClose()); $('editor').addEventListener('close',()=>{editing=null;previewSequence++;clearTimeout(previewTimer);(returnFocus?.isConnected?returnFocus:$('results')).focus({preventScroll:true});});
$('bets-tab').onclick=()=>{tab='placed';offset=0;sequence++;load();};$('research-tab').onclick=()=>{tab='research';offset=0;sequence++;load();};$('log-tab').onclick=()=>{tab='log';offset=0;sequence++;load();};$('refresh').onclick=()=>{sequence++;load();};$('previous').onclick=()=>{offset=Math.max(0,offset-100);sequence++;load();};$('next').onclick=()=>{offset+=100;sequence++;load();};$('filters').onsubmit=e=>e.preventDefault();let debounce;$('filters').oninput=e=>{offset=0;sequence++;clearTimeout(debounce);debounce=setTimeout(load,e.target.name==='search'?180:0);};
load();setInterval(()=>{if(!$('editor').open&&!document.querySelector('.journal-details[open]')&&!document.hidden)load();},15000);
