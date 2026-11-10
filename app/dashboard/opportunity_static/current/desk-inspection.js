import {evidenceReason as reasons} from './desk-reasons.js';
import {pinnedInspection} from './desk-evidence.js';
// The server owns the exact inputs and cashflows. Formatting happens here.
const {el, num, fmt, odd, name, button} = window.PredictUI;
const percent = value => value == null ? 'Unavailable' : `${fmt(value)}%`;
const probability = value => value == null ? 'Unavailable' : percent(num(value) * 100);
const usd = value => value == null ? 'Unavailable' : new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits: 6
}).format(num(value));
const number = value => value == null ? 'Unavailable' : fmt(value);
const human = value => String(value).replaceAll('_', ' ');

function facts(entries) {
  const list = el('dl', null, 'inspection-facts');
  for (const [label, value] of entries) {
    const detail = el('dd');
    detail.append(value instanceof Node ? value : value == null || value === '' ? 'Unavailable' : String(value));
    list.append(el('dt', label), detail);
  }
  return list;
}

function section(title, ...content) {
  const result = el('section', null, 'inspection-section');
  result.append(el('h3', title), ...content);
  return result;
}

function disclosure(title, ...content) {
  const result = el('details', null, 'inspection-disclosure');
  result.append(el('summary', title), ...content);
  return result;
}

function fee(title, model, startingTerms) {
  model ||= {};
  const block = section(title);
  if (startingTerms) {
    const starting = el('div', null, 'inspection-formula');
    starting.append(el('strong', 'Starting fee terms'), facts(startingTerms.values), el('p', startingTerms.scope));
    if (startingTerms.in_review_window === false) {
      starting.append(el('p', 'This capture falls outside the recorded fee review window.', 'desk-meta'));
    }
    block.append(starting);
  }
  if (model.available) {
    block.append(facts([
      ['Trade fee', usd(model.trade_fee_usd)], ['Fee treatment', human(model.fee_payment || 'Upfront modeled trade fee')],
      ...(model.expected_trade_fee_usd != null ? [['Expected fee', usd(model.expected_trade_fee_usd)]] : []),
      ['Risk', usd(model.normalization_risk_usd)], ['Profit if it wins', usd(model.win_profit_usd)],
      ['Profit if it loses', usd(model.loss_profit_usd)], ['Expected profit', usd(model.scenario_net_usd)],
      ['Return on risk', percent(model.return_percent)], ['Model size', `${model.quantity} ${model.quantity_unit} · ${model.fill_count} fill · ${model.liquidity_role}`]
    ]));
  } else {
    const unavailable = el('p', null, 'inspection-gap');
    unavailable.append(el('strong', 'Missing for this offer'), ' · ', reasons(model.reason));
    block.append(unavailable);
    if (model.detail) block.append(el('p', reasons(model.detail), 'desk-meta'));
    if (model.required_evidence) block.append(el('p', model.required_evidence, 'desk-meta'));
  }
  if (model.fee_scenarios?.length) {
    block.append(disclosure('Fee scenarios by account type', facts(model.fee_scenarios.map(scenario => [
      human(scenario.membership), `${usd(scenario.fee)} fee · ${usd(scenario.risk)} risk · ${percent(scenario.return_percent)} return`
    ]))));
  }
  const notes = [model.condition, model.formula, ...(model.assumptions || []),
    ...(model.exclusions?.length ? [`Outside this model: ${model.exclusions.join(', ')}.`] : [])].filter(Boolean);
  if (model.evidence || notes.length) {
    const source = model.evidence || {};
    block.append(disclosure('Fee basis and assumptions', ...notes.map(note => el('p', note)), facts([
      ['Schedule or review', source.version], ['Reviewed at', source.reviewed_at],
      ['Review ends', source.review_before], ['Instrument', source.series_id || source.event_id],
      ...(source.fee_rate != null ? [['Schedule coefficient', source.fee_rate]] : [])
    ])));
  }
  return block;
}

const feeClasses = {
  exact_public: 'Verified public fee',
  conservative: 'Conservative estimate',
  account_reviewed: 'Reviewed account fee',
  partial: 'Partial evidence',
  unknown: 'Unknown'
};

export function tradingFeeLabel(model) {
  if (!model.available) return 'Trading fee unavailable';
  const timing = model.fee_cashflows?.winning_settlement_usd != null ? ' at settlement if it wins' : ' at fill';
  return `Trading fee ${usd(model.trade_fee_usd)}${timing} · ${feeClasses[model.classification]}`;
}

