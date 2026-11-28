import {bookName} from './pregame-labels.js';
import {feeAssumption} from './pregame-evidence.js';
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
const inactiveBooks = new Set([
  'stale', 'stale_book', 'native_observation_superseded', 'identity_revision_changed',
  'native_identity_changed', 'native_schedule_changed', 'native_game_started',
]);

function dashboardResult(result, now) {
  const depth = result.liquidity;
  const bookUntil = Date.parse(depth?.valid_until || depth?.book_valid_until);
  const referenceUntil = Date.parse(depth?.reference_valid_until);
  const staleBook = bookUntil <= now;
  const staleReference = referenceUntil <= now;
  const inactive = staleBook || inactiveBooks.has(depth?.reason);
  const deadline = Math.min(...[bookUntil, referenceUntil].filter(time => time > now));
  if (inactive) {
    return {deadline: Infinity, inactive, model: {
      ...result,
      preview_offer: null,
      liquidity: {
        status: 'unknown', size_status: 'unknown',
        reason: inactiveBooks.has(depth.reason) ? depth.reason : 'stale_book',
        intended_stake_usd: depth.intended_stake_usd,
        book_received_at: depth.book_received_at,
        book_source_at: depth.book_source_at,
        receipt_id: depth.receipt_id,
        as_of: depth.as_of,
        published_at: depth.published_at,
        valid_until: depth.valid_until || depth.book_valid_until,
      },
    }};
  }
  const model = staleReference ? {
    ...result,
    liquidity: {...depth, modeled_net_ev: null, reason: 'reference_stale', eligible: false, supported_eligible: false,
      status: depth.status === 'below_ev_floor' ? depth.size_status || 'unknown' : depth.status},
  } : result;
  return {deadline, inactive, model};
}

function dashboardFeedback(depth, requestedAmount) {
  const reason = depth?.reason;
  if (reason === 'stale' || reason === 'stale_book') {
    return 'The book has expired. Evaluate amount to check for a fresh book.';
  }
  if (reason === 'native_observation_superseded') {
    return 'The saved book changed. Evaluate amount to check this selection again.';
  }
  if (['identity_revision_changed', 'native_identity_changed', 'native_schedule_changed'].includes(reason)) {
    return 'The market changed. Reopen the current quote to evaluate its amount.';
  }
  if (reason === 'native_game_started') {
    return 'The game has started. The saved book is available as evidence.';
  }
  if (depth?.size_status === 'confirmed_empty' || depth?.status === 'confirmed_empty') {
    return 'The current book showed no available size. Evaluate amount to check again.';
  }
  if (depth?.size_status === 'above_limit' || depth?.status === 'above_limit') {
    return 'The displayed prices exceed the limit. Evaluate amount to check again.';
  }
  const sized = depth?.size_status || depth?.status;
  if (depth?.modeled_stake_usd != null && ['full_size', 'partial_size', 'below_ev_floor'].includes(sized)) {
    const amount = money(requestedAmount || depth.intended_stake_usd);
    const supported = 'The current book models '+money(depth.modeled_stake_usd)+' of '+amount+' requested.';
    if (reason === 'reference_stale') {
      return supported+' The fair reference expired. Evaluate amount to check for a refreshed reference.';
    }
    return supported+(depth.modeled_net_ev == null ? ' Net EV is unavailable.' : '')+' No records saved.';
  }
  return 'Current size is unknown. Evaluate amount to check again.';
}

function archivedCalculation(depth, originalMode) {
  if (depth?.modeled_stake_usd == null) return null;
  const history = node('details', undefined, 'amount-saved-calculation');
  const facts = node('dl', undefined, 'dashboard-facts');
  const netEV = depth.modeled_net_ev == null ? null : (100 * ratio(depth.modeled_net_ev)).toFixed(2)+'%';
  for (const [label, value] of [
    ['Requested cash', money(depth.intended_stake_usd)],
    ['Modeled cash', money(depth.modeled_stake_usd)],
    ['Modeled win profit', depth.modeled_win_profit_usd == null ? null : money(depth.modeled_win_profit_usd)],
    ['Modeled net EV', netEV],
    ['Fee assumption', feeAssumption(depth.fee_mode || originalMode, depth.modeled_fee_usd != null)],
  ]) {
    if (value != null) facts.append(node('dt',label),node('dd',value));
  }
  history.append(node('summary','Earlier size estimate (expired)'),facts);
  return history;
}

