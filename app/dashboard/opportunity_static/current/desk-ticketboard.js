import {evidenceReason} from './desk-reasons.js';
import {quoteFreshness} from './desk-quote-display.js';

const {el, name, odd, button, num} = window.PredictUI;
const $ = id => document.getElementById(id);
const unitKey = 'unit-usd';
const dollars = new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'});
const wholeDollars = new Intl.NumberFormat('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0});
export function unitLabel(value) {
  const amount = Number(value);
  return (Number.isInteger(amount) ? wholeDollars : dollars).format(amount);
}
export const conditioningLabel = value => ({if_no_draw:'if no draw', if_no_push:'if no push',
  if_decisive_completed_game:'for a decisive completed game'})[value];

// The service validates these same dollar bounds and decimal places.
function validUnit(value) {
  return /^[0-9]{1,7}(?:\.[0-9]{1,2})?$/.test(value) && Number(value) > 0 &&
    Number(value) <= 1_000_000 ? Number(value).toFixed(2) : '';
}

export function createUnitPicker({readPreference, savePreference, changed}) {
  const select = $('board-unit');
  const custom = $('custom-unit');
  const editor = $('custom-unit-field');
  const customOption = select.querySelector('[value="custom"]');
  const savedOption = el('option');
  let amount;

  function showAmount() {
    savedOption.remove();
    const preset = [...select.options].some(option => option.value === amount);
    if (!preset) {
      savedOption.value = amount;
      savedOption.textContent = unitLabel(amount);
      customOption.before(savedOption);
    }
    select.value = amount;
    custom.setCustomValidity('');
    editor.hidden = true;
  }

  function restore() {
    amount = '100.00';
    showAmount();
  }

  function commit(value) {
    const prior = amount;
    savePreference(unitKey, value);
    // Apply the current choice even if device storage is unavailable.
    amount = value;
    showAmount();
    if (prior !== amount) changed();
  }

  select.addEventListener('change', () => {
    if (select.value === 'custom') {
      editor.hidden = false;
      custom.value = amount ? String(Number(amount)) : '';
      custom.focus();
    } else {
      custom.setCustomValidity('');
      commit(select.value);
    }
  });
  const applyCustom = () => {
    const value = validUnit(custom.value.trim());
    custom.setCustomValidity(value ? '' : 'Enter $0.01 to $1,000,000 with up to two decimal places.');
    if (!custom.reportValidity()) return;
    select.focus();
    commit(value);
  };
  custom.addEventListener('input', () => custom.setCustomValidity(''));
  custom.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      applyCustom();
    } else if (event.key === 'Escape') {
      showAmount();
      select.focus();
    }
  });
  $('apply-unit').onclick = applyCustom;
  restore();
  return {value:() => amount, restore};
}

export function ticketFacts(entries, className) {
  const list = el('dl', null, className);
  for (const [label, value] of entries) {
    const cell = el('div');
    const detail = el('dd');
    detail.append(value ?? 'Unavailable');
    cell.append(el('dt', label), detail);
    list.append(cell);
  }
  return list;
}

export function modeledOdds(display = {}, raw = {}, blended = false) {
  const american = blended ? display.blended_offer : display.after_fee_odds;
  const decimal = blended ? raw.blended_decimal : raw.after_fee_decimal;
  return american || decimal ? odd({american:american ?? display.after_fee_decimal, decimal}) : 'Unavailable';
}

