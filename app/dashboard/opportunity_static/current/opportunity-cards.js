import {evidenceReason} from './desk-reasons.js';

const {el, num, fmt, name, odd, link, button} = window.PredictUI;
const basisLabels = {sportsbooks:'Indicative before-fee estimate', reviewed:'Verified after-fee EV',
  conservative:'Conservative after-fee scenario', before:'Before-fee scenario'};
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
  return null;
}

function fairReferenceLabel(reference) {
  if (reference?.method === 'authored_probability') return 'Authored practice probability';
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
    if (!entries.has(key)) entries.set(key, {fair, reference, venues:new Set()});
    entries.get(key).venues.add(venueLabel(offer));
  }
  for (const {fair, reference, venues} of entries.values()) {
    const price = el('div');
    price.append(odd(fair), el('small', reference));
    if (entries.size > 1) price.append(el('small', [...venues].join(', ')));
    cell.append(price);
  }
  if (!entries.size && group.sportsbook_reference && context.basis === 'sportsbooks') {
    cell.append(odd(group.sportsbook_reference.fair_odds), el('small', name(group.sportsbook_reference.book)));
  } else if (!entries.size) noQuote(cell, 'the EV reference');
  if (Object.keys(group.sportsbook_quotes || {}).length) {
    const fallback = !entries.size && context.basis === 'sportsbooks' ? group.sportsbook_reference : null;
    const reference = selectedReference(group.offers[0], context.basis) ?? fallback;
    const popout = el('div', null, 'matrix-sportsbook-popout');
    popout.id = `sportsbook-prices-${group.id}`;
    popout.setAttribute('popover', 'auto');
    popout.setAttribute('role', 'region');
    popout.setAttribute('aria-label', 'Sportsbook prices');
    popout.append(el('strong', context.position(group.offers[0])),
      sportsbookQuotes(group, reference, context.checkedAt, context.mode));
    const trigger = el('button', 'Sportsbooks', 'opportunity-link matrix-book-trigger');
    trigger.type = 'button';
    trigger.setAttribute('popovertarget', popout.id);
    trigger.setAttribute('aria-label', `Sportsbook prices for ${context.position(group.offers[0])}`);
    cell.append(trigger, popout);
  }
  return cell;
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
    updates_stopped:'updates inactive', sgo_paused_or_stopped:'updates paused',
    source_expired:'quote expired', 'Price expired':'quote expired',
    input_replaced_or_removed:'quote replaced or removed', source_unknown:'source time unverified'
  };
  const status = Object.entries(labels).find(([code]) => codes.includes(code))?.[1] || 'current quote unavailable';
  return `${mode ? 'Last known at capture' : 'Last known'} · ${status}`;
}

function quoteSourceAge(offer, checkedAt) {
  const source = elapsedAge(offer.source_clock_at, checkedAt);
  const confirmation = elapsedAge(offer.confirmed_at, checkedAt);
  if (source && confirmation && Date.parse(offer.confirmed_at) > Date.parse(offer.source_clock_at)) {
    return `Source ${source} · confirmed ${confirmation}`;
  }
  if (source || confirmation) return source ? `Source ${source}` : `Confirmed ${confirmation}`;
  return 'Source time unknown';
}