// This component has no journal dependency. Recording always uses the inspected quote.
export function amountResearch(kind,snapshot,renderResult,{dataType='all',signal,savedLiquidity,clock}={}){
  const frozen = structuredClone(snapshot);
  const dashboard = kind === 'dashboard';
  const section = node('section', undefined, 'amount-research');
  const heading = node('h3','Explore an amount');
  const intro = node('p','Read-only research · total cash budget, including acquisition fees. No quote or bet is saved.','comparison-context');
  const budgetLabel = dashboard ? 'Cash budget' : 'Illustrative cash budget';
  const form = node('form'), label = node('label',budgetLabel+' ($)'), input = node('input');
  input.type = 'number';
  input.min = '0.01';
  input.max = '1000000';
  input.step = '0.01';
  input.value = String(ratio(kind === 'arb' ? snapshot.basis_usd || '100' :
    snapshot.liquidity?.intended_stake_usd || snapshot.fee?.comparison_basis_usd || '100'));
  input.required = true;
  input.setAttribute('aria-label',budgetLabel);
  label.append(input);
  const presets = node('div',undefined,'amount-presets');
  for (const value of [25,100,500]) {
    const button = node('button','$'+value);
    button.type = 'button';
    button.onclick = () => { input.value = String(value); form.requestSubmit(); };
    presets.append(button);
  }
  const apply = node('button','Evaluate amount');
  apply.type = 'submit';
  const status = node('p',undefined,'comparison-context');
  status.setAttribute('role','status');
  const output = node('div',undefined,'amount-result');
  const overview = kind === 'arb' ? node('div',undefined,'amount-overview') : null;

  let revision = 0, controller, expiryTimer, displayed;
  let result = frozen;
  let lastModeled = savedLiquidity || frozen.liquidity;

  function draw(model, archived = null) {
    const open = dashboard ? new Set([...output.querySelectorAll('details[open]')]
      .map(detail => detail.querySelector('summary')?.textContent)) : null;
    renderResult(output,model);
    if (archived) output.append(archived);
    for (const detail of output.querySelectorAll('details')) {
      if (open?.has(detail.querySelector('summary')?.textContent)) detail.open = true;
    }
    if (overview) {
      const summary = output.querySelector('.arb-summary');
      if (summary) overview.replaceChildren(summary);
    }
  }

  function refreshDashboard({force = false} = {}) {
    clearTimeout(expiryTimer);
    if (signal?.aborted) return;
    const now = clock?.now() ?? Date.now();
    const {deadline, inactive, model} = dashboardResult(result, now);
    const state = model === result ? 'unchanged' : inactive ? 'expired' : 'reference-expired';
    if (force || state !== displayed) {
      draw(model, inactive ? archivedCalculation(lastModeled, frozen.fee_mode) : null);
      displayed = state;
      if (!controller) status.textContent = dashboardFeedback(model.liquidity, section.dataset.evaluatedAmount);
    }
    if (Number.isFinite(deadline) && !document.hidden) {
      expiryTimer = setTimeout(refreshDashboard, Math.min(2147483647, Math.max(0, deadline - now)));
    }
  }

  const checkVisibility = () => {
    if (document.hidden) clearTimeout(expiryTimer);
    else refreshDashboard();
  };
  if (dashboard && !signal?.aborted) {
    clock?.addEventListener('change', refreshDashboard, {signal});
    document.addEventListener('visibilitychange',checkVisibility,{signal});
    window.addEventListener('pageshow',checkVisibility,{signal});
    signal?.addEventListener('abort',() => clearTimeout(expiryTimer),{once: true});
  }
  form.onsubmit = async event => {
    event.preventDefault();
    if (!form.reportValidity() || signal?.aborted) return;
    const token = ++revision;
    controller?.abort();
    controller = new AbortController();
    const requestController = controller, requestedAmount = input.value;
    status.textContent = 'Evaluating modeled cashflows… Previous calculation shown.';
    output.setAttribute('aria-busy','true');
    const timer = setTimeout(() => requestController.abort(),12000);
    const endpoint = dashboard ? '/api/research/dashboard-liquidity' :
      '/api/pregame/research?'+new URLSearchParams({data_type:dataType||'all'});
    const body = dashboard ? {market_id:frozen.market_id,pull_id:frozen.pull_id,offer_id:frozen.id,
      revision:frozen.revision,amount:requestedAmount} : {kind,snapshot:frozen,amount:requestedAmount};
    const requestSignal = signal ? AbortSignal.any([signal,requestController.signal]) : requestController.signal;
    try {
      const response = await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:requestSignal});
      const data = await response.json();
      if (token !== revision || signal?.aborted) return;
      if (!response.ok) throw Error(data.error||'Amount calculation unavailable.');
      section.dataset.evaluatedAmount = requestedAmount;
      if (dashboard) {
        result = {...data.result, liquidity_evidence: data.result.liquidity_evidence || result.liquidity_evidence};
        if (result.liquidity?.modeled_stake_usd != null) lastModeled = result.liquidity;
        controller = null;
        clock?.observe(data.read_at);
        refreshDashboard({force: true});
      } else {
        draw(data.result);
        status.textContent = 'Modeled for up to '+money(requestedAmount)+' total cash. '+
          (data.result.liquidity?'See liquidity and fees at this size.':'Size remains unverified.')+' No records saved.';
      }
    } catch (error) {
      if (token === revision && !signal?.aborted) {
        const message = error.name === 'AbortError' ? 'Amount request timed out. Choose Evaluate amount to retry.' : error.message;
        status.textContent = message+' Previous calculation is preserved.';
      }
    } finally {
      clearTimeout(timer);
      if (token === revision) {
        controller = null;
        output.removeAttribute('aria-busy');
      }
    }
  };
  form.append(label,presets,apply);
  if (overview) section.append(overview,heading,intro,form,status,output);
  else section.append(output,heading,intro,form,status);
  if (dashboard) refreshDashboard({force: true});
  else draw(frozen);
  return section;
}