export function tradingFeeSize(model) {
  const unit = model.quantity_unit === 'USD normal claim' || model.quantity_unit === 'USD payout contracts'
    ? `$1-payout contract${num(model.quantity) === 1 ? '' : 's'}` : model.quantity_unit;
  return `${model.quantity} ${unit} · ${model.fill_count} immediate taker fill${model.fill_count === 1 ? '' : 's'}`;
}

function tradingFee(model) {
  const block = section('Trading fee');
  if (model.available) {
    const timing = model.fee_cashflows?.winning_settlement_usd != null ? 'Winning settlement' : 'At fill';
    block.append(facts([
      ['Trading fee', usd(model.trade_fee_usd)], ['Evidence class', feeClasses[model.classification]],
      ['Trade profile', 'Manual retail'], ['Modeled size', tradingFeeSize(model)],
      ['Fee timing', timing], ['Holding assumption', model.holding_assumption]
    ]), ...model.assumptions.map(note => el('p', note, 'desk-meta')));
    if (timing === 'Winning settlement') {
      block.append(facts([['Fee at fill', usd(model.fee_cashflows.at_fill_usd)],
        ['Fee if it loses', usd(model.fee_cashflows.losing_settlement_usd)]]));
    }
  } else {
    block.append(el('p', tradingFeeLabel(model), 'inspection-gap'),
      el('p', reasons(model.reason), 'desk-meta'));
  }
  if (model.evidence) {
    const source = model.evidence;
    const terms = el('a', 'Official fee schedule');
    terms.href = source.source_url;
    terms.target = '_blank';
    terms.rel = 'noopener noreferrer';
    block.append(disclosure('Trading fee evidence', facts([
      ['Source', terms], ['Schedule review', source.version], ['Reviewed at', source.reviewed_at],
      ['Review ends', source.review_before],
      ...(source.order_inserted_at ? [['Modeled order insertion', source.order_inserted_at],
        ['Taker coefficient', source.coefficient], ['Acquired-side price', '$' + source.acquired_price_usd],
        ['Offer phase', source.phase === 'live' ? 'In-game' : 'Pregame']] : []),
      ...(source.published_version ? [['Published version', source.published_version],
        ['Published effective time', source.published_effective_from || 'None published'],
        ['Authority begins', source.effective_from], ['Schedule SHA-256', source.sha256]] : []),
      ['Scope', source.applicability]
    ])));
  }
  return block;
}

function settlement(data, venue) {
  const block = section(`${name(venue)} rules and outcomes`);
  const scoring = Object.entries(data.scoring).filter(([key, value]) =>
    key !== 'score_domain' && !['not_applicable', 'unknown'].includes(value));
  if (scoring.length) {
    block.append(facts(scoring.map(([key, value]) => [human(key).replace(/^./, char => char.toUpperCase()), human(value)])));
  }
  block.append(el('p', 'Payout and profit before fees per $1 of normal winning payout.', 'desk-meta'));
  block.append(facts(data.outcomes.map(outcome => {
    const description = el('div');
    if (outcome.payout_usd != null) {
      description.append(`${usd(outcome.payout_usd)} payout · ${usd(outcome.profit_usd)} profit`);
    }
    if (outcome.note) description.append(el('div', outcome.note, 'desk-meta'));
    return [outcome.label, description.hasChildNodes() ? description : null];
  })));
  if (data.equality_can_affect_ev) {
    block.append(el('p', 'A tie or exact-line outcome can change expected profit. To include it in EV, we need its probability. The displayed EV covers decisive win and loss only.', 'inspection-formula'));
  }
  if (data.wording.length) {
    block.append(disclosure('Book’s saved rule text', ...data.wording.map(rule => {
      const part = el('div');
      part.append(el('strong', rule.excerpt ? `${rule.label} excerpt` : rule.label), el('p', rule.text));
      return part;
    })));
  } else if (!data.fictional) {
    block.append(el('p', 'This capture did not include the book’s exact market rule text.', 'inspection-gap'));
  }
  return block;
}

