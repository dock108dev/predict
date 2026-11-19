import {evidenceReason} from './desk-reasons.js';
import {pairPayoff, pairLegSize} from './desk-inspection.js';
import {ticketFacts} from './desk-ticketboard.js';
import {basisName, books, noQuote, percent, quoteFreshness, quoteReason, selectedReference,
  settlementLabel, sportsbookOdds, sportsbookQuotes, tone, venueLabel} from './desk-quote-display.js';

const {el, num, name, odd, link, button} = window.PredictUI;
export {basisName, percent, priceStatus, quoteAge, quoteFreshness, quoteReason, selectedReference,
  settlementLabel, sportsbookQuotes, tone, venueLabel, winPayout} from './desk-quote-display.js';

const compactBasisLabels = {sportsbooks:'Before-fee estimate', reviewed:'After-fee EV',
  conservative:'Conservative after-fee estimate', before:'Before-fee scenario',
  after_fees:'Estimated EV after fees', sportsbook_after_fees:'Modeled after-fee estimate', public_estimate:'Estimated Net EV · $100'};
const matrixBasisLabels = {sportsbooks:'est.', reviewed:'EV', conservative:'est.', before:'scenario',
  after_fees:'EV', sportsbook_after_fees:'est.', public_estimate:'Estimated Net EV · $100'};
const venues = ['kalshi', 'polymarket_us', 'novig', 'prophetx'];

function fairReferenceLabel(reference) {
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
    const price = el('div');
    price.append(odd(group.sportsbook_reference.fair_odds), el('small', name(group.sportsbook_reference.book)));
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
  const popout = el('dialog', null, 'matrix-sportsbook-popout');
  popout.id = `sportsbook-prices-${group.id}`;
  popout.setAttribute('aria-label', 'Same-line sportsbook quotes');
  const heading = el('header');
  const close = button('Close', () => popout.close(), 'opportunity-link');
  heading.append(el('strong', outcome), close);
  popout.append(heading, sportsbookQuotes(group, reference, context.checkedAt, context.mode));
  const outside = event => {
    const {left, right, top, bottom} = popout.getBoundingClientRect();
    return event.target === popout && (event.clientX < left || event.clientX > right
      || event.clientY < top || event.clientY > bottom);
  };
  let backdropDown = false;
  popout.addEventListener('pointerdown', event => { backdropDown = outside(event); });
  popout.addEventListener('click', event => {
    if (backdropDown && outside(event)) popout.close();
    backdropDown = false;
  });
  const trigger = el('button', 'Same-line sportsbook quotes', 'opportunity-link matrix-book-trigger');
  trigger.type = 'button';
  trigger.setAttribute('aria-controls', popout.id);
  trigger.setAttribute('aria-haspopup', 'dialog');
  trigger.onclick = () => popout.showModal();
  popout.addEventListener('close', () => trigger.focus({preventScroll:true}));
  trigger.setAttribute('aria-label', `Same-line sportsbook quotes for ${outcome}`);
  cell.append(trigger, popout);
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
  if (group.game_identity_status) description.append(el('small', 'Source listing · game identity unverified'));
  header.append(description);
  if (result) header.append(result);
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
  if (offer.posted_price) item.title = quoteFreshness(offer, context.mode, true);
  if (offer.desk_quote_key) item.dataset.deskQuoteKey = offer.desk_quote_key;
  const reason = quoteReason(offer);
  const freshness = (context.mode || offer.posted_price) && quoteFreshness(offer, context.mode);
  const calculation = reason || `${percent(offer.value)} ${basisName(context.basis) || 'return'}`;
  const description = [label, context.position(offer), offer.odds?.american].filter(Boolean).join(', ');
  item.setAttribute('aria-label', [description, freshness, showResult && offer.current && calculation, 'Quote details'].filter(Boolean).join(', '));
  if (showResult) item.append(el('span', label, 'desk-site'));
  const price = el('span', null, 'quote-price');
  price.append(odd(offer.odds));
  item.append(price);
  if (freshness) item.append(el('small', freshness, 'quote-freshness'));
  if (showResult && offer.current) {
    const result = el('small', calculation, reason ? 'offer-reason' : tone(offer.value));
    item.append(result);
  }
  return item;
}

