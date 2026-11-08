// The server owns the exact inputs and cashflows. Formatting happens here.
const {el, num, fmt, odd, name, button} = window.PredictUI;
const percent = value => value == null ? 'Unavailable' : `${fmt(value)}%`;
const probability = value => value == null ? 'Unavailable' : percent(num(value) * 100);
const usd = value => value == null ? 'Unavailable' : new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits: 6
}).format(num(value));
const number = value => value == null ? 'Unavailable' : fmt(value);
const reasonLabels = {
  finance_pending: 'Calculation was still pending when this result was captured.',
  source_expired: 'The source price or reference had expired at capture.',
  source_unknown: 'The source did not provide enough timing evidence.',
  comparison_scoring_scope_missing: 'The full scoring and settlement rules are unverified for cross-site pairing.',
  exact_reference_pair_unavailable: 'An exact two-sided Pinnacle match is missing.',
  reference_probability_unavailable: 'A supported Pinnacle probability is missing.',
  supported_decisive_benchmark_required: 'A supported decisive benchmark is missing.',
  source_price_or_selection_unsupported: 'The price or the exact outcome could not be verified.',
  polymarket_account_taker_fee_tier_unbound: 'The account taker coefficient and its effective dates are missing.',
  kalshi_account_membership_unbound: 'The account channel, membership and applicable charges are missing.',
  prophetx_account_fee_model_and_rate_unbound: 'The account fee agreement, rate and assessment basis are missing.',
  conditional_fee_review_expired_or_not_effective: 'The fee review does not cover this capture time.',
  conditional_pregame_ended: 'The reviewed pregame model ended at kickoff.',
  live_financial_model_unverified: 'A qualified live model and current in-game reference are required.',
  conservative_trade_fee_estimate_not_applicable: 'There is no conservative fee model for this site.',
  synthetic_account_terms_unavailable: 'This example has fictional fees only. See the modeled scenario below.',
  synthetic_public_schedule_unavailable: 'This example uses no public fee schedule.'
};
const human = value => String(value).replaceAll('_', ' ');
const reasons = value => String(value || 'Details unavailable').split(', ').map(code => reasonLabels[code] || human(code)).join(' ');

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
  for (const [title, value] of [['Offered odds', odd(offer.odds)], ['Before fees', percent(offer.before_fee)],
    ['Reviewed fees', percent(offer.after_fee)], ['Conservative fees', percent(offer.conservative)]]) {
    const tile = el('div');
    const total = el('strong'); total.append(value);
    tile.append(el('small', title), total); tiles.append(tile);
  }
  result.append(tiles);
  if (offer.reason) result.append(el('p', offer.reason, 'inspection-gap'));
  if (!evidence?.inspection) {
    result.append(el('p', 'Loading the pinned calculation…', 'desk-meta inspection-loading'));
    return result;
  }
  const data = evidence.inspection;
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
    reference.append(el('p', reasons(data.identity.probability_reason || data.identity.reference_reason || ref.reason || 'exact_reference_pair_unavailable'), 'inspection-gap'));
  }
  result.append(reference, section('Before-fee cashflows', facts([
    ['Normal winning payout', usd(gross.win_receipt_usd)], ['Profit if it wins', usd(gross.win_profit_usd)],
    ['Profit if it loses', usd(gross.loss_profit_usd)], ['Expected profit per claim', usd(gross.expected_profit_usd)],
    ['Risk per claim', usd(gross.risk_usd)], ['Return on risk', percent(gross.return_percent)]
  ]), el('p', 'Expected profit = fair chance × win profit + losing chance × loss profit. Return = expected profit ÷ risk.', 'inspection-formula')),
  fee('Reviewed trade fees', data.reviewed, data.starting_fee_terms), fee('Conservative fee estimate', data.conservative));
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
  const list = el('ul'); gaps.forEach(gap => list.append(el('li', human(gap))));
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
  math.legs.forEach((leg, index) => {
    const offer = offers.get(pair.legs[index]);
    result.append(section(`${name(offer.venue)} · ${position(offer, game)}`, facts([
      ['Offered odds', odd(offer.odds)], ['Cost per $1 claim', usd(leg.cost_per_claim)],
      ['Stake', usd(leg.allocation_usd)], ['Payout if this leg wins', usd(leg.win_receipt_usd)],
      ['Combined profit if this leg wins', usd(leg.win_profit_usd)]
    ]), button('Inspect offer and fees', () => inspect(offer), 'desk-action')));
  });
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
  const missing = el('ul'); math.missing.forEach(item => missing.append(el('li', item)));
  result.append(section('Still needed for a net pair', missing));
  return result;
}