export function tradeInspection(offer, group, evidence, {mode, position}) {
  const result = document.createDocumentFragment();
  result.append(el('p', group.game_title, 'inspection-matchup'));
  if (mode) result.append(el('p', mode, 'inspection-mode'));
  const tiles = el('div', null, 'inspection-tiles');
  for (const [title, value] of [['Offered odds', odd(offer.odds)], ['Before-fee EV', percent(offer.before_fee)],
    ['Reviewed-fee EV', percent(offer.after_fee)], ['Conservative EV', percent(offer.conservative)]]) {
    const tile = el('div');
    const total = el('strong'); total.append(value);
    tile.append(el('small', title), total); tiles.append(tile);
  }
  result.append(tiles);
  if (offer.trade_fee) result.append(tradingFee(offer.trade_fee));
  if (offer.reason) result.append(el('p', reasons(offer.reason), 'inspection-gap'));
  if (!evidence?.inspection) {
    result.append(el('p', 'Loading the pinned calculation…', 'desk-meta inspection-loading'));
    return result;
  }
  const data = pinnedInspection(offer, evidence.inspection);
  const original = data.original || {};
  const ref = data.fair_reference;
  const gross = data.before_fees;
  result.append(el('p', `Math at capture · ${evidence.captured_at || offer.captured_at}`, 'desk-meta'));
  result.append(section('Price and outcome', facts([
    ['Selected outcome', position], ['Market', [name(offer.market.market), human(offer.market.period)].join(' · ')],
    ['Native side', data.source?.native_side && human(data.source.native_side)], ['Original price', original.value == null ? null : `${original.value} ${human(original.units)}`],
    ['Cost per $1 normal claim', usd(gross.cost_usd)], ['Cross-site settlement match', data.identity.outcome?.supported ? 'Supported' : reasons(data.identity.outcome?.reason || 'Exact settlement evidence missing')]
  ])));
  if (data.settlement) result.append(settlement(data.settlement, offer.venue));
  const reference = section('Pinnacle reference');
  if (ref.available) {
    reference.append(facts([
      ...ref.pair.map((leg, index) => [index === ref.selected ? 'Selected price' : 'Opposite price',
        `${leg.selection?.label || human(leg.selection?.predicate || 'Outcome')} · ${leg.original.value} decimal · ${probability(ref.implied_probabilities[index])} implied`]),
      ['Book margin', probability(ref.overround)], ['Fair probability', probability(ref.probability)],
      ['Fair decimal odds', number(ref.fair_decimal_odds)]
    ]), el('p', 'Fair probability = selected implied probability ÷ sum of the two implied probabilities.', 'inspection-formula'),
    el('p', ref.conditioning, 'desk-meta'));
  } else {
    reference.append(el('p', reasons(ref.reason || data.identity.probability_reason || data.identity.reference_reason || 'exact_reference_pair_unavailable'), 'inspection-gap'));
  }
  result.append(reference, section('Before-fee cashflows', facts([
    ['Normal winning payout', usd(gross.win_receipt_usd)], ['Profit if it wins', usd(gross.win_profit_usd)],
    ['Profit if it loses', usd(gross.loss_profit_usd)], ['Expected profit per claim', usd(gross.expected_profit_usd)],
    ['Risk per claim', usd(gross.risk_usd)], ['Return on risk', percent(gross.return_percent)]
  ]), el('p', 'Expected profit = fair chance × win profit + losing chance × loss profit. Return = expected profit ÷ risk.', 'inspection-formula')),
  fee('EV with reviewed trading fees', data.reviewed, data.starting_fee_terms), fee('EV with conservative fees', data.conservative));
  const model = data.assumed_scenario || {};
  const scenario = section('Full net EV and execution');
  if (model.available) {
    scenario.append(facts([
      ['Assumed quantity', number(model.quantity_per_leg)], ['Expected profit after assumed fees', usd(model.fee_adjusted_expected_profit_usd)],
      ['Expected profit after buffer', usd(model.buffered_profit_usd)], ['Modeled return', percent(model.buffered_return_percent)],
      ...Object.entries(model.scenario_profits_usd || {}).map(([key, value]) => [human(key), usd(value)])
    ]), el('p', model.meaning, 'desk-meta'));
  }
  const gaps = [...new Set([...(model.missing || []), ...(data.reviewed?.missing || []),
    'Full outcome probabilities for pushes, ties and voids', 'Executable size and account-specific costs'])];
  const list = el('ul'); gaps.forEach(gap => list.append(el('li', gap.includes('_') ? reasons(gap) : gap)));
  scenario.append(el('p', 'Still needed to establish full economics', 'desk-meta'), list); result.append(scenario);
  const clocks = disclosure('Source evidence and clocks', facts([
    ['Source event', group.source_titles?.join(' · ')], ['Source update', offer.source_clock_at],
    ['Book confirmation', offer.confirmed_at], ['Local receipt', offer.received_at], ['Capture', offer.captured_at],
    ['Game state', `${offer.game_state} · ${human(offer.game_state_basis || 'No explicit source state')}`],
    ['Source event ID', data.source?.native_event_id], ['Source market ID', data.source?.native_market_id],
    ['Source outcome ID', data.source?.native_outcome_id]
  ]));
  const raw = disclosure('Raw calculation evidence');
  raw.addEventListener('toggle', () => { if (raw.open && raw.children.length === 1) raw.append(el('pre', JSON.stringify(evidence, null, 2))); });
  result.append(clocks, raw);
  return result;
}

