import {evidenceReason} from './desk-reasons.js';

const {el, num, fmt, name, odd} = window.PredictUI;
const basisLabels = {sportsbooks:'Indicative before-fee estimate', reviewed:'Verified after-fee EV',
  conservative:'Conservative after-fee scenario', before:'Before-fee scenario'};
export const books = ['fanduel', 'draftkings', 'betmgm', 'caesars'];
export const cash = value => value == null ? 'Unavailable' : new Intl.NumberFormat('en-US', {
  style:'currency', currency:'USD'
}).format(num(value));
export const percent = value => value == null ? 'Unavailable' : `${num(value) > 0 ? '+' : ''}${fmt(value)}%`;
export const tone = value => num(value) > 0 ? 'positive' : num(value) < 0 ? 'negative' : '';
export const basisName = basis => basisLabels[basis];
export const venueLabel = offer => name(offer.venue);

export function quoteReason(offer) {
  if (!offer.current) return quoteFreshness(offer);
  if (offer.value != null) return null;
  const reason = String(offer.reason || '').split(', ')[0];
  return evidenceReason(reason, 'No qualified same-line sportsbook pair.').replace(/\.$/, '');
}

export function selectedReference(offer, basis) {
  if (basis === 'sportsbooks' && offer?.sportsbook) {
    return {book:offer.sportsbook.book, prices:offer.sportsbook.prices, candidates:offer.sportsbook.candidates};
  }
  const ref = offer?.reference_current && offer.reference_calculation;
  const book = ref && ref.contributors?.find(item => item.venue === ref.venue || item.venue === ref.bookmaker);
  if (book) return {book:book.venue, prices:book.inputs, candidates:ref.candidates};
  const [selected] = Object.entries(offer?.fair_reference?.selected_prices || {});
  if (selected) return {book:selected[0], prices:[{price_american:selected[1]}]};
  return null;
}

export function sportsbookOdds(price) {
  if (price?.american && price?.decimal) return price;
  const american = price?.price_american ?? price?.american ?? price;
  const amount = num(american);
  if (!Number.isFinite(amount) || !amount) return null;
  return {american:amount > 0 ? `+${amount}` : String(amount),
    decimal:amount > 0 ? 1 + amount / 100 : 1 + 100 / -amount};
}

export function quoteAge(source, checkedAt = Date.now()) {
  const age = elapsedAge(source, checkedAt);
  return age ? `Quote updated ${age}` : 'Quote time unknown';
}

function elapsedAge(source, checkedAt = Date.now()) {
  const elapsed = Math.floor((new Date(checkedAt) - new Date(source)) / 1000);
  if (!source || !Number.isFinite(elapsed) || elapsed < 0) return null;
  if (elapsed < 60) return `${elapsed}s ago`;
  if (elapsed < 3600) return `${Math.floor(elapsed / 60)}m ago`;
  return `${Math.floor(elapsed / 3600)}h ago`;
}

export function quoteFreshness(offer, mode, inspection = false) {
  if (offer.posted_price && !mode) return 'Latest posted pregame price';
  if (offer.current) return mode ? 'Current at capture' : inspection ? 'Current at inspection' : 'Current';
  const codes = [...(offer.current_reasons || []), offer.reason];
  const labels = {
    sgo_charge_unresolved:'source on hold', ambiguous_dispatch_unresolved:'source on hold',
    source_expired:'quote expired', 'Price expired':'quote expired',
    data_runtime_unhealthy:'price feed unavailable',
    updates_stopped:'updates inactive', sgo_paused_or_stopped:'updates paused',
    input_replaced_or_removed:'quote replaced or removed', source_unknown:'source time unverified'
  };
  const status = Object.entries(labels).find(([code]) => codes.includes(code))?.[1] || 'current quote unavailable';
  return `${mode ? 'Last known at capture' : 'Last known'} · ${status}`;
}

function sportsbookCell(group, book, reference, checkedAt, mode, inspection = false) {
  const cell = el('div', null, 'sportsbook-price');
  const selected = reference?.book === book && reference.prices?.[0];
  const usesReference = value => selected && value.current !== false
    && value.price_american === selected.price_american && (!selected.source_at || value.source_at === selected.source_at);
  let values = group.sportsbook_quotes?.[book] || (selected ? [{...selected, current:true}] : []);
  if (selected && !values.some(usesReference)) {
    values = [{...selected, current:true}, ...values];
  }
  for (const value of values) {
    const item = el('div');
    item.append(odd(sportsbookOdds(value)));
    if (value.source_at) item.title = value.source_at;
    const isReference = usesReference(value);
    if (isReference) item.classList.add('matrix-reference');
    const label = [mode ? [value.current === false ? 'Last known at capture' : 'At capture',
      value.source_at && quoteAge(value.source_at, checkedAt)].filter(Boolean).join(' · ') :
      priceStatus(value.current, value.source_at, checkedAt, inspection),
      isReference && 'EV reference'].filter(Boolean).join(' · ');
    if (label) {
      const freshness = el('small', label);
      if (inspection && !mode && value.current === true) freshness.dataset.inspectionBook = '1';
      item.append(freshness);
    }
    cell.append(item);
  }
  if (!values.length) noQuote(cell, name(book), group.retained_sportsbooks?.includes(book));
  return cell;
}

export function noQuote(cell, venue, retained = false) {
  const missing = el('span', retained ? 'Saved quote' : '—', 'desk-meta missing-quote');
  const detail = retained ? `Saved quote from ${venue}. Turn on Last-known prices to see it.`
    : `No quote shown from ${venue} for this exact outcome`;
  missing.setAttribute('aria-label', detail);
  missing.title = detail;
  cell.append(missing);
}

export function priceStatus(current, at, checkedAt, inspection = false) {
  const status = current === true ? (inspection ? 'Current at inspection' : 'Current')
    : current === false ? 'Last known' : 'Freshness unverified';
  return at ? `${status} · ${quoteAge(at, checkedAt)}` : status;
}

export function settlementLabel(group) {
  return ({matched:'Venue settlement rules match', different:'Venue settlement rules differ',
    unverified:'Venue settlement match unverified'})[group.settlement_match];
}

export function winPayout(offer) {
  const cost = num(offer.cost_per_normal_claim);
  const multiplier = cost > 0 ? 1 / cost : num(offer.odds?.decimal);
  return multiplier > 1 && Number.isFinite(multiplier)
    ? `A winning $10 stake returns ${cash(multiplier * 10)} total, including ${cash((multiplier - 1) * 10)} profit before fees.` : null;
}

export function sportsbookQuotes(group, reference, checkedAt, mode, inspection = false) {
  const section = el('div', null, 'sportsbook-comparison');
  const listed = inspection ? books.filter(book => group.sportsbook_quotes?.[book]?.length || reference?.book === book) : books;
  const prices = el('div', null, 'sportsbook-prices');
  for (const book of listed) {
    const cell = el('div');
    cell.append(el('strong', name(book)), sportsbookCell(group, book, reference, checkedAt, mode, inspection));
    prices.append(cell);
  }
  if (listed.length) section.append(...(inspection ? [] : [el('small', 'Same-line sportsbook quotes')]), prices);
  if (group.sportsbook_source_reason) {
    section.append(el('small', evidenceReason(group.sportsbook_source_reason)));
  }
  return section;
}
