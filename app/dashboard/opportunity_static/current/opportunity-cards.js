import {evidenceReason} from './desk-reasons.js';

const {el, num, fmt, name, odd, link, button} = window.PredictUI;
const basisLabels = {sportsbooks:'Sportsbook estimate before fees', reviewed:'Reviewed-fee EV', conservative:'Modeled EV after fee', before:'Qualified EV before fees'};
const books = ['fanduel', 'draftkings', 'betmgm', 'caesars'];
const venues = ['kalshi', 'polymarket_us', 'novig', 'prophetx'];
const dollars = new Intl.NumberFormat('en-US', {style:'currency', currency:'USD', maximumFractionDigits:6});
export const money = value => value == null ? 'Unavailable' : dollars.format(num(value));
const cash = value => value == null ? 'Unavailable' : new Intl.NumberFormat('en-US', {
  style:'currency', currency:'USD'
}).format(num(value));
export const percent = value => value == null ? 'Unavailable' : `${num(value) > 0 ? '+' : ''}${fmt(value)}%`;
export const tone = value => num(value) > 0 ? 'positive' : num(value) < 0 ? 'negative' : '';
export const basisName = basis => basisLabels[basis];
export const venueLabel = offer => name(offer.venue);

export function quoteReason(offer) {
  if (!offer.current) return offer.reason === 'Price unavailable' ? 'Price unavailable' : 'Last known · expired';
  if (offer.value != null) return null;
  const reason = String(offer.reason || '').split(', ')[0];
  return evidenceReason(reason, 'No qualified same-line sportsbook pair.').replace(/\.$/, '');
}

export function selectedReference(offer, basis) {
  if (basis === 'sportsbooks' && offer?.sportsbook) {
    return {book:offer.sportsbook.book, prices:offer.sportsbook.prices, candidates:offer.sportsbook.candidates};
  }
  const ref = offer?.reference_current && offer.reference_calculation;
  const book = ref && ref.contributors?.find(item => item.venue === ref.venue || item.venue === ref.bookmaker)
    || ref?.contributors?.[0];
  if (book) return {book:book.venue, prices:book.inputs, candidates:ref.candidates};
  return null;
}

function sportsbookOdds(price) {
  if (price?.american && price?.decimal) return price;
  const american = price?.price_american ?? price?.american ?? price;
  const amount = num(american);
  if (!Number.isFinite(amount) || !amount) return null;
  return {american:amount > 0 ? `+${amount}` : String(amount),
    decimal:amount > 0 ? 1 + amount / 100 : 1 + 100 / -amount};
}

export function quoteAge(source, checkedAt = Date.now()) {
  const elapsed = Math.floor((new Date(checkedAt) - new Date(source)) / 1000);
  if (!source || !Number.isFinite(elapsed) || elapsed < 0) return 'Quote time unknown';
  if (elapsed < 60) return `Quote updated ${elapsed}s ago`;
  if (elapsed < 3600) return `Quote updated ${Math.floor(elapsed / 60)}m ago`;
  return `Quote updated ${Math.floor(elapsed / 3600)}h ago`;
}

function sportsbookCell(group, book, reference, checkedAt) {
  const cell = el('div', null, 'sportsbook-price');
  const selected = reference?.book === book && reference.prices?.[0];
  const values = group.sportsbook_quotes?.[book] || (selected ? [selected] : []);
  for (const value of values) {
    const item = el('div');
    item.append(odd(sportsbookOdds(value)));
    if (value.source_at) item.title = value.source_at;
    if (selected && value.current !== false
        && value.price_american === selected.price_american && value.source_at === selected.source_at) {
      item.classList.add('matrix-reference');
      item.append(el('small', 'EV reference'));
    } else if (value.current === false) {
      item.append(el('small', `Last known · ${quoteAge(value.source_at, checkedAt)}`));
    }
    cell.append(item);
  }
  if (!values.length) cell.append(el('span', '—', 'desk-meta'));
  return cell;
}

export function settlementLabel(group) {
  return ({matched:'Venue settlement rules match', different:'Venue settlement rules differ',
    unverified:'Venue settlement match unverified'})[group.settlement_match];
}

export function winPayout(offer) {
  const cost = num(offer.cost_per_normal_claim);
  const multiplier = cost > 0 ? 1 / cost : num(offer.odds?.decimal);
  return multiplier > 1 && Number.isFinite(multiplier)
    ? `$10 pays ${cash(multiplier * 10)} on a win before fees` : null;
}