export function ticketCard(group, {position, clock, inspectOffer}) {
  const offer = group.offers[0];
  const label = position(offer);
  const model = offer.valuation_summary;
  const {display, raw, reference} = model;
  const card = el('article', null, 'pregame-ticket');
  card.dataset.groupId = group.id;
  card.dataset.gameKey = group.game_key;
  const bet = el('div', null, 'ticket-bet');
  bet.append(el('p', `${group.league} · ${clock(group.start_at)}`, 'ticket-time'),
    el('h3', label), el('p', group.game_title, 'ticket-matchup'));
  if (model.evidence_class === 'fixture') {
    bet.append(el('small', offer.practice_ticket ? `Simulated offer · ${unitLabel(offer.unit_usd)} unit` : 'Simulated offer', 'ticket-context'));
  }
  const pricing = el('div', null, 'ticket-pricing');
  pricing.append(el('p', name(offer.venue), 'ticket-venue'));
  const prices = [['Posted odds', odd(offer.odds)], ['After-fee odds', modeledOdds(display, raw)]];
  if (display.blended_offer) prices.push(['Blended fill', modeledOdds(display, raw, true)]);
  if (reference) prices.push(['Fair odds', odd(reference.fair_odds)]);
  pricing.append(ticketFacts(prices, 'ticket-prices'));
  if (reference) {
    const condition = conditioningLabel(reference.conditioning);
    pricing.append(el('p', `Reference · ${name(reference.book)} ${reference.selected_price}`, 'ticket-context'));
    if (condition) pricing.append(el('p', `Fair odds ${condition}`, 'ticket-context'));
  }
  if (offer.quote_freshness === 'retained' || offer.quote_freshness === 'unknown') {
    pricing.append(el('p', quoteFreshness(offer, false), 'ticket-context'));
  }
  const stub = el('div', null, 'ticket-stub');
  const metric = ticketFacts([['Estimated Net EV', display.net_ev], ['Opportunity Score', display.opportunity_score]], 'ticket-metrics');
  const compare = button('Compare prices', () => inspectOffer(offer, group, compare), 'ticket-compare');
  compare.dataset.offerId = offer.id;
  compare.dataset.boardId = offer.board_id;
  compare.dataset.memberId = offer.evidence_result_id;
  if (offer.desk_quote_key) compare.dataset.deskQuoteKey = offer.desk_quote_key;
  compare.setAttribute('aria-label', `Compare prices for ${label}, ${group.game_title}`);
  compare.setAttribute('aria-haspopup', 'dialog');
  stub.append(metric, compare);
  card.append(bet, pricing, stub);
  return card;
}

export function ticketboardEmpty(page, {amount, retry, browseLink}) {
  const empty = el('section', null, 'ticketboard-empty');
  const hasQualified = (page.qualified_board_offer_count ?? page.qualified_offer_count) > 0;
  const title = {
    unit_needed:'Choose a unit size to rank offers after fees.',
    valuation_pending:`Calculating opportunities for ${unitLabel(amount)}`,
    read_failed:'Opportunities could not be loaded',
    ready:hasQualified ? 'No positive estimated Net EV offers at $100.'
      : 'No offers have an estimated Net EV at $100.'
  }[page.state] || 'Opportunities could not be loaded';
  empty.append(el('h2', page.pending_member_count ? 'Updating $100 estimates' : title));
  if (page.pending_member_count) empty.append(el('p', `${page.pending_member_count} groups are still being calculated. Completed results appear as they publish.`, 'desk-meta'));
  if (page.state === 'ready') empty.append(el('p', `${page.qualified_offer_count || 0} of ${page.matched_offer_count || 0} posted offers have an estimated Net EV.`, 'desk-meta'));
  if (page.state === 'ready' && !hasQualified) {
    const reasons = Object.entries(page.blocker_counts || {}).sort((a, b) => b[1] - a[1]);
    const labels = [...new Set(reasons.map(([reason]) => evidenceReason(reason)))].slice(0, 4);
    if (labels.length) {
      const list = el('ul');
      list.append(...labels.map(label => el('li', label)));
      empty.append(list);
    } else if (!page.matched_offer_count) {
      empty.append(el('p', 'There are no matching pregame prices on this board.'));
    }
  }
  const actions = el('div', null, 'desk-empty-actions');
  if (page.state === 'read_failed') {
    const reload = button('Retry', retry, 'desk-primary');
    reload.id = 'retry-board';
    actions.append(reload);
  }
  actions.append(browseLink);
  empty.append(actions);
  return empty;
}

export function sameBoardUnit(value, amount) {
  return amount ? value != null && num(value) === Number(amount) : value == null;
}
