import {evidenceReason} from './desk-reasons.js';

const {el, num, fmt, name, odd, link, button} = window.PredictUI;
const basisLabels = {sportsbooks:'Indicative before-fee estimate', reviewed:'Verified after-fee EV',
  conservative:'Conservative after-fee scenario', before:'Before-fee scenario'};
const compactBasisLabels = {sportsbooks:'Before-fee estimate', reviewed:'After-fee EV',
  conservative:'Conservative scenario', before:'Before-fee scenario'};
const matrixBasisLabels = {sportsbooks:'est.', reviewed:'EV', conservative:'est.', before:'scenario'};
const books = ['fanduel', 'draftkings', 'betmgm', 'caesars'];
const venues = ['kalshi', 'polymarket_us', 'novig', 'prophetx'];
const cash = value => value == null ? 'Unavailable' : new Intl.NumberFormat('en-US', {
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

function fairReferenceLabel(reference) {
  if (reference?.method === 'authored_probability') return 'Authored scenario probability';
  const names = reference?.books?.map(name);
  if (!names?.length) return '';
  if (reference.indicative) return `Indicative · ${names.join(', ')}`;
  return reference.method === 'median' ? `Median · ${names.join(', ')}` : names.join(', ');
}

function fairOddsCell(group, context) {
  const cell = el('td', null, 'matrix-fair-odds');
  const entries = new Map();
  for (const offer of group.offers) {
    if (!offer.current) continue;
    const fair = offer.fair_odds || (context.basis !== 'sportsbooks' && offer.reference_current && offer.reference)
      || offer.sportsbook?.fair_odds;
    const reference = fairReferenceLabel(offer.fair_reference);
    if (!fair || !reference) continue;
    const key = JSON.stringify([fair.decimal, reference]);
    if (!entries.has(key)) entries.set(key, {fair, reference, venues:new Set(), deadlines:[]});
    entries.get(key).venues.add(venueLabel(offer));
    entries.get(key).deadlines.push(offer.calculation_current_until);
  }
  for (const {fair, reference, venues, deadlines} of entries.values()) {
    const price = el('div');
    price.append(odd(fair), el('small', reference));
    if (entries.size > 1) price.append(el('small', [...venues].join(', ')));
    markCalculationExpiry(price, context, group, ...deadlines);
    cell.append(price);
  }
  if (!entries.size && group.sportsbook_reference && context.basis === 'sportsbooks') {
    const price = el('div');
    price.append(odd(group.sportsbook_reference.fair_odds), el('small', name(group.sportsbook_reference.book)));
    markCalculationExpiry(price, context, group, group.sportsbook_reference.current_until);
    cell.append(price);
  } else if (!entries.size) cell.append(el('small', 'Reference estimate unavailable'));
  return cell;
}

function appendSportsbookTrigger(cell, group, context) {
  if (!Object.values(group.sportsbook_quotes || {}).some(quotes => quotes.length)) return;
  const offer = group.offers[0];
  const outcome = context.position(offer);
  const reference = selectedReference(offer, context.basis)
    ?? (context.basis === 'sportsbooks' ? group.sportsbook_reference : null);
  const popout = el('div', null, 'matrix-sportsbook-popout');
  popout.id = `sportsbook-prices-${group.id}`;
  popout.setAttribute('popover', 'auto');
  popout.setAttribute('role', 'region');
  popout.setAttribute('aria-label', 'Sportsbook prices');
  popout.append(el('strong', outcome),
    sportsbookQuotes(group, reference, context.checkedAt, context.mode));
  const trigger = el('button', 'Same-line sportsbook quotes', 'opportunity-link matrix-book-trigger');
  trigger.type = 'button';
  trigger.setAttribute('popovertarget', popout.id);
  trigger.setAttribute('aria-label', `Same-line sportsbook quotes for ${outcome}`);
  cell.append(trigger, popout);
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

function noQuote(cell, venue, retained = false) {
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

function score(value, label) {
  const result = el('div', null, `opportunity-score ${tone(value)}`);
  result.append(el('strong', percent(value)), el('small', label));
  return result;
}

function earliestDeadline(...dates) {
  const deadline = Math.min(...dates.filter(Boolean).map(value => Date.parse(value)).filter(Number.isFinite));
  return Number.isFinite(deadline) ? String(deadline) : null;
}

function markCalculationExpiry(element, context, group, ...dates) {
  const deadline = earliestDeadline(context.phase === 'pregame' && group.start_at, ...dates);
  if (deadline) element.dataset.calculationDeadline = deadline;
}

function markQuoteExpiry(element, context, group, offer, description) {
  if (!offer.current || context.mode) return;
  const deadline = earliestDeadline(context.phase === 'pregame' && group.start_at, offer.current_until);
  if (!deadline) return;
  element.dataset.quoteDeadline = deadline;
  if (description) element.dataset.quoteDescription = description;
}

function cardHeader(group, title, subtitle, result, clock) {
  const header = el('header', null, 'opportunity-card-header');
  const description = el('div');
  const period = group.market.period === 'full_game' ? 'Full-game' : group.market.period?.replaceAll('_', ' ');
  description.append(el('small', [group.league, clock(group.start_at), [period, group.market.market].filter(Boolean).join(' ')].filter(Boolean).join(' · ')),
    el('h2', title));
  if (subtitle) description.append(el('p', subtitle));
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
  const item = button('', event => context.inspectOffer(offer, group, event.currentTarget), `desk-offer ${className}`);
  item.dataset.offerId = offer.id;
  if (offer.desk_quote_key) item.dataset.deskQuoteKey = offer.desk_quote_key;
  const reason = quoteReason(offer);
  const freshness = quoteFreshness(offer, context.mode);
  const calculation = reason || `${percent(offer.value)} ${basisName(context.basis) || 'return'}`;
  const description = [label, context.position(offer), offer.odds?.american].filter(Boolean).join(', ');
  item.setAttribute('aria-label', [description, freshness, showResult && offer.current && calculation, 'Quote details'].filter(Boolean).join(', '));
  markQuoteExpiry(item, context, group, offer, description);
  if (showResult) item.append(el('span', label, 'desk-site'));
  const price = el('span', null, 'quote-price');
  price.append(odd(offer.odds));
  item.append(price);
  if (!offer.current || context.mode) {
    const status = !offer.current && context.summary && !context.mode ? 'Last known' : freshness;
    item.append(el('small', status, 'quote-freshness'));
  }
  if (showResult && offer.current) {
    const result = el('small', calculation, reason ? 'offer-reason' : tone(offer.value));
    if (!reason) {
      result.dataset.quoteCalculation = '1';
      markCalculationExpiry(result, context, group, offer.current_until, offer.calculation_current_until);
    }
    item.append(result);
  }
  return item;
}

export function evCard(group, context) {
  if (context.compact) return compactEV(group, context);
  const lead = group.offers[0];
  const row = el('article', null, 'opportunity-card');
  row.dataset.groupId = group.id;
  const leadScore = score(group.score, group.score == null ? 'Missing calculation inputs' : `${venueLabel(lead)} · ${basisName(context.basis)}`);
  if (group.score != null) markCalculationExpiry(leadScore, context, group, lead.current_until, lead.calculation_current_until);
  row.append(cardHeader(group, context.position(lead), group.game_title, leadScore, context.clock));
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
      if (context.mode) leg.append(el('small', 'At capture'));
      prices.append(leg);
    });
    comparison.append(prices);
  }
  if (fair) {
    const estimate = el('span', 'Estimated fair odds ');
    estimate.append(odd(fair));
    markCalculationExpiry(estimate, context, group, lead.calculation_current_until);
    comparison.append(estimate);
  } else if (!reference) {
    comparison.append(el('span', lead.current ? quoteReason(lead) || 'No current same-line pair' : 'Offer price expired'));
  }
  grid.append(comparison);
  const inspect = button('View EV calculation ↗', event => context.inspectOffer(lead, group, event.currentTarget), 'opportunity-link');
  inspect.dataset.calculationId = lead.id;
  row.append(grid);
  if (settlementLabel(group)) row.append(el('p', settlementLabel(group), 'desk-meta'));
  if (group.sportsbook_quotes) row.append(sportsbookQuotes(group, reference, context.checkedAt, context.mode));
  row.append(cardActions(group, context, inspect));
  return row;
}

function compactEV(group, context) {
  const lead = group.offers.find(offer => offer.id === group.score_source?.id) || group.offers[0];
  const row = el('article', null, 'opportunity-card compact-ev');
  row.dataset.groupId = group.id;
  if (!context.nested) {
    const header = el('header', null, 'compact-ev-meta');
    const game = el('div', null, 'compact-ev-game');
    game.append(el('span', group.game_title), el('small', [group.league, context.clock(group.start_at)].filter(Boolean).join(' · ')));
    header.append(game, context.gameLink(group));
    row.append(header);
  }
  const market = el('div', null, 'compact-ev-market');
  market.append(el('h2', context.position(lead)));
  if (group.market.period && group.market.period !== 'full_game') {
    market.append(el('small', name(group.market.period), 'compact-ev-period'));
  }
  const label = compactBasisLabels[context.basis] || 'Return';
  const quotes = el('div', null, 'compact-prices');
  quotes.setAttribute('role', 'group');
  quotes.setAttribute('aria-label', 'Prediction market offers');
  const seen = new Set();
  // The server orders offers by the applicable exact EV basis.
  for (const offer of group.offers) {
    if (!offer.odds?.american || seen.has(offer.venue)) continue;
    seen.add(offer.venue);
    const value = offer.current ? offer.value ?? (offer === lead ? group.score : null) : null;
    const price = quote(offer, group, context, offer === lead && offer.current ? 'desk-best' : '', false);
    price.prepend(el('span', venueLabel(offer), 'compact-venue'));
    price.dataset.calculationId = offer.id;
    const accessible = `View trade details: ${venueLabel(offer)}, ${context.position(offer)}, ${offer.odds.american}`;
    price.dataset.quoteDescription = accessible;
    price.setAttribute('aria-label', [accessible, value != null ? `${percent(value)} ${label}` : quoteFreshness(offer, context.mode)].join(', '));
    if (value != null) {
      const ev = el('strong', percent(value), `compact-ev-return ${tone(value)}`);
      ev.dataset.quoteCalculation = '1';
      ev.title = basisName(context.basis) || label;
      markCalculationExpiry(ev, context, group, offer.current_until, offer.calculation_current_until);
      price.append(ev);
    }
    quotes.append(price);
  }
  market.append(quotes);
  row.append(market, compactBookQuotes(group, lead, context));
  return row;
}

function compactBookQuotes(group, lead, context) {
  const row = el('div', null, 'compact-books');
  row.setAttribute('role', 'group');
  row.setAttribute('aria-label', 'Fair odds and sportsbook quotes');
  const fallback = context.basis === 'sportsbooks' && !lead.fair_odds ? group.sportsbook_reference : null;
  const fair = lead.fair_odds || (context.basis === 'sportsbooks' ? lead.sportsbook?.fair_odds || fallback?.fair_odds
    : lead.reference_current && lead.reference);
  const fairValue = el('span', 'Fair odds ', 'compact-fair');
  fairValue.append(fair ? odd(fair) : 'unavailable');
  if (fair) markCalculationExpiry(fairValue, context, group, lead.calculation_current_until, fallback?.current_until);
  row.append(fairValue);

  const selected = lead.fair_reference?.selected_prices || {};
  const reference = context.basis === 'sportsbooks' && !lead.sportsbook ? fallback : selectedReference(lead, context.basis);
  const referenceBooks = lead.fair_reference?.books?.length ? lead.fair_reference.books : reference?.book ? [reference.book] : [];
  const available = group.sportsbook_quotes || {};
  const ordered = new Set([...referenceBooks, ...books.filter(book => available[book]), ...Object.keys(available)]);
  for (const book of ordered) {
    const comparison = referenceBooks.includes(book);
    const exact = selected[book] || (reference?.book === book && reference.prices?.[0]?.price_american);
    const quote = available[book]?.[0];
    const price = exact || quote?.price_american;
    if (!price) continue;
    const item = el('span', `${name(book)} `, comparison && exact ? 'compact-reference-book' : '');
    item.append(odd(sportsbookOdds(price)));
    if (comparison && exact) {
      const use = el('small', 'Used for fair odds');
      markCalculationExpiry(use, context, group, lead.calculation_current_until, fallback?.current_until);
      item.append(use);
    } else if (quote?.current === false) item.append(el('small', 'Last known'));
    row.append(item);
  }
  return row;
}

function venueKey(offer) {
  return offer.venue;
}

function venueColumns(offers, stable = false) {
  const columns = new Map(stable ? venues.map(venue => [venue, name(venue)]) : []);
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
  const payoffScore = score(group.score, net?.fee_basis === 'conservative'
    ? 'Completed-game return with conservative fees' : 'Completed-game return after fees');
  markCalculationExpiry(payoffScore, context, group, ...legs.map(leg => leg.current_until), best.calculation_current_until);
  row.append(cardHeader(group, group.game_title, '', payoffScore, context.clock));
  const content = el('ul', null, 'arb-card-legs');
  for (const leg of legs) {
    const item = el('li', null, leg.current ? 'desk-best' : '');
    item.append(el('span', context.position(leg)), el('small', venueLabel(leg)), odd(leg.odds));
    if (!leg.current) item.append(el('small', quoteFreshness(leg, context.mode)));
    markQuoteExpiry(item, context, group, leg);
    content.append(item);
  }
  const inspectPair = (pair, label, showScore = false) => {
    const inspect = button(label, event => context.inspectPair(pair, offers, group, event.currentTarget), 'opportunity-link');
    inspect.dataset.pairId = pair.id;
    if (showScore && pair.score != null) {
      const result = el('span', ` · ${percent(pair.score)}`);
      markCalculationExpiry(result, context, group, ...pair.legs.map(id => offers.get(id)?.current_until), pair.calculation_current_until);
      inspect.append(result);
    }
    return inspect;
  };
  row.append(content);
  if (net?.available) {
    const funds = el('p', `Funding ${cash(net.funding_usd)} · Lowest net payout ${cash(net.minimum_net_payout_usd)} · Worst profit/loss ${cash(net.minimum_net_profit_usd)}`, 'desk-meta');
    markCalculationExpiry(funds, context, group, ...legs.map(leg => leg.current_until), best.calculation_current_until);
    row.append(funds);
    row.append(el('p', 'Completed-game states only · Full arbitrage unverified', 'desk-meta'));
    if (net.execution_reason) row.append(el('p', evidenceReason(net.execution_reason), 'desk-meta'));
  } else {
    row.append(el('p', evidenceReason(net?.reason), 'desk-meta'));
  }
  const pairLabel = net?.reason === 'pair_leg_stale_or_replaced' ? 'Inspect last-known legs ↗'
    : net?.available || best.inspection || best.evidence_result_id && net?.reason !== 'pair_settlement_unverified'
      ? 'View payoff calculation ↗' : 'Inspect pairing evidence ↗';
  row.append(cardActions(group, context, inspectPair(best, pairLabel)));
  if (group.pairs.length > 1) {
    const detail = el('details', null, 'desk-expand');
    detail.dataset.id = group.id;
    detail.open = expanded;
    detail.append(el('summary', `Other pairings (${group.pairs.length - 1})`));
    for (const pair of group.pairs.slice(1)) {
      const pairLabel = pair.legs.map(id => venueLabel(offers.get(id))).join(' + ');
      detail.append(inspectPair(pair, pairLabel, true));
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

export function gameMatrix(groups, context, {includeAlternates, market, selectedLine, disclosure}) {
  const visible = orderedMarkets(groups).filter(group => !group.withdrawn
    && (!market || market === group.market.market)
    && (context.compact || group.id === selectedLine || includeAlternates || group.offers.some(offer => offer.alternate !== true)));
  const box = el('section', null, 'odds-card');
  const linked = visible[0] || groups[0];
  if (linked) {
    box.dataset.gameKey = linked.game_key;
    if (linked.source_event) box.dataset.sourceEvent = linked.source_event;
  }
  let actions;
  if (context.gameTitle || context.showGameLink) {
    const header = el('header');
    header.append(el('h2', context.gameTitle || 'Markets'));
    if (context.showGameLink && linked) {
      actions = el('div', null, 'odds-card-actions');
      actions.append(context.gameLink(linked));
      header.append(actions);
    }
    box.append(header);
  }
  if (!visible.length) {
    box.append(el('p', 'No prices match these market filters.', 'matrix-empty'));
    return box;
  }
  if (!disclosure) {
    appendMarketMatrix(box, visible, context, {selectedLine, includeAlternates, actions});
    return box;
  }
  box.classList.add('odds-disclosure');
  const details = el('details', null, 'market-disclosure');
  const summary = el('summary', `Compare ${visible.length} ${visible.length === 1 ? 'outcome' : 'outcomes'}`);
  details.dataset.id = disclosure.id;
  details.open = disclosure.open;
  details.append(summary);
  box.append(details);
  const openMatrix = () => {
    if (details.open && details.childElementCount === 1) appendMarketMatrix(details, visible, context, {selectedLine, includeAlternates});
    const scroll = details.querySelector('.odds-scroll');
    if (details.open && scroll) updateMatrixCue(scroll);
  };
  if (details.open) appendMarketMatrix(details, visible, context, {selectedLine, includeAlternates});
  details.addEventListener('toggle', openMatrix);
  return box;
}

function appendMarketMatrix(container, visible, context, {selectedLine, includeAlternates, actions}) {
  const allOffers = visible.flatMap(group => group.offers);
  const columns = venueColumns(allOffers, context.stableVenues)
    .filter(([venue]) => !context.selectedVenues || context.selectedVenues.includes(venue));
  const table = el('table', null, 'odds-matrix');
  if (context.summary && context.stableVenues && columns.length === venues.length) {
    table.classList.add('standard-columns');
    const layout = el('colgroup');
    layout.append(el('col', null, 'outcome-column'), ...columns.map(() => el('col')), el('col', null, 'reference-column'));
    table.append(layout);
  }
  const thead = table.createTHead();
  const outcomes = heading('Outcome');
  const fairOdds = heading('Fair odds');
  const venueHeadings = columns.map(([, label]) => heading(label));
  venueHeadings.forEach((cell, index) => { cell.dataset.venueColumn = columns[index][0]; });
  if (context.summary) {
    thead.insertRow().append(outcomes, ...venueHeadings, fairOdds);
  } else {
    const section = thead.insertRow();
    const exchange = heading('Venue prices', 'colgroup');
    const ev = heading(basisName(context.basis) || 'Calculation');
    exchange.colSpan = columns.length;
    outcomes.rowSpan = ev.rowSpan = fairOdds.rowSpan = 2;
    section.append(outcomes, exchange, ev, fairOdds);
    thead.insertRow().append(...venueHeadings);
  }
  const body = table.createTBody();
  const quotedVenues = new Set();
  for (const group of visible) {
    const lead = group.offers[0];
    const tr = body.insertRow();
    tr.dataset.groupId = group.id;
    const side = heading(null, 'row');
    side.append(el('span', context.position(lead), 'matrix-outcome'));
    const period = group.market.period === 'full_game' ? 'Full game' : name(group.market.period);
    if (!context.compact || group.market.period !== 'full_game') side.append(el('small', `${name(group.market.market)} · ${period}`));
    if (group.id === selectedLine) {
      tr.classList.add('selected-game-line');
      tr.setAttribute('aria-current', 'true');
    }
    if (settlementLabel(group) && !context.compact) side.append(el('small', settlementLabel(group)));
    appendSportsbookTrigger(side, group, context);
    tr.append(side);
    const currentPayouts = group.offers.filter(offer => offer.current).map(offer => num(offer.odds?.decimal));
    const highestPayout = Math.max(...currentPayouts);
    let hasQuote = false;
    for (const [venue] of columns) {
      const cell = tr.insertCell();
      for (const offer of group.offers.filter(candidate => venueKey(candidate) === venue
        && (!context.compact || candidate.odds?.american)
        && (context.compact || group.id === selectedLine || includeAlternates || candidate.alternate !== true))) {
        const price = quote(offer, group, context, offer.current && offer.odds?.decimal != null
          && num(offer.odds.decimal) === highestPayout ? 'desk-best' : '', false);
        if (context.summary && offer.current && offer.value != null) {
          const label = percent(offer.value);
          price.dataset.calculationId = offer.id;
          const value = el('small', `${label} ${matrixBasisLabels[context.basis] || 'return'}`, tone(offer.value));
          markCalculationExpiry(value, context, group, offer.current_until, offer.calculation_current_until);
          price.append(value);
          price.setAttribute('aria-label', `${price.getAttribute('aria-label')}, ${label} ${basisName(context.basis) || 'return'}`);
          value.dataset.quoteCalculation = '1';
        } else if (context.summary && offer.current) {
          const gap = el('small', 'EV unavailable', 'offer-reason');
          gap.title = quoteReason(offer);
          price.append(gap);
        }
        cell.append(price);
        quotedVenues.add(venue);
        hasQuote = true;
      }
      if (!cell.hasChildNodes()) noQuote(cell, name(venue), !context.summary && group.retained_venues?.includes(venue));
    }
    if (!hasQuote && context.selectedVenues) side.append(el('small', 'No quote from selected sites', 'desk-meta'));
    if (context.summary) {
      tr.append(fairOddsCell(group, context));
      continue;
    }
    const value = tr.insertCell();
    const current = group.offers.find(offer => offer.current && offer.value != null);
    const saved = !current && group.offers.reduce((best, offer) => (
      offer.last_known_ev != null && (!best || num(offer.last_known_ev) > num(best.last_known_ev)) ? offer : best
    ), null);
    const choice = current || saved;
    if (choice) {
      const result = percent(choice.value ?? choice.last_known_ev);
      const calculation = button(saved ? result : '', event => context.inspectOffer(choice, group, event.currentTarget),
        `opportunity-link ${saved ? '' : tone(choice.value)}`);
      calculation.dataset.calculationId = choice.id;
      if (context.compact) calculation.title = `${venueLabel(choice)} · ${basisName(context.basis)}`;
      if (choice === saved) calculation.setAttribute('aria-label', `Last known EV ${result} at ${venueLabel(choice)}`);
      else {
        const scoreText = el('span', result);
        markCalculationExpiry(scoreText, context, group, choice.current_until, choice.calculation_current_until);
        calculation.append(scoreText, el('span', 'Unavailable', 'desk-meta expired-matrix-value'));
      }
      value.append(calculation);
      if (choice === saved || !context.compact) value.append(el('small', choice === saved ? 'Last known' : venueLabel(choice)));
    } else {
      const missing = el('small', context.compact ? 'Unavailable' : quoteReason(lead));
      missing.title = quoteReason(lead);
      missing.setAttribute('aria-label', quoteReason(lead));
      if (context.compact) {
        const price = button('—', event => context.inspectOffer(lead, group, event.currentTarget), 'opportunity-link missing-quote');
        price.setAttribute('aria-label', `EV unavailable for ${context.position(lead)}. View details.`);
        value.append(price);
      } else value.append(missing);
    }
    tr.append(fairOddsCell(group, context));
  }
  const scroll = scrollTable(table, 'Prediction market odds and fair odds');
  for (const cell of venueHeadings) cell.toggleAttribute('data-has-quotes', quotedVenues.has(cell.dataset.venueColumn));
  const cue = button('More columns →', () => {
    const atEnd = scroll.scrollLeft >= scroll.scrollWidth - scroll.clientWidth - 1;
    const next = nextQuoteColumn(scroll);
    const stickyWidth = outcomes.getBoundingClientRect().width;
    const shift = next ? next.getBoundingClientRect().left - scroll.getBoundingClientRect().left - stickyWidth
      : Math.round(scroll.clientWidth * .65);
    const left = atEnd ? 0 : scroll.scrollLeft + shift;
    scroll.scrollTo({left, behavior:'instant'});
  }, 'matrix-scroll-cue opportunity-link');
  cue.hidden = true;
  scroll.addEventListener('scroll', () => updateMatrixCue(scroll));
  (actions || container).append(cue);
  if (context.summary) container.append(el('p', 'Select odds marked ↗ for quote details. A dash means no quote shown for that site and exact outcome.', 'matrix-key desk-meta'));
  container.append(scroll);
}

function nextQuoteColumn(scroll) {
  const right = scroll.getBoundingClientRect().right;
  return [...scroll.querySelectorAll('[data-has-quotes]')].find(cell => cell.getBoundingClientRect().right > right + 6);
}

function updateMatrixCue(scroll) {
  const cue = scroll.closest('.odds-card').querySelector('.matrix-scroll-cue');
  const extent = scroll.scrollWidth - scroll.clientWidth;
  const atEnd = scroll.scrollLeft >= extent - 1;
  cue.hidden = extent <= 1;
  const next = nextQuoteColumn(scroll);
  cue.textContent = atEnd ? 'First columns ←' : next ? `See ${next.textContent} prices →` : 'More columns →';
  cue.setAttribute('aria-label', atEnd ? 'Scroll to the first odds column'
    : next ? `See ${next.textContent} prices in the next columns` : 'Scroll to see more odds columns');
}

export function updateMatrixCues(results) {
  for (const region of results.querySelectorAll('.odds-card .odds-scroll')) updateMatrixCue(region);
}
