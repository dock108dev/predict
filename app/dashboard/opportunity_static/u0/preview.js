
function renderPreviewCalculations(calculation,q,selection){
 const gap=rawGap(q,selection.comparisonQuotes);calculation('Raw price difference',gap??'Unavailable',gap!==null?'Lowest other eligible quote minus selected price, in cents. Gross only.':'No other eligible quote for this exact selection.');
 calculation('Arbitrage return','Unavailable',q.calculations.arbitrage.reason);calculation('Supported EV','Unavailable',q.calculations.ev.reason);
 const profit=q.display.what_if?.gross_profit_per_dollar_payout;
 if(profit!==undefined){const formatted=Number(profit).toFixed(4).replace(/0+$/,'').replace(/\.$/,'');calculation('Manual What-if',(Number(profit)<0?'-':Number(profit)>0?'+':'')+'$'+formatted.replace('-',''),'Synthetic scenario only: 50% win chance, $1 normal-win payout, assumed zero costs, one payout unit. '+(Number(profit)===0?'Zero gross profit under these assumptions.':Number(profit)<0?'Negative gross profit under these assumptions.':'Positive gross profit under these assumptions.')+' Not a model-supported EV.');}
 else calculation('Manual What-if','Unavailable','Quote units or normal-win payout basis are unsupported.');
}
import {el,venues,periods,renderBoard,renderDetails,fillPrice,quoteText,rawGap} from './board.js';
const $=id=>document.getElementById(id);let base,payload,view,selection=null,updates=0,scenarioRevision=0;
const filters=()=>Object.fromEntries(['league','market','period','venue','search'].map(k=>[k,$(k).value]));
function announce(text){$('announcement').textContent=text;}
function applicablePeriods(){const selected=$('period').value;const available=new Set(['full_game']);for(const e of payload.events.filter(e=>!$('league').value||e.league===$('league').value))for(const g of e.groups)if(!$('market').value||g.market===$('market').value)available.add(g.period);$('period').replaceChildren(...[...available].map(k=>{const o=el('option',periods[k]);o.value=k;return o;}));$('period').value=available.has(selected)?selected:'full_game';}
function currentQuote(id){for(const e of payload.events)for(const g of e.groups)for(const o of g.outcomes)for(const q of Object.values(o.quotes))if(q?.id===id)return {event:e,group:g,outcome:o,quote:q,comparisonQuotes:o.quotes};return null;}
function empty(title,text){$('board').replaceChildren();const n=el('div',undefined,'empty');n.append(el('h2',title),el('p',text));$('board').append(n);}
function draw(){$('fixture-clock').textContent='Synthetic clock: '+new Date(payload.clock_at).toLocaleString('en-US',{timeZone:'America/New_York'})+' ET';view=renderBoard($('board'),payload,filters(),select,selection?.quote.id);$('count').textContent=view.events.length+' games · '+view.rows+' selections';const state=$('scenario').value;
if(state==='connecting')empty('Connecting to prices','Available sources will appear here as they connect.');else if(state==='no-events')empty('No events available','There are no listed games in the current state. New listings will appear automatically.');else if(!view.events.length)empty('No games match these filters','Try another league, period or team name. Clear filters to return to the board.');else if(state==='no-comparable')$('count').textContent+=' · Only one venue available; no comparable price';
$('flow').textContent=state==='connecting'?'Connecting · simulated':state==='no-events'?'No listed events · simulated':state==='partial'?'Partial venue coverage · simulated':state==='no-comparable'?'One venue only · simulated':state==='error'?'Kalshi unavailable · other sources available':state==='budget'?'Aggregate updates delayed · simulated':state==='stale'?'Quotes stale · simulated':'Synthetic updates ready';checkSelection();}
function select(value,b){selection={...structuredClone(value),expired:false,expiresAt:performance.now()+300000,runtime:payload.runtime_id};draw();renderDetails($('details'),selection,closeDetails,adoptLatest,{renderPreviewCalculations}).focus();checkSelection();if(matchMedia('(max-width:800px)').matches){$('details').setAttribute('role','dialog');$('details').setAttribute('aria-modal','true');}else{$('details').removeAttribute('role');$('details').removeAttribute('aria-modal');}announce('Selected '+value.outcome.label+', '+venues[value.quote.venue]+', revision '+value.quote.revision);}
function closeDetails(){const id=selection?.quote.id;selection=null;$('details').classList.remove('expired');$('details').removeAttribute('role');$('details').removeAttribute('aria-modal');const p=el('div',undefined,'detail-placeholder');p.append(el('h2','A closer look'),el('p','Select any price to inspect its original quote, rules and supported calculations.'));$('details').replaceChildren(p);draw();(view.buttons.get(id)?.button||$('search')).focus();}
function adoptLatest(){const latest=currentQuote(selection.quote.id);if(!latest||latest.quote.state==='error'||latest.quote.state==='unavailable'){announce('Latest quote unavailable. Select another venue.');return;}select(latest,view.buttons.get(latest.quote.id)?.button);}
function checkSelection(){if(!selection)return;if(performance.now()>=selection.expiresAt||selection.runtime!==payload.runtime_id)selection.expired=true;const n=$('selection-notice');if(!n)return;const latest=currentQuote(selection.quote.id);let text='';if(selection.expired){text='Selection expired'+(selection.runtime!==payload.runtime_id?' after restart':'')+'. Reselect a current price to continue. Previous quote is inspection only.';$('details').classList.add('expired');}else if(latest?.quote.revision>selection.quote.revision)text='Newer price available: '+quoteText(latest.quote)+'. Your review still holds revision '+selection.quote.revision+'.';else if(!view.buttons.has(selection.quote.id))text='This selected price is outside the current filters. Your review is still held.';
if(text){if(n.dataset.message!==text){n.dataset.message=text;n.replaceChildren(el('div',text));if(latest&&latest.quote.state!=='error'&&latest.quote.state!=='unavailable'){const b=el('button',selection.expired?'Reselect latest price':'Review newer price','secondary');b.id='adopt-latest';b.addEventListener('click',adoptLatest);n.append(b);}announce(text);}n.hidden=false;}else{n.hidden=true;n.dataset.message='';}}
function applyScenario(){payload=structuredClone(base);updates=0;const s=$('scenario').value;payload.runtime_id='syn:scenario-'+(++scenarioRevision);if(s==='stale')payload.clock_at=new Date(new Date(payload.clock_at).getTime()+18000000).toISOString();if(s==='no-events'||s==='connecting')payload.events=[];for(const e of payload.events)for(const g of e.groups)for(const o of g.outcomes)for(const [v,q]of Object.entries(o.quotes)){
if((s==='partial'&&v==='prophetx')||(s==='no-comparable'&&v!=='kalshi'))q.state='unavailable';if(s==='error'&&v==='kalshi')q.state='error';if(s==='budget'&&['novig','prophetx'].includes(v)){q.state='budget_delayed';q.comparison.eligible=false;}if(s==='stale'){q.stale=true;q.age_seconds+=18000;q.comparison.eligible=false;}if(s==='unknown-time'&&v==='polymarket_us'){q.times.source_at=null;q.comparison.eligible=false;}}
applicablePeriods();draw();announce('Preview state '+s);}
$('filters').addEventListener('submit',e=>e.preventDefault());for(const key of ['league','market','period','venue','search'])$(key).addEventListener(key==='search'?'input':'change',()=>{if(key==='league'||key==='market')applicablePeriods();draw();});$('filters').addEventListener('reset',()=>setTimeout(()=>{applicablePeriods();draw();},0));$('scenario').addEventListener('change',applyScenario);
$('update').addEventListener('click',async()=>{
  if($('scenario').value!=='populated'){announce('Choose Populated to advance a native fixture price.');return;}
  if(updates){announce('Native update already applied. Choose a board state to reset the fixture.');return;}
  updates++;
  const requestedRuntime=payload.runtime_id;
  try{
    const response=await fetch('/preview/u0/state?revision=2');
    if(!response.ok)throw Error('Preview update unavailable');
    const next=await response.json();
    if(payload.runtime_id!==requestedRuntime)return;
    for(const e of payload.events)for(const g of e.groups)for(const o of g.outcomes){
      for(const q of Object.values(o.quotes)){
        if(q.venue!=='kalshi'||q.state!=='available')continue;
        let replacement;
        for(const ne of next.events)for(const ng of ne.groups)for(const no of ng.outcomes)if(no.id===o.id)replacement=no.quotes.kalshi;
        if(replacement)o.quotes.kalshi=replacement;
      }
    }
    payload.state_revision=next.state_revision;
    // Patch in place: no reordered rows, recreated buttons, focus or scroll loss.
    for(const ref of view.buttons.values()){
      const current=currentQuote(ref.q.id);if(!current)continue;
      ref.q=current.quote;
      const visible=Object.fromEntries(Object.entries(current.outcome.quotes).filter(([v])=>!$('venue').value||v===$('venue').value));
      fillPrice(ref.button,current.quote,visible);
    }
    checkSelection();announce('Native fixture updated. Aggregate source ages unchanged.');
  }catch{
    if(payload.runtime_id!==requestedRuntime)return;
    updates=0;announce('Preview update unavailable. The previous prices remain visible.');
  }
});
$('expire').addEventListener('click',()=>{if(selection){selection.expired=true;checkSelection();}else announce('Select a price first.');});$('restart').addEventListener('click',()=>{payload.runtime_id='syn:runtime-'+Date.now();checkSelection();announce('Runtime restarted. Previous selection expired.');});
document.addEventListener('keydown',e=>{if(!selection)return;if(e.key==='Escape'){e.preventDefault();closeDetails();}if(e.key==='Tab'&&matchMedia('(max-width:800px)').matches){const nodes=[...$('details').querySelectorAll('button,summary,input,a')].filter(n=>!n.closest('[hidden]'));if(e.shiftKey&&document.activeElement===nodes[0]){e.preventDefault();nodes.at(-1).focus();}else if(!e.shiftKey&&document.activeElement===nodes.at(-1)){e.preventDefault();nodes[0].focus();}}});
setInterval(checkSelection,1000);
try{const response=await fetch('/preview/u0/state');if(!response.ok)throw Error('Preview unavailable');base=await response.json();payload=structuredClone(base);applicablePeriods();draw();}catch{empty('Preview unavailable','Restart the local design preview and reopen this page.');$('flow').textContent='Preview unavailable';}