export function sportsbookQuotes(group, reference, checkedAt) {
  const section = el('div', null, 'sportsbook-comparison');
  section.append(el('small', 'Same-line sportsbook quotes'));
  const prices = el('div', null, 'sportsbook-prices');
  for (const book of books) {
    const cell = el('div');
    cell.append(el('strong', name(book)), sportsbookCell(group, book, reference, checkedAt));
    prices.append(cell);
  }
  section.append(prices);
  if (group.sportsbook_source_reason) {
    section.append(el('small', evidenceReason(group.sportsbook_source_reason)));
  }
  return section;
}

function score(value, label) {
  const result = el('div', null, `opportunity-score ${tone(value)}`);
  result.append(el('strong', percent(value)), el('small', label));
  return result;
}

function cardHeader(group, title, subtitle, result, clock) {
  const header = el('header', null, 'opportunity-card-header');
  const description = el('div');
  const period = group.market.period === 'full_game' ? 'Full-game' : group.market.period?.replaceAll('_', ' ');
  description.append(el('small', [group.league, clock(group.start_at), [period, group.market.market].filter(Boolean).join(' ')].filter(Boolean).join(' · ')),
    el('h2', title), el('p', subtitle));
  header.append(description, result);
  return header;
}

function cardActions(group, context, inspect) {
  const footer = el('footer', null, 'opportunity-actions');
  footer.append(context.gameLink(group), inspect);
  return footer;
}

function quote(offer, group, context, className = '', showResult = true) {
  const label = venueLabel(offer);
  const item = button('', () => context.inspectOffer(offer, group), `desk-offer ${className}`);
  item.dataset.offerId = offer.id;
  const reason = quoteReason(offer);
  item.setAttribute('aria-label', [label, context.position(offer), offer.odds?.american, showResult && (reason || `${percent(offer.value)} EV`),
    !showResult && !offer.current && 'Last known price'].filter(Boolean).join(', '));
  if (showResult) item.append(el('span', label, 'desk-site'));
  item.append(odd(offer.odds));
  if (showResult) item.append(el('small', reason || `${percent(offer.value)} EV`, reason ? 'offer-reason' : tone(offer.value)));
  else {
    if (!offer.current) item.append(el('small', 'Last known'));
    if (offer.current && context.showWinPayout && winPayout(offer)) item.append(el('small', winPayout(offer)));
  }
  return item;
}

export function evCard(group, context) {
  const lead = group.offers[0];
  const row = el('article', null, 'opportunity-card');
  row.dataset.groupId = group.id;
  row.append(cardHeader(group, context.position(lead), group.game_title,
    score(group.score, group.score == null ? 'Missing calculation inputs' : `${venueLabel(lead)} · ${basisName(context.basis)}`), context.clock));
  const grid = el('div', null, 'opportunity-quotes');
  for (const offer of group.offers) {
    grid.append(quote(offer, group, context, group.score != null && offer === lead ? 'desk-best' : ''));
  }
  const reference = selectedReference(lead, context.basis);
  const fair = context.basis === 'sportsbooks' ? lead.sportsbook?.fair_odds
    : lead.reference_current && lead.reference;
  const comparison = el('div', null, 'opportunity-reference');
  comparison.append(el('small', 'Comparison sportsbook'));
  if (reference) {
    comparison.append(el('strong', name(reference.book)));
    const prices = el('div', null, 'opportunity-reference-prices');
    reference.prices?.forEach((price, index) => {
      const participant = context.game?.participants?.find(item => item.role === price.side)?.name;
      const line = price.line != null ? `${num(price.line) > 0 && participant ? '+' : ''}${num(price.line)}` : null;
      const side = price.label || [participant || name(price.side), line].filter(value => value != null).join(' ') || (index ? 'Opposite' : 'Selected');
      const leg = el('span');
      leg.append(`${side} `, odd(sportsbookOdds(price)));
      prices.append(leg);
    });
    comparison.append(prices);
  }
  if (fair) {
    const estimate = el('span', 'Estimated fair odds ');
    estimate.append(odd(fair));
    comparison.append(estimate);
  } else if (!reference) {
    comparison.append(el('span', lead.current ? quoteReason(lead) || 'No current same-line pair' : 'Offer price expired'));
  }
  grid.append(comparison);
  const inspect = button('View EV calculation ↗', () => context.inspectOffer(lead, group), 'opportunity-link');
  inspect.dataset.calculationId = lead.id;
  row.append(grid);
  if (settlementLabel(group)) row.append(el('p', settlementLabel(group), 'desk-meta'));
  if (group.sportsbook_quotes) row.append(sportsbookQuotes(group, reference, context.checkedAt));
  row.append(cardActions(group, context, inspect));
  return row;
}

function sideKey(offer) {
  const side = offer.selection || {};
  return JSON.stringify([side.predicate, side.participant ?? offer.participant, num(side.signed_line ?? offer.market.line)]);
}