function sportsbookCell(group, book, reference, checkedAt, mode, inspection = false) {
  const cell = el('div', null, 'sportsbook-price');
  const selected = reference?.book === book && reference.prices?.[0];
  let values = group.sportsbook_quotes?.[book] || (selected ? [{...selected, current:true}] : []);
  if (selected && !values.some(value => value.current !== false &&
      value.price_american === selected.price_american && value.source_at === selected.source_at)) {
    values = [{...selected, current:true}, ...values];
  }
  for (const value of values) {
    const item = el('div');
    item.append(odd(sportsbookOdds(value)));
    if (value.source_at) item.title = value.source_at;
    const isReference = selected && value.current !== false
      && value.price_american === selected.price_american && value.source_at === selected.source_at;
    if (isReference) item.classList.add('matrix-reference');
    const freshness = el('small', [mode ? (value.current === false ? 'Last known at capture' : 'At capture') :
      priceStatus(value.current, value.source_at, checkedAt, inspection),
      isReference && 'EV reference'].filter(Boolean).join(' · '));
    if (inspection && !mode && value.current === true) freshness.dataset.inspectionBook = '1';
    item.append(freshness);
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
  section.append(el('small', 'Same-line sportsbook quotes'));
  const prices = el('div', null, 'sportsbook-prices');
  for (const book of books) {
    const cell = el('div');
    cell.append(el('strong', name(book)), sportsbookCell(group, book, reference, checkedAt, mode, inspection));
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
  const reason = quoteReason(offer);
  const freshness = quoteFreshness(offer, context.mode);
  const age = quoteSourceAge(offer, context.checkedAt);
  const calculation = reason || `${percent(offer.value)} ${basisName(context.basis) || 'return'}`;
  item.setAttribute('aria-label', [label, context.position(offer), offer.odds?.american,
    freshness, age, showResult && offer.current && calculation].filter(Boolean).join(', '));
  if (offer.source_clock_at || offer.confirmed_at) {
    item.title = [offer.source_clock_at && `Source update ${offer.source_clock_at}`,
      offer.confirmed_at && `Book confirmation ${offer.confirmed_at}`].filter(Boolean).join(' · ');
  }
  if (showResult) item.append(el('span', label, 'desk-site'));
  item.append(odd(offer.odds));
  item.append(el('small', offer.current && context.compact ? age : `${freshness} · ${age}`, 'quote-freshness'));
  if (showResult && offer.current) item.append(el('small', calculation, reason ? 'offer-reason' : tone(offer.value)));
  return item;
}

export function evCard(group, context) {
  if (context.compact) return compactEV(group, context);
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
      leg.append(el('small', context.mode ? 'At capture' : priceStatus(lead.reference_current || !!lead.sportsbook,
        price.source_at, context.checkedAt)));
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
  const inspect = button('View EV calculation ↗', event => context.inspectOffer(lead, group, event.currentTarget), 'opportunity-link');
  inspect.dataset.calculationId = lead.id;
  row.append(grid);
  if (settlementLabel(group)) row.append(el('p', settlementLabel(group), 'desk-meta'));
  if (group.sportsbook_quotes) row.append(sportsbookQuotes(group, reference, context.checkedAt, context.mode));
  row.append(cardActions(group, context, inspect));
  return row;
}

function compactEV(group, context) {
  const lead = group.offers[0];
  const row = el('article', null, 'opportunity-card compact-ev');
  row.dataset.groupId = group.id;
  const fair = lead.fair_odds;
  const inspect = button('', event => context.inspectOffer(lead, group, event.currentTarget),
    `opportunity-score ${tone(group.score)}`);
  inspect.title = basisName(context.basis);
  inspect.dataset.calculationId = lead.id;
  inspect.setAttribute('aria-label', [`View EV calculation: ${percent(group.score)}, ${venueLabel(lead)}`,
    fair && `sportsbook fair odds ${fair.american}`].filter(Boolean).join(', '));
  const headline = el('span', null, 'compact-ev-result');
  headline.append(el('strong', percent(group.score)), el('small', 'EV'));
  inspect.append(headline);
  if (fair) {
    const estimate = el('span', 'Sportsbook fair ', 'compact-fair');
    estimate.append(odd(fair));
    const source = fairReferenceLabel(lead.fair_reference);
    if (source) estimate.append(` · ${source}`);
    inspect.append(estimate);
  }
  row.append(cardHeader(group, context.position(lead), group.game_title, inspect, context.clock));
  const quotes = el('div', null, 'compact-prices');
  const seen = new Set();
  for (const offer of group.offers) {
    if (!offer.current || !offer.odds?.american || seen.has(offer.venue)) continue;
    seen.add(offer.venue);
    const price = quote(offer, group, context, offer === lead ? 'desk-best' : '', false);
    price.prepend(el('span', venueLabel(offer)));
    if (offer !== lead && offer.value != null) {
      price.append(el('small', `${percent(offer.value)} EV`, tone(offer.value)));
    }
    quotes.append(price);
  }
  const footer = el('div', null, 'compact-ev-footer');
  footer.append(quotes, context.gameLink(group));
  row.append(footer);
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
  row.append(cardHeader(group, group.game_title, '',
    score(group.score, net?.fee_basis === 'conservative'
      ? 'Completed-game return with conservative fees' : 'Completed-game return after fees'), context.clock));
  const content = el('ul', null, 'arb-card-legs');
  for (const leg of legs) {
    const item = el('li', null, 'desk-best');
    item.append(el('span', context.position(leg)), el('small', venueLabel(leg)), odd(leg.odds));
    if (!leg.current) item.append(el('small', quoteFreshness(leg, context.mode)));
    content.append(item);
  }
  const inspectPair = (pair, label) => {
    const inspect = button(label, event => context.inspectPair(pair, offers, group, event.currentTarget), 'opportunity-link');
    inspect.dataset.pairId = pair.id;
    return inspect;
  };
  row.append(content);
  if (net?.available) {
    row.append(el('p', `Funding ${cash(net.funding_usd)} · Lowest net payout ${cash(net.minimum_net_payout_usd)} · Worst profit/loss ${cash(net.minimum_net_profit_usd)}`, 'desk-meta'));
    row.append(el('p', 'Completed-game states only · Full arbitrage unverified', 'desk-meta'));
    if (net.execution_reason) row.append(el('p', evidenceReason(net.execution_reason), 'desk-meta'));
  } else {
    row.append(el('p', evidenceReason(net?.reason), 'desk-meta'));
  }
  row.append(cardActions(group, context, inspectPair(best, 'View payoff calculation ↗')));
  if (group.pairs.length > 1) {
    const detail = el('details', null, 'desk-expand');
    detail.dataset.id = group.id;
    detail.open = expanded;
    detail.append(el('summary', `Other pairings (${group.pairs.length - 1})`));
    for (const pair of group.pairs.slice(1)) {
      const pairLabel = pair.legs.map(id => venueLabel(offers.get(id))).join(' + ');
      detail.append(inspectPair(pair, `${pairLabel} · ${percent(pair.score)}`));
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

export function gameMatrix(groups, context, {includeAlternates, market, selectedLine}) {
  const visible = orderedMarkets(groups).filter(group => !group.withdrawn
    && (!market || market === group.market.market)
    && (context.compact || group.id === selectedLine || includeAlternates || group.offers.some(offer => offer.alternate !== true)));
  const allOffers = visible.flatMap(group => group.offers);
  const box = el('section', null, 'odds-card');
  const linked = visible[0] || groups[0];
  if (linked) {
    box.dataset.gameKey = linked.game_key;
    if (linked.source_event) box.dataset.sourceEvent = linked.source_event;
  }
  const header = el('header');
  header.append(el('h2', context.gameTitle || 'Markets'));
  if (context.showGameLink && linked) header.append(context.gameLink(linked));
  box.append(header);
  if (!visible.length) {
    box.append(el('p', 'No prices match these market filters.', 'matrix-empty'));
    return box;
  }
  const columns = venueColumns(allOffers, context.stableVenues);
  const table = el('table', null, 'odds-matrix');
  const thead = table.createTHead(), section = thead.insertRow(), headings = thead.insertRow();
  const outcome = heading('Exact outcome');
  outcome.rowSpan = 2;
  const fairOdds = heading('Fair odds');
  fairOdds.rowSpan = 2;
  const exchange = heading(context.summary ? 'Prediction markets' : 'Venue prices', 'colgroup');
  exchange.colSpan = columns.length;
  section.append(outcome, exchange);
  if (!context.summary) {
    const ev = heading(basisName(context.basis) || 'Calculation');
    ev.rowSpan = 2;
    section.append(ev);
  }
  section.append(fairOdds);
  headings.append(...columns.map(([, label]) => heading(label)));
  const body = table.createTBody();
  for (const group of visible) {
    const lead = group.offers[0];
    const tr = body.insertRow();
    tr.dataset.groupId = group.id;
    const side = heading(context.position(lead), 'row');
    const period = group.market.period === 'full_game' ? 'Full game' : name(group.market.period);
    if (!context.compact || group.market.period !== 'full_game') side.append(el('small', `${name(group.market.market)} · ${period}`));
    if (group.id === selectedLine) {
      tr.classList.add('selected-game-line');
      tr.setAttribute('aria-current', 'true');
    }
    if (settlementLabel(group) && !context.compact) side.append(el('small', settlementLabel(group)));
    tr.append(side);
    const currentPayouts = group.offers.filter(offer => offer.current).map(offer => num(offer.odds?.decimal));
    const highestPayout = Math.max(...currentPayouts);
    for (const [venue] of columns) {
      const cell = tr.insertCell();
      for (const offer of group.offers.filter(candidate => venueKey(candidate) === venue
        && (!context.compact || candidate.odds?.american)
        && (context.compact || group.id === selectedLine || includeAlternates || candidate.alternate !== true))) {
        const price = quote(offer, group, context, offer.current && offer.odds?.decimal != null
          && num(offer.odds.decimal) === highestPayout ? 'desk-best' : '', false);
        if (context.summary && offer.current && offer.value != null) {
          const label = `${percent(offer.value)} ${context.basis === 'reviewed' ? 'EV' : 'estimate'}`;
          price.dataset.calculationId = offer.id;
          price.append(el('small', label, tone(offer.value)));
          price.setAttribute('aria-label', `${price.getAttribute('aria-label')}, ${label}, ${basisName(context.basis)}`);
        }
        cell.append(price);
      }
      if (!cell.hasChildNodes()) noQuote(cell, name(venue), !context.summary && group.retained_venues?.includes(venue));
    }
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
      const calculation = button(result, event => context.inspectOffer(choice, group, event.currentTarget),
        `opportunity-link ${saved ? '' : tone(choice.value)}`);
      calculation.dataset.calculationId = choice.id;
      if (context.compact) calculation.title = `${venueLabel(choice)} · ${basisName(context.basis)}`;
      if (choice === saved) calculation.setAttribute('aria-label', `Last known EV ${result} at ${venueLabel(choice)}`);
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
  const cue = button('More columns →', () => {
    const atEnd = scroll.scrollLeft >= scroll.scrollWidth - scroll.clientWidth - 1;
    scroll.scrollBy({left:atEnd ? -scroll.scrollWidth : Math.round(scroll.clientWidth * .65), behavior:'smooth'});
  }, 'matrix-scroll-cue opportunity-link');
  cue.hidden = true;
  scroll.addEventListener('scroll', () => updateMatrixCue(scroll));
  box.append(cue, scroll);
  return box;
}

function updateMatrixCue(scroll) {
  const cue = scroll.previousElementSibling;
  const extent = scroll.scrollWidth - scroll.clientWidth;
  const atEnd = scroll.scrollLeft >= extent - 1;
  cue.hidden = extent <= 1;
  cue.textContent = atEnd ? 'First columns ←' : 'More columns →';
  cue.setAttribute('aria-label', atEnd ? 'Scroll to the first odds column' : 'Scroll to see more odds columns');
}

export function updateMatrixCues(results) {
  for (const region of results.querySelectorAll('.odds-card > .odds-scroll')) updateMatrixCue(region);
}