export function pairInspection(pair, offers, {group, game, position, inspect, mode}) {
  const result = document.createDocumentFragment();
  const math = pair.inspection;
  result.append(el('p', group.game_title, 'inspection-matchup'));
  if (mode) result.append(el('p', mode, 'inspection-mode'));
  result.append(section('Before-fee payoff', facts([
    ['Total funding', usd(math.funding_usd)], ['Ideal equal payout', usd(math.ideal_payout_usd)],
    ['Ideal profit', usd(math.ideal_profit_usd)], ['Lower profit after cent allocation', usd(math.minimum_profit_usd)],
    ['Return on rounded funding', percent(math.rounded_return_percent)]
  ]), el('p', math.rounding, 'inspection-formula')));
  const retail = pair.retail_payoff;
  math.legs.forEach((leg, index) => {
    const offer = offers.get(pair.legs[index]);
    const charge = retail?.legs[index];
    result.append(section(`${name(offer.venue)} · ${position(offer, game)}`, facts([
      ['Offered odds', odd(offer.odds)], ['Cost per $1 claim', usd(leg.cost_per_claim)],
      ['Cent-rounded stake', usd(leg.allocation_usd)], ['Payout if this leg wins', usd(leg.win_receipt_usd)],
      ...(charge?.available ? [['Modeled $1 claims', charge.quantity], ['Fee at fill', usd(charge.at_fill_usd)],
        ...Object.entries(charge.settlement_usd).map(([state, fee]) => [`Settlement fee · ${pairState(state)}`, usd(fee)]),
        ['Fee evidence', feeClasses[charge.classification]]] :
        [['Fee at this stake', reasons(charge?.reason || retail?.reason || 'pair_fee_size_unverified')]]),
      ['Combined profit if this leg wins', usd(leg.win_profit_usd)]
    ]), button('Inspect offer and fees', () => inspect(offer), 'desk-action')));
  });
  const net = section('Net settlement after retail fees');
  if (retail?.available) {
    net.append(facts([['Total funding including fill fees', usd(retail.funding_usd)],
      ...Object.entries(retail.states).map(([state, values]) => [pairState(state),
        `${usd(values.net_receipt_usd)} net payout · ${usd(values.net_profit_usd)} net profit`])]),
      el('p', 'Completed-game outcomes at the captured prices and shown stakes. Fill fees are paid in addition to the stakes. Execution, voids and cancellations are outside this model.', 'desk-meta'));
  } else net.append(el('p', reasons(retail?.reason || 'pair_settlement_unverified'), 'inspection-gap'));
  result.append(net);
  const scenario = pair.assumed_scenario;
  if (scenario?.available) {
    result.append(section('Modeled pair with assumed fees', facts([
      ['Scenario funding', usd(scenario.deployed_capital_usd)],
      ['First leg upfront fee', usd(scenario.upfront_fees_usd?.[0])],
      ['Second leg upfront fee', usd(scenario.upfront_fees_usd?.[1])],
      ['Lowest profit after fees and buffer', usd(scenario.scenario_minimum_usd)],
      ['Lowest return after fees and buffer', percent(scenario.scenario_minimum_percent)]
    ]), el('p', 'This scenario uses configured fractional sizing and its own funding amount.', 'desk-meta')));
  }
  return result;
}

const pairState = state => ({first_wins:'First leg wins', second_wins:'Second leg wins', equality:'Exact line settlement'})[state];
