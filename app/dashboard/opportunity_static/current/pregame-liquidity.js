import {ratio} from './pregame-prices.js';

const node=(tag,text,cls)=>{
  const element=document.createElement(tag);
  if(text!==undefined)element.textContent=text;
  if(cls)element.className=cls;
  return element;
};
const shown=(value,format)=>value!=null&&Number.isFinite(ratio(value))?format(ratio(value)):null;
const money=value=>shown(value,n=>n.toLocaleString('en-US',{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:2}));
const percent=value=>shown(value,n=>(n>0?'+':'')+(100*n).toFixed(2)+'%');
const price=value=>shown(value,n=>(100*n).toFixed(2)+'¢');
const labels={
  full_size:'Full size', partial_size:'Partial size', confirmed_empty:'No displayed size',
  empty:'No displayed size', price_above_limit:'Price above limit', above_limit:'Price above limit',
  below_ev_floor:'Below EV floor',
  unknown:'Depth unknown'
};
const reasons={
  book_unobserved:'No matching book has been collected.',
  stale_book:'The last matching book is stale.',
  reference_stale:'The fair-price reference is stale.',
  reference_revision_changed:'A new fair-price reference is awaiting a depth calculation.',
  identity_revision_changed:'The contract changed since the book was collected.',
  native_identity_unmatched:'The exact venue contract is unverified.',
  source_paused:'The source is paused.',
  truncated:'The public book retains only the displayed levels.',
  fee_schedule_unverified:'The applicable fee schedule is unverified.',
  fee_cutover_time_unverified:'The venue has not confirmed the fee transition time.',
  fee_rounding_ambiguous:'The available levels do not establish exact per-fill fees.',
  timeout:'The venue response did not arrive in time.',
  unavailable:'The venue book was unavailable.',
  throttled:'The venue throttled the book request.',
};

function statusText(depth){
  const status=labels[depth.status]||labels.unknown;
  const ev=percent(depth.modeled_net_ev);
  const at=money(depth.modeled_stake_usd);
  if(ev&&at)return `${status} · ${depth.status==='unknown'?'Observed size ':''}${ev} at ${at}`;
  return status;
}

export function liquidityBadge(row){
  const depth=row.liquidity;
  if(!depth)return null;
  const section=node('small',statusText(depth),'liquidity-badge');
  section.dataset.depthStatus=depth.status||'unknown';
  const available=money(depth.available_purchase_usd);
  if(available)section.append(node('span',`${depth.availability_is_lower_bound?'At least ':''}${available} available`));
  return section;
}

export function liquidityDetails(row){
  const depth=row.liquidity;
  if(!depth)return null;
  const section=node('section',undefined,'liquidity-details');
  const target=money(depth.intended_stake_usd||depth.requested_stake_usd);
  section.append(node('h3',target?'Liquidity at '+target:'Liquidity'),liquidityBadge(row));
  if(depth.reason)section.append(node('p',reasons[depth.reason]||depth.reason.replaceAll('_',' '),'comparison-context'));
  const rows=node('dl');
  const add=(label,value)=>{
    if(value!==null&&value!==undefined&&value!=='')rows.append(node('dt',label),node('dd',value));
  };
  add('Supported cash budget',money(depth.modeled_stake_usd));
  add('Modeled purchase',money(depth.modeled_purchase_usd));
  add('Modeled average buy price',price(depth.modeled_average_price));
  add('Price limit used',price(depth.limit_price));
  const modeledFee=money(depth.modeled_fee_usd),feeLower=money(depth.fee_lower_bound_usd);
  add('Modeled fee', modeledFee&&depth.fee_is_upper_bound?(feeLower&&feeLower!==modeledFee?
    feeLower+' to '+modeledFee:'Up to '+modeledFee):modeledFee);
  add('Modeled win profit',money(depth.modeled_win_profit_usd));
  add('Modeled net EV',percent(depth.modeled_net_ev));
  add('Book received',clock(depth.book_received_at||depth.book_known_at));
  add('Venue timestamp',clock(depth.book_source_at));
  add('Published',clock(depth.published_at));
  if(rows.childElementCount)section.append(rows);
  if(row.liquidity_evidence){
    const evidence=row.liquidity_evidence, details=node('details');
    const facts=node('dl');
    for(const [label,value] of [['Receipt',depth.receipt_id],['Market',evidence.market_id],['Outcome',evidence.outcome_id],
      ['Opposite outcome',evidence.opposite_outcome_id],['Book sequence',evidence.sequence],
      ['Identity revision',evidence.market_revision||evidence.binding_revision],['Fee schedule',evidence.fee?.schedule_revision||evidence.fee?.version],
      ['Settlement rule',evidence.contract?.settlement?.rule_id]]){
      if(value!==undefined&&value!==null)facts.append(node('dt',label),node('dd',String(value)));
    }
    details.append(node('summary','Public book evidence'),facts);
    if(evidence.levels?.length){
      const levels=node('ol',undefined,'liquidity-levels');
      for(const level of evidence.levels)levels.append(node('li',`${price(level.price)} · ${level.quantity} native units`));
      details.append(levels);
    }
    if(evidence.receipts?.length){
      const source=node('dl');
      for(const proof of evidence.receipts){
        const timing=[clock(proof.requested_at),clock(proof.received_at||proof.observed_at)].filter(Boolean).join(' → ');
        const value=[timing, proof.status&&'HTTP '+proof.status, proof.cache_control, proof.age&&'Age '+proof.age+'s'].filter(Boolean).join(' · ');
        if(value)source.append(node('dt','Venue receipt'),node('dd',value));
      }
      details.append(source);
    }
    section.append(details);
  }
  return section;
}

function clock(value){
  if(!value||!Number.isFinite(Date.parse(value)))return null;
  return new Date(value).toLocaleTimeString('en-US',{timeZone:'America/New_York',
    hour:'numeric',minute:'2-digit',second:'2-digit'})+' ET';
}

export function coverageRows(rows,bookName){
  const table=node('table',undefined,'liquidity-coverage-table');
  const headings=node('tr');
  for(const label of ['Venue','League','Market','Lines','All','Size checked','Full size','EV checked','Stake covered','Gaps']){
    const heading=node('th',label);heading.scope='col';headings.append(heading);
  }
  const head=node('thead');head.append(headings);table.append(head);
  const body=node('tbody');
  for(const row of rows){
    const entry=node('tr');
    const intended=ratio(row.intended_stake_usd),supported=ratio(row.observed_supported_stake_usd);
    const share=intended?(100*supported/intended).toFixed(1)+'%':'—';
    const gaps=Object.entries(row.reasons||{}).map(([reason,n])=>reason.replaceAll('_',' ')+' '+n);
    for(const value of [bookName(row.venue),row.league,row.family,row.main?'Main':'Alternate',
      row.opportunities,row.assessable,row.full_size,row.ev_assessable,share,gaps.join(' · ')||'—'])entry.append(node('td',String(value)));
    body.append(entry);
  }
  table.append(body);
  return table;
}
