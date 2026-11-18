import {evidenceReason} from './desk-reasons.js';

const {el, num, fmt, name, odd, button} = window.PredictUI;
const basisLabels = {sportsbooks:'Indicative before-fee estimate', reviewed:'Verified after-fee EV',
  conservative:'Conservative after-fee scenario', before:'Before-fee scenario',
  after_fees:'Estimated Net EV · $100', sportsbook_after_fees:'Modeled after-fee estimate', public_estimate:'Estimated Net EV · $100'};
export const books = ['fanduel', 'draftkings', 'betmgm', 'caesars'];
export const cash = value => value == null ? 'Unavailable' : new Intl.NumberFormat('en-US', {
  style:'currency', currency:'USD'
}).format(num(value));
export const percent = value => value == null ? 'Unavailable' : `${num(value) > 0 ? '+' : ''}${fmt(value).replace(/^-/, '−')}%`;
export const tone = value => num(value) > 0 ? 'positive' : num(value) < 0 ? 'negative' : '';
export const basisName = basis => basisLabels[basis];
export const venueLabel = offer => name(offer.venue);

export function quoteReason(offer) {
  if (!offer.current) return quoteFreshness(offer);
  if (offer.value != null) return null;
  const reason = String(offer.reason || '').split(', ')[0];
  return evidenceReason(reason, 'No qualified same-line sportsbook pair.').replace(/\.$/, '');
}

export const usesSportsbookReference = (offer, basis) => basis === 'sportsbooks' || ['sportsbook_after_fees', 'public_estimate'].includes(offer?.value_basis);

export function selectedReference(offer, basis) {
  if (usesSportsbookReference(offer, basis) && offer?.sportsbook) {
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
  const source = offer.source_clock_at;
  const receipt = offer.received_at;
  const clock = value => new Date(value).toLocaleString();
  if (offer.posted_price && !mode) {
    const status = {fresh:'Recently confirmed', retained:inspection ? 'Retained pregame price' : 'Retained',
      unknown:'Freshness unverified'}[offer.quote_freshness] || 'Posted pregame price';
    return [status, source ? inspection ? 'Source ' + clock(source) : elapsedAge(source) || 'Source time unverified'
      : receipt ? 'Source time unknown · received ' + (inspection ? clock(receipt) : quoteAge(receipt).replace('Quote updated ', ''))
      : 'Source time unknown',
    inspection && offer.confirmed_at && offer.confirmed_at !== source && 'Book confirmation ' + clock(offer.confirmed_at)]
      .filter(Boolean).join(' · ');
  }
  if (offer.current) return mode ? 'Current at capture' : source ? quoteAge(source)
    : receipt ? 'Source time unknown · received ' + clock(receipt) : 'Source time unknown';
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
  const allOdds = Object.values(group.sportsbook_quotes || {}).flat().map(sportsbookOdds).filter(Boolean);
  const decimals = [...new Set(allOdds.map(price => Number(price.decimal)))];
  let places = 2;
  while (places < 10 && new Set(decimals.map(price => price.toFixed(places))).size < decimals.length) places++;
  for (const value of values) {
    const item = el('div');
    const odds = sportsbookOdds(value);
    item.append(odd(odds && {...odds, decimal_places:places}));
    if (value.source_at && (mode || inspection)) item.title = value.source_at;
    const isReference = usesReference(value);
    if (isReference) item.classList.add('matrix-reference');
    const label = [mode ? [value.current === false ? 'Last known at capture' : 'At capture',
      value.source_at && quoteAge(value.source_at, checkedAt)].filter(Boolean).join(' · ') :
      inspection && priceStatus(value.current, value.source_at, checkedAt),
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

export function noQuote(cell, venue, retained = false, explain = null, outcome = null) {
  const detail = retained ? 'A saved quote is available. Turn on Last-known prices to see it.'
    : 'No quote shown for this exact line.';
  const label = retained ? 'Saved quote' : 'No quote';
  const missing = explain ? button(label, event => explain(venue, outcome, detail, event.currentTarget), 'opportunity-link missing-quote')
    : el('span', label, 'desk-meta missing-quote');
  if (explain) {
    missing.setAttribute('aria-label', [venue, outcome, detail].filter(Boolean).join(' · '));
    missing.setAttribute('aria-haspopup', 'dialog');
    missing.setAttribute('aria-controls', 'quote-gap');
  } else missing.setAttribute('aria-label', detail);
  cell.append(missing);
}

export function priceStatus(current, at, checkedAt) {
  const status = current === false ? 'Last known' : 'Published quote';
  return at ? `${status} · ${quoteAge(at, checkedAt)}` : `${status} · Source time unknown`;
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
