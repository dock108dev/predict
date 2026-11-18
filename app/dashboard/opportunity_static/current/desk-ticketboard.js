import {quoteFreshness} from './desk-quote-display.js';

const {el, name, odd, button} = window.PredictUI;
const dollars = new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'});
const wholeDollars = new Intl.NumberFormat('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0});
export function unitLabel(value) {
  const amount = Number(value);
  return (Number.isInteger(amount) ? wholeDollars : dollars).format(amount);
}
export const conditioningLabel = value => ({if_no_draw:'if no draw', if_no_push:'if no push',
  if_decisive_completed_game:'for a decisive completed game'})[value];

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
  compare.dataset.memberId = offer.evidence_result_id;
  if (offer.desk_quote_key) compare.dataset.deskQuoteKey = offer.desk_quote_key;
  compare.setAttribute('aria-label', `Compare prices for ${label}, ${group.game_title}`);
  compare.setAttribute('aria-haspopup', 'dialog');
  stub.append(metric, compare);
  card.append(bet, pricing, stub);
  return card;
}