function venueKey(offer) {
  return offer.venue;
}

function venueColumns(offers, stable = false) {
  const columns = new Map(stable ? [
    ['kalshi', name('kalshi')], ['polymarket_us', name('polymarket_us')], ['novig', name('novig')]
  ] : []);
  for (const offer of offers) columns.set(venueKey(offer), venueLabel(offer));
  const priority = key => {
    const index = venues.indexOf(key.split(':')[0]);
    return index < 0 ? venues.length : index;
  };
  return [...columns].sort(([left], [right]) => priority(left) - priority(right) || left.localeCompare(right));
}

function scrollTable(table, label) {
  const scroll = el('div', null, 'odds-scroll');
  scroll.tabIndex = 0;
  scroll.setAttribute('role', 'region');
  scroll.setAttribute('aria-label', label);
  scroll.append(table);
  return scroll;
}

function heading(text, scope = 'col') {
  const cell = el('th', text);
  cell.scope = scope;
  return cell;
}

export function arbCard(group, context, expanded) {
  const row = el('article', null, 'opportunity-card opportunity-arb');
  row.dataset.groupId = group.id;
  const best = group.pairs[0];
  const offers = new Map(group.offers.map(offer => [offer.id, offer]));
  const legs = best.legs.map(id => offers.get(id));
  const net = best.retail_payoff;
  row.append(cardHeader(group, group.game_title, legs.map(context.position).join(' / '),
    score(group.score, net?.available ? `${cash(net.minimum_net_profit_usd)} worst modeled result` : 'Net payoff unavailable'), context.clock));
  const content = el('div', null, 'arb-card-comparison');
  const columns = venueColumns(group.offers);
  const table = el('table', null, 'odds-matrix');
  const header = table.createTHead().insertRow();
  header.append(heading('Opposing sides'), ...columns.map(([, label]) => heading(label)));
  const body = table.createTBody();
  for (const leg of legs) {
    const tr = body.insertRow();
    tr.append(heading(context.position(leg), 'row'));
    for (const [venue] of columns) {
      const cell = tr.insertCell();
      for (const offer of group.offers.filter(candidate => venueKey(candidate) === venue && sideKey(candidate) === sideKey(leg))) {
        const chosen = best.legs.includes(offer.id);
        const item = quote(offer, group, context, chosen ? 'desk-best' : '', false);
        if (chosen) item.append(el('small', 'Selected leg'));
        cell.append(item);
      }
      if (!cell.hasChildNodes()) cell.append(el('span', '—', 'desk-meta'));
    }
  }
  content.append(scrollTable(table, 'Opposing venue prices'));
  const summary = el('div', null, 'opportunity-reference');
  summary.append(el('small', 'Modeled pair'), el('strong', legs.map(venueLabel).join(' + ')));
  if (net?.available) {
    const size = net.sizing ? `${net.sizing.quantity} contracts per leg · ` : '';
    summary.append(el('span', `${size}${cash(net.funding_usd)} total with fees`));
    net.legs?.forEach((leg, index) => {
      summary.append(el('span', `${cash(leg.acquisition_usd)} on ${context.position(legs[index])} · ${venueLabel(legs[index])}`));
    });
    if (net.states) {
      const receipts = Object.values(net.states).map(state => num(state.net_receipt_usd)).filter(Number.isFinite);
      if (receipts.length) summary.append(el('span', `${cash(Math.min(...receipts))} lowest modeled payout`));
    }
  } else summary.append(el('span', evidenceReason(net?.reason || 'pair_settlement_unverified')));
  content.append(summary);
  const inspectPair = (pair, label) => {
    const inspect = button(label, () => context.inspectPair(pair, offers, group), 'opportunity-link');
    inspect.dataset.pairId = pair.id;
    return inspect;
  };
  row.append(content, cardActions(group, context, inspectPair(best, 'View payoff calculation ↗')));
  if (group.pairs.length > 1) {
    const detail = el('details', null, 'desk-expand');
    detail.dataset.id = group.id;
    detail.open = expanded;
    detail.append(el('summary', `Other pairings (${group.pairs.length - 1})`));
    for (const pair of group.pairs.slice(1)) {
      const pairLabel = pair.legs.map(id => venueLabel(offers.get(id))).join(' + ');
      detail.append(inspectPair(pair, `${pairLabel} · ${pair.retail_payoff?.available ? money(pair.retail_payoff.minimum_net_profit_usd) : 'Net payoff unavailable'}`));
    }
    row.append(detail);
  }
  return row;
}