export function evCard(group, context) {
  if (group.offers[0]?.valuation_summary) {
    const lead = group.offers[0];
    const summary = lead.valuation_summary;
    const row = el('article', null, 'opportunity-card');
    row.dataset.groupId = group.id;
    row.append(cardHeader(group, context.position(lead), group.game_title,
      score(group.score, `${venueLabel(lead)} · Net EV`), context.clock));
    row.append(el('p', `Opportunity Score ${summary.display.opportunity_score} · After-fee odds ${summary.display.after_fee_odds}`, 'desk-meta'));
    if (summary.evidence_class === 'fixture') row.append(el('p', 'Fixture data', 'desk-meta'));
    const inspect = button('View EV calculation ↗', event => context.inspectOffer(lead, group, event.currentTarget), 'opportunity-link');
    inspect.dataset.calculationId = lead.id;
    row.append(cardActions(group, context, inspect));
    return row;
  }
  if (context.compact) return compactEV(group, context);
  const lead = group.offers[0];
  const row = el('article', null, 'opportunity-card');
  row.dataset.groupId = group.id;
  const leadScore = score(group.score, group.score == null ? 'Missing calculation inputs' : `${venueLabel(lead)} · ${basisName(context.basis)}`);
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
  if (group.line_role === 'unknown') market.append(el('small', 'Main line unverified', 'desk-meta'));
  if (group.game_identity_status) market.append(el('small', 'Source listing · game identity unverified', 'desk-meta'));
  const quotes = el('div', null, 'compact-prices');
  quotes.setAttribute('role', 'group');
  quotes.setAttribute('aria-label', 'Prediction market offers');
  const seen = new Set();
  // The server orders offers by the applicable exact EV basis.
  for (const offer of group.offers) {
    if (!offer.odds?.american || seen.has(offer.venue)
      || (context.selectedVenues && !context.selectedVenues.includes(offer.venue))) continue;
    seen.add(offer.venue);
    const label = compactBasisLabels[offer.value_basis || context.basis] || 'Return';
    const value = offer.current ? offer.value ?? (offer === lead ? group.score : null) : null;
    const price = quote(offer, group, context, offer === lead && value != null ? 'desk-best' : '', false);
    price.prepend(el('span', venueLabel(offer), 'compact-venue'));
    price.dataset.calculationId = offer.id;
    const accessible = `View trade details: ${venueLabel(offer)}, ${context.position(offer)}, ${offer.odds.american}`;
    price.setAttribute('aria-label', [accessible, value != null && `${percent(value)} ${label}`,
      quoteFreshness(offer, context.mode)].filter(Boolean).join(', '));
    if (value != null) {
      const ev = el('strong', percent(value), `compact-ev-return ${tone(value)}`);
      ev.title = basisName(offer.value_basis || context.basis) || label;
      price.append(ev, el('small', label, 'compact-ev-basis'));
    }
    quotes.append(price);
  }
  if (!seen.size && context.selectedVenues) quotes.append(el('small', 'No quote from selected sites', 'desk-meta'));
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
  const unavailable = group.score == null && lead.current && quoteReason(lead);
  if (fair) {
    const fairValue = el('span', 'Fair odds ', 'compact-fair');
    fairValue.append(odd(fair));
    row.append(fairValue);
  }
  if (unavailable) row.append(el('span', `EV unavailable · ${unavailable}`, 'compact-ev-gap'));

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
    if (comparison && exact) item.append(el('small', 'Used for fair odds'));
    else if (context.mode && quote?.current === false) item.append(el('small', 'Last known'));
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
  row.append(cardHeader(group, group.game_title, context.mode || '',
    net?.available ? score(group.score, 'Lowest modeled return') : null, context.clock));
  const content = el('ul', null, 'arb-card-legs');
  for (const [index, leg] of legs.entries()) {
    const item = el('li', null, leg.current ? 'desk-best' : '');
    item.append(el('span', context.position(leg)), el('small', venueLabel(leg)), odd(leg.odds));
    const sizing = pairLegSize(best, index);
    if (sizing.length) item.append(ticketFacts(sizing, 'arb-leg-sizing'));
    if (leg.posted_price || !leg.current && context.mode) {
      item.append(el('small', quoteFreshness(leg, context.mode), 'quote-freshness'));
    }
    content.append(item);
  }
  const inspectPair = (pair, label, showScore = false) => {
    const inspect = button(label, event => context.inspectPair(pair, offers, group, event.currentTarget), 'opportunity-link');
    inspect.dataset.pairId = pair.id;
    if (showScore && pair.score != null) {
      const result = el('span', ` · ${percent(pair.score)}`);
      inspect.append(result);
    }
    return inspect;
  };
  row.append(content, pairPayoff(best));
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
    && (group.line_role || context.compact || group.id === selectedLine || includeAlternates
      || group.offers.some(offer => offer.alternate !== true)));
  const box = el('section', null, 'odds-card');
  const linked = visible[0] || groups[0];
  if (linked) {
    box.dataset.gameKey = linked.game_key;
    if (linked.source_event) box.dataset.sourceEvent = linked.source_event;
  }
  let actions;
  if (context.gameTitle || context.showGameLink) {
    const header = el('header');
    const description = el('div', null, 'odds-occurrence');
    description.append(el('h2', context.gameTitle || 'Markets'));
    if (context.occurrenceLabel) description.append(el('p', context.occurrenceLabel, 'desk-meta'));
    if (context.identityNote) description.append(el('p', context.identityNote, 'desk-note'));
    header.append(description);
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
    const outcome = context.position(lead);
    side.append(el('span', outcome, 'matrix-outcome'));
    if (group.line_role === 'unknown') side.append(el('small', 'Main line unverified', 'desk-meta'));
    const period = group.market.period === 'full_game' ? 'Full game' : name(group.market.period);
    if (!context.compact || group.market.period !== 'full_game') side.append(el('small', `${name(group.market.market)} · ${period}`));
    if (group.id === selectedLine) {
      tr.classList.add('selected-game-line');
      tr.setAttribute('aria-current', 'true');
    }
    if (settlementLabel(group) && !context.compact) side.append(el('small', settlementLabel(group)));
    appendSportsbookTrigger(side, group, context);
    if (context.lineLink) side.append(context.lineLink(group));
    tr.append(side);
    let hasQuote = false;
    for (const [venue] of columns) {
      const cell = tr.insertCell();
      for (const offer of group.offers.filter(candidate => venueKey(candidate) === venue
        && (!context.compact || candidate.odds?.american)
        && (group.line_role || context.compact || group.id === selectedLine || includeAlternates || candidate.alternate !== true))) {
        const price = quote(offer, group, context, offer.current && offer.best_payout ? 'desk-best' : '', false);
        if (context.summary && offer.current && offer.value != null) {
          const label = percent(offer.value);
          price.dataset.calculationId = offer.id;
          const value = el('small', `${label} ${matrixBasisLabels[offer.value_basis || context.basis] || 'return'}`, tone(offer.value));
          price.append(value);
          price.setAttribute('aria-label', `${price.getAttribute('aria-label')}, ${label} ${basisName(context.basis) || 'return'}`);
        } else if (context.summary && offer.current) {
          const gap = el('small', 'EV unavailable', 'offer-reason');
          gap.title = quoteReason(offer);
          price.append(gap);
        }
        cell.append(price);
        quotedVenues.add(venue);
        hasQuote = true;
      }
      if (!cell.hasChildNodes()) noQuote(cell, name(venue), !context.summary && group.retained_venues?.includes(venue),
        context.explainQuoteGap, outcome);
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
      else calculation.append(el('span', result));
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
