import {bookName} from './pregame-labels.js';
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
let packet=null,tab=initial.get('view')==='log'?'log':'bets',editing=null,returnFocus=null,loading=false,initialOpened=false,offset=0,sequence=0,queued=false;

function pick(row){
  const s=row.selection||{},line=ratio(s.signed_line),team=row.selection_label||(s.participant||'').split(':').pop();
  if(row.family==='total')return (s.predicate==='over'||row.side==='over'?'Over ':'Under ')+(line??'');
  return (team||row.game||'Selection')+(row.family==='spread'?' '+(line>0?'+':'')+(line??''):' to win');
}
function observedPrice(row){
  const original=row.posted||{};
  if(original.units==='american_odds')return String(original.value);
  const d=ratio(row.raw?.posted_decimal),p=d?1/d:null;
  if(p!==null&&['kalshi','polymarket_us'].includes(row.venue))return (p*100).toFixed(2).replace(/\.00$/,'')+'¢';
  return row.display?.posted_odds||[original.value,original.units?.replaceAll('_',' ')].filter(Boolean).join(' ')||'Unavailable';
}
function tradePrice(trade){if(!trade)return 'Not entered';if(trade.units==='probability'){const p=ratio(trade.price);return p===null?'Unavailable':(p*100).toFixed(2).replace(/\.00$/,'')+'¢';}const n=ratio(trade.price);return n===null?'Not entered':(n>0?'+':'')+String(trade.price).replace(/^\+/, '');}
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
  const count=s.counts||{},settledCount=s.settled??settled.length,totalRecords=Object.values(count).reduce((a,b)=>a+Number(b),0);
  const stats=[['Placed bets',count.placed??placed.length],['Settled bets',settledCount],['Reported net profit',money(settledCount?s.realized_profit_usd??profit:null)],['Journal records',totalRecords||packet.total||0]];
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
  const grid=node('div',undefined,'journal-prices');
  legs(entry).forEach((row,i)=>{
    const data=m.legs?.[i]||{},trade=entry.trade?.legs?.[i],quote=data.close_quote||data.latest_quote;
    const leg=node('section',undefined,'journal-price-leg');leg.append(node('h3',bookName(row.venue)+' · '+pick(row)));
    const values=node('div',undefined,'journal-price-grid');
    for(const [label,value,time]of [['Observed',observedPrice(row),row.times?.source_at||row.times?.received_at],['Actual',tradePrice(trade),entry.trade?.placed_at],[data.close_quote?'Last pregame close':'Latest captured',quote?observedPrice(quote):'Unavailable',quote?.times?.source_at||quote?.times?.received_at]]){
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
  const snapshot=entry.snapshot,m=entry.metrics||{},estimatedClose=(m.legs||[]).some(l=>l.close_reference_basis==='alternate_line_interpolation'),article=node('article',undefined,'journal-entry');article.dataset.entryId=entry.id;
  const head=node('header',undefined,'journal-entry-head'),subject=node('div'),caption=node('p',(entry.kind==='arb'?'ARBITRAGE':'EV BET')+' · '+(snapshot.league||'')+' · '+when(snapshot.kickoff),'journal-caption');caption.append(node('span',entry.decision,'journal-decision '+entry.decision));
  const title=node('h2',entry.kind==='arb'?snapshot.game:pick(snapshot));subject.append(caption,title,node('p',snapshot.game,'journal-observed'));
  const edit=node('button',entry.decision==='observed'?'Record decision':'Edit trade');edit.type='button';edit.onclick=()=>openEditor(entry,edit);head.append(subject,edit);
  article.append(head,node('p','Observed '+when(entry.created_at)+' · '+legs(entry).map(row=>bookName(row.venue)+' '+observedPrice(row)).join(' / '),'journal-observed'));
  const figures=node('div',undefined,'journal-figures'),actual=m.basis==='reported_trade';
  if(entry.kind==='ev')figures.append(metric('Observed EV',percent(m.observed_ev??snapshot.raw?.net_ev)),metric(actual?'Actual entry EV':'Modeled entry EV',percent(m.entry_ev),m.entry_ev_usd!==null&&m.entry_ev_usd!==undefined?money(m.entry_ev_usd)+' expected profit':undefined),metric((m.legs||[]).some(l=>l.close_reference_basis==='harder_line_probability_lower_bound')?'Entry EV at close (bound)':estimatedClose?'Entry EV at close (estimated)':'Entry EV at close',percent(m.close_ev),m.close_ev_usd!==null&&m.close_ev_usd!==undefined?money(m.close_ev_usd)+' at closing fair probability':m.close_state==='tracking'?'Tracking until kickoff':(m.legs||[]).some(l=>l.closing_fair)?'Entry cashflows unavailable':'No comparable closing reference'));
  else figures.append(metric('Observed paired return',percent(m.observed_arb_return??snapshot.return_rate)),metric(actual?'Actual minimum profit':'Modeled minimum profit',money(m.entry_min_profit_usd),percent(m.entry_arb_return)+' paired return'),metric('Closing quote model return',percent(m.close_arb_return),m.close_min_profit_usd!==null&&m.close_min_profit_usd!==undefined?money(m.close_min_profit_usd)+' modeled profit · '+money(m.close_cost_usd)+' basis':m.close_state==='tracking'?'Tracking until kickoff':'Closing legs unavailable'));
  figures.append(metric('Reported net result',money(m.realized_profit_usd),m.realized_roi!==null&&m.realized_roi!==undefined?percent(m.realized_roi)+' return':'Awaiting actual settlement'));
  article.append(figures);if(['closed','missing'].includes(m.close_state))article.append(closingPrices(entry));
  if(entry.kind==='arb')article.append(node('p','Entry EV '+percent(m.entry_ev)+' · Entry EV at close '+percent(m.close_ev)+(m.entry_ev===null?' · Comparable fair references are needed to measure expected value.':''),'journal-observed'));
  if(entry.kind==='ev'&&m.close_market_ev!==null&&m.close_market_ev!==undefined)article.append(node('p','Closing offer EV'+(estimatedClose?' (estimated)':'')+' '+percent(m.close_market_ev)+' · Entry EV at close keeps your original trade cashflows fixed.','journal-observed'));
  if(entry.trade?.legs?.some(leg=>leg.fee_basis==='unavailable'))article.append(node('p','Fee schedule unavailable for this saved quote; after-fee metrics are unavailable.','journal-observed'));article.append(priceDetails(entry));if(entry.notes)article.append(node('p',entry.notes,'journal-notes'));return article;
}
function render(){
  if(!packet)return;drawSummary();$('bets-tab').setAttribute('aria-pressed',String(tab==='bets'));$('log-tab').setAttribute('aria-pressed',String(tab==='log'));
  const entries=packet.entries||[],total=packet.total??entries.length;
  $('count').textContent=total+' '+(total===1?'record':'records');$('results').replaceChildren(...entries.map(card));
  $('previous').disabled=offset===0;$('next').disabled=offset+entries.length>=total;$('page').textContent=total?`${offset+1}–${Math.min(offset+entries.length,total)} of ${total}`:'0';
  if(!entries.length){const empty=node('div',undefined,'journal-empty');empty.append(node('h2',tab==='bets'?'Your next bet starts with a saved quote.':'No logged opportunities match this view.'),node('p',tab==='bets'?'Save an EV bet or arbitrage comparison, then enter the odds, stake and fees you actually got. Automatically observed opportunities are in the Opportunity log.':'Automatic logging begins from current eligible opportunities. You can also save any comparison from the board.'));const link=node('a','Browse opportunities →');link.href='/';empty.append(link);$('results').append(empty);}
}
function query(){const q=new URLSearchParams({view:tab,limit:'100',offset:String(offset)});for(const [k,v]of new FormData($('filters')))if(v)q.set(k,v);return q;}
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
  fieldset.append(node('p','Odds '+tradePrice(values)+' · Fees calculated from the saved book schedule.'));
  fieldset.append(field('Stake placed ($)','stake-'+i,values.stake,{required:true}));
  const advanced=node('details',undefined,'journal-options');advanced.append(node('summary','Change odds'));
  const price=field('Actual price','price-'+i,values.price,{type:'text'}),input=price.querySelector('input');input.dataset.originalValue=values.price;
  const unitWrap=node('label','Price format','journal-field'),unit=node('select');unit.name='units-'+i;unit.append(new Option('American odds','american_odds'),new Option('Contract price (0–1)','probability'));unit.value=values.units;unit.dataset.originalValue=values.units;unitWrap.append(unit);
  const grid=node('div',undefined,'journal-form-grid');grid.append(price,unitWrap);advanced.append(grid);fieldset.append(advanced);fieldset.querySelector('[name="stake-'+i+'"]').min='.01';return fieldset;
}
async function openEditor(entry,trigger){
  editing=structuredClone(entry);returnFocus=trigger||document.activeElement;const form=$('edit-form'),snapshot=entry.snapshot;
  $('editor-title').textContent=entry.kind==='arb'?snapshot.game:pick(snapshot);$('entry-context').replaceChildren(node('p',snapshot.game+' · '+when(snapshot.kickoff),'journal-observed-detail'),node('p',entry.trade?'Your recorded stakes and odds are shown.':entry.kind==='arb'?'Default: $200 total stake, split across both legs. Fees are calculated separately.':'Default: win $100 at negative odds; stake $100 at positive odds. Before fees.','journal-observed-detail'));
  form.elements.decision.value=['saved','observed'].includes(entry.decision)?'placed':entry.decision;form.elements.notes.value=entry.notes||'';form.elements.placed_at.value=localInput(entry.trade?.placed_at);form.elements.settled_at.value=localInput(entry.trade?.result?.settled_at);form.elements.result_notes.value=entry.trade?.result?.notes||'';
  const defaults=suggestedTrades(entry);$('trade-legs').replaceChildren(...legs(entry).map((row,i)=>legEditor(row,i,entry.trade?.legs?.[i]||defaults[i])));
  $('result-legs').replaceChildren(...legs(entry).map((row,i)=>field('Leg '+(i+1)+' · '+bookName(row.venue)+' · net returned cash ($)','receipt-'+i,entry.trade?.result?.receipts_usd?.[i]??'',{help:'After all settlement charges; includes any returned stake'})));
  $('more-options').open=false;$('settlement').open=Boolean(entry.trade?.result);$('delete-confirmation').hidden=true;$('delete').disabled=false;$('confirm-delete').disabled=false;$('edit-status').textContent='';$('audit-data').textContent=JSON.stringify({original_snapshot:entry.snapshot},null,2);$('audit').open=false;$('save').disabled=false;
  if(!$('editor').open)$('editor').showModal();
  try{const response=await fetch('/api/bet-journal/'+encodeURIComponent(entry.id),{cache:'no-store'});if(!response.ok)return;const data=await response.json();if(editing?.id===entry.id)$('audit-data').textContent=JSON.stringify({original_snapshot:entry.snapshot,history:data.history,quote_observations:data.quotes},null,2);}catch(e){/* Editing remains available with the loaded snapshot. */}
}
function tradeFromForm(){
  const form=$('edit-form'),values=new FormData(form),actual=legs(editing).map((row,i)=>{
    const stake=values.get('stake-'+i);if(!stake||Number(stake)<=0)throw Error('Enter the stake placed for each leg.');
    const leg={quote_id:row.id,stake},price=form.elements['price-'+i],units=form.elements['units-'+i];
    if(editing.trade?.legs?.[i]||price.value!==price.dataset.originalValue||units.value!==units.dataset.originalValue){leg.price=price.value;leg.units=units.value;}
    return leg;
  });
  const trade={automatic:true,legs:actual,placed_at:iso(values.get('placed_at'))};
  const receipts=legs(editing).map((_,i)=>values.get('receipt-'+i)||null);
  if(receipts.some(v=>v!==null)){
    if(receipts.some(v=>v===null))throw Error('Enter returned cash for every leg to record a complete result.');
    trade.result={receipts_usd:receipts,settled_at:iso(values.get('settled_at')),notes:values.get('result_notes')||''};
  }
  return trade;
}
$('edit-form').onsubmit=async event=>{
  event.preventDefault();if(!editing)return;$('edit-status').textContent='';
  let payload;try{payload={revision:editing.revision,decision:$('edit-form').elements.decision.value,notes:$('edit-form').elements.notes.value,trade:tradeFromForm()};}catch(e){$('edit-status').textContent=e.message;return;}
  $('save').disabled=true;$('edit-status').textContent='Saving changes…';
  try{
    const response=await fetch('/api/bet-journal/'+encodeURIComponent(editing.id),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),data=await response.json();
    if(response.status===409)throw Error('This record changed in another session. Close and Refresh to load that version before saving. Your edits are still shown here.');
    if(!response.ok)throw Error(data.message||data.error||'The change could not be saved.');
    $('editor').close();await load();
  }catch(e){$('edit-status').textContent=e.message||'Changes could not be saved. Your entries are preserved; retry.';}finally{$('save').disabled=false;}
};

$('delete').onclick=()=>{$('delete-confirmation').hidden=false;$('confirm-delete').focus();};
$('keep').onclick=()=>{$('delete-confirmation').hidden=true;$('delete').focus();};
$('confirm-delete').onclick=async()=>{
  if(!editing)return;const target=editing;$('confirm-delete').disabled=true;$('save').disabled=true;$('delete').disabled=true;$('edit-status').textContent='Deleting…';
  try{
    const response=await fetch('/api/bet-journal/'+encodeURIComponent(target.id),{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:target.revision})}),data=await response.json();
    if(response.status===409)throw Error('This record changed in another session. Close and Refresh before deleting it.');
    if(!response.ok)throw Error(data.error||'The bet could not be deleted.');
    if(editing?.id===target.id)$('editor').close();if(packet?.entries?.length===1)offset=Math.max(0,offset-100);sequence++;await load();
  }catch(e){$('edit-status').textContent=e.message||'Could not delete. Your record is preserved.';}
  finally{$('confirm-delete').disabled=false;$('save').disabled=false;$('delete').disabled=false;}
};
for(const id of ['editor-close','cancel'])$(id).onclick=()=>$('editor').close();$('editor').addEventListener('close',()=>{editing=null;(returnFocus?.isConnected?returnFocus:$('results')).focus({preventScroll:true});});
$('bets-tab').onclick=()=>{tab='bets';offset=0;sequence++;load();};$('log-tab').onclick=()=>{tab='log';offset=0;sequence++;load();};$('refresh').onclick=()=>{sequence++;load();};$('previous').onclick=()=>{offset=Math.max(0,offset-100);sequence++;load();};$('next').onclick=()=>{offset+=100;sequence++;load();};$('filters').onsubmit=e=>e.preventDefault();let debounce;$('filters').oninput=e=>{offset=0;sequence++;clearTimeout(debounce);debounce=setTimeout(load,e.target.name==='search'?180:0);};
load();setInterval(()=>{if(!$('editor').open&&!document.querySelector('.journal-details[open]')&&!document.hidden)load();},15000);