function lineOrder(offer, participants) {
  const line = offer.selection?.signed_line ?? offer.market.line;
  const value = num(line) ?? 0;
  const participant = offer.selection?.participant ?? offer.participant;
  return offer.market.market === 'spread' && participants.length === 2 && participant === participants[1]
    ? -value : value;
}

function orderedMarkets(groups) {
  const family = ['winner', 'spread', 'total'];
  const side = ['win', 'not_win', 'cover', 'not_cover', 'over', 'under'];
  const participants = [...new Set(groups.map(group => group.offers[0])
    .filter(offer => offer.market.market === 'spread')
    .map(offer => offer.selection?.participant ?? offer.participant).filter(Boolean))].sort();
  if (groups.every(group => group.matrix_order != null)) return [...groups].sort((a, b) => a.matrix_order - b.matrix_order);
  return [...groups].sort((a, b) => {
    const left = a.offers[0], right = b.offers[0];
    const market = family.indexOf(left.market.market) - family.indexOf(right.market.market);
    const order = lineOrder(left, participants) - lineOrder(right, participants);
    const predicate = side.indexOf(left.selection?.predicate) - side.indexOf(right.selection?.predicate);
    return market || order || predicate || a.id.localeCompare(b.id);
  });
}

export function gameMatrix(groups, context, {includeAlternates, market}) {
  const visible = orderedMarkets(groups).filter(group => !group.withdrawn
    && (!market || market === group.market.market)
    && (includeAlternates || group.offers.some(offer => offer.alternate !== true)));
  const allOffers = visible.flatMap(group => group.offers);
  const box = el('section', null, 'odds-card');
  const header = el('header');
  header.append(el('h2', context.gameTitle || 'Full-game markets'), el('p', `${visible.length} exact ${visible.length === 1 ? 'outcome' : 'outcomes'}`, 'desk-meta'));
  if (context.showGameLink && groups[0]) header.append(context.gameLink(groups[0]));
  box.append(header);
  if (!visible.length) {
    box.append(el('p', 'No prices match these market filters.', 'matrix-empty'));
    return box;
  }
  const columns = venueColumns(allOffers, context.stableVenues);
  const table = el('table', null, 'odds-matrix');
  const thead = table.createTHead(), section = thead.insertRow(), headings = thead.insertRow();
  const outcome = heading('Exact outcome'), ev = heading('EV');
  outcome.rowSpan = ev.rowSpan = 2;
  const exchange = heading('Venue prices', 'colgroup'), sportsbook = heading('Sportsbook quotes', 'colgroup');
  exchange.colSpan = columns.length;
  sportsbook.colSpan = books.length;
  section.append(outcome, exchange, sportsbook, ev);
  headings.append(...columns.map(([, label]) => heading(label)), ...books.map(book => heading(name(book))));
  const body = table.createTBody();
  for (const group of visible) {
    const lead = group.offers[0];
    const reference = selectedReference(lead, context.basis);
    const tr = body.insertRow();
    tr.dataset.groupId = group.id;
    const side = heading(context.position(lead), 'row');
    side.append(el('small', `${group.offers.every(offer => offer.alternate === true) ? 'Alternate ' : ''}${name(group.market.market)} · Full game`));
    if (settlementLabel(group)) side.append(el('small', settlementLabel(group)));
    tr.append(side);
    const currentPayouts = group.offers.filter(offer => offer.current).map(offer => num(offer.odds?.decimal));
    const highestPayout = Math.max(...currentPayouts);
    for (const [venue] of columns) {
      const cell = tr.insertCell();
      for (const offer of group.offers.filter(candidate => venueKey(candidate) === venue && (includeAlternates || candidate.alternate !== true))) {
        cell.append(quote(offer, group, context, offer.current && offer.odds?.decimal != null
          && num(offer.odds.decimal) === highestPayout ? 'desk-best' : '', false));
      }
      if (!cell.hasChildNodes()) cell.append(el('span', '—', 'desk-meta'));
    }
    for (const book of books) {
      tr.insertCell().append(sportsbookCell(group, book, reference, context.checkedAt));
    }
    const value = tr.insertCell();
    if (lead.value != null) {
      const calculation = button(percent(lead.value), () => context.inspectOffer(lead, group), `opportunity-link ${tone(lead.value)}`);
      calculation.dataset.calculationId = lead.id;
      value.append(calculation, el('small', venueLabel(lead)));
    } else value.append(el('small', quoteReason(lead)));
  }
  box.append(scrollTable(table, 'Venue and sportsbook odds'), el('p', 'Highlighted venue odds show the highest current payout. A dash means no quote is shown. Turn on Last-known prices to include retained quotes.', 'matrix-legend desk-meta'));
  return box;
}
