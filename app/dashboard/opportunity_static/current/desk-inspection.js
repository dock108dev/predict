import {evidenceReason as reasons} from './desk-reasons.js';
import {pinnedInspection} from './desk-evidence.js';
import {basisName, priceStatus, selectedReference, settlementLabel, sportsbookQuotes, winPayout, percent as signedPercent, tone} from './opportunity-cards.js';
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

function feeAuthority(source) {
  return [
    ['Terms verified', source.reviewed_at],
    ...(source.review_before ? [['Applicable through', source.review_before]] : []),
    ...(source.standing_public_terms ? [
      ['Terms', source.verification_scope === 'market_terms_only'
        ? 'Standing public terms · market evidence verified · PDF recheck unavailable' : 'Standing public terms'],
      ['Recheck due', source.recheck_due_at]
    ] : [])
  ];
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
      ['Schedule or review', source.version], ...feeAuthority(source), ['Instrument', source.series_id || source.event_id],
      ...(source.fee_rate != null ? [['Schedule coefficient', source.fee_rate]] : [])
    ])));
  }
  return block;
}

const feeClasses = {
  exact_public: 'Verified public fee',
  conservative: 'Conservative estimate',
  account_reviewed: 'Reviewed account fee',
  synthetic: 'Fictional practice fee',
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
  return [
    model.quantity != null && unit && `${model.quantity} ${unit}`,
    model.fill_count != null && `${model.fill_count} immediate taker fill${model.fill_count === 1 ? '' : 's'}`
  ].filter(Boolean).join(' · ');
}

function tradingFee(model) {
  const block = section('Trading fee');
  if (model.available) {
    const fictional = model.classification === 'synthetic';
    const size = tradingFeeSize(model);
    const timing = model.fee_cashflows?.winning_settlement_usd != null ? 'Winning settlement' : 'At fill';
    block.append(facts([
      ['Trading fee', usd(model.trade_fee_usd)], ['Evidence class', feeClasses[model.classification]],
      ['Trade profile', fictional ? 'Synthetic practice' : 'Manual retail'],
      ...(fictional && model.evidence?.fictional_rate != null
        ? [['Fictional rate', `${percent(num(model.evidence.fictional_rate) * 100)} of the acquisition cost`]] : []),
      ...(size ? [['Modeled size', size]] : []),
      ['Fee timing', timing], ...(model.holding_assumption ? [['Holding assumption', model.holding_assumption]] : [])
    ]), ...(model.assumptions || []).map(note => el('p', note, 'desk-meta')));
    if (timing === 'Winning settlement') {
      block.append(facts([['Fee at fill', usd(model.fee_cashflows.at_fill_usd)],
        ['Fee if it loses', usd(model.fee_cashflows.losing_settlement_usd)]]));
    }
  } else {
    block.append(el('p', tradingFeeLabel(model), 'inspection-gap'),
      el('p', reasons(model.reason), 'desk-meta'));
  }
  if (model.evidence?.source_url) {
    const source = model.evidence;
    const terms = el('a', 'Official fee schedule');
    terms.href = source.source_url;
    terms.target = '_blank';
    terms.rel = 'noopener noreferrer';
    block.append(disclosure('Trading fee evidence', facts([
      ['Source', terms], ['Schedule review', source.version], ...feeAuthority(source),
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

function settlement(data, venue, aggregate) {
  const block = section(aggregate ? 'Illustrative outcomes · contract rules unverified' : `${name(venue)} rules and outcomes`);
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

function tiles(entries) {
  const list = el('div', null, 'inspection-tiles');
  for (const [label, value, style = ''] of entries) {
    const tile = el('div');
    const total = el('strong', null, style);
    total.append(value);
    tile.append(el('small', label), total);
    list.append(tile);
  }
  return list;
}

function sportsbookReference(reference) {
  const block = section('Comparison sportsbook');
  block.append(facts([
    ['Selected book', name(reference.book)],
    ['Selected odds', reference.prices?.[0]?.price_american],
    ['Opposite odds', reference.prices?.[1]?.price_american],
    ...(reference.fair_odds ? [['Estimated fair odds', odd(reference.fair_odds)]] : []),
    ['No-vig probability', probability(reference.probability)]
  ]));
  if (reference.indicative) {
    block.append(el('p', 'Pregame estimate based on a decisive win or loss. Fees, ties, pushes and voids are excluded.', 'desk-meta'));
  }
  const candidates = Object.entries(reference.candidates || {});
  if (candidates.length) {
    block.append(disclosure('Candidate book prices', facts(candidates.map(([book, prices]) => [
      name(book), prices.map(leg => leg.price_american).join(' / ')
    ]))));
  }
  return block;
}

function roundingTrace(trace) {
  const traceView = disclosure('Sized fee rounding');
  for (const [index, fill] of trace.entries()) {
    traceView.append(facts([
      ['Fill', String(index + 1)], ['Raw fee', fill.raw],
      ...[['amount','Rounded charge'], ['trade_fee','Trading fee'], ['rounding_fee','Rounding fee'],
        ['rounding_refund','Rounding refund'], ['accumulator','Rounding balance']].flatMap(([key, label]) =>
        fill[key] == null ? [] : [[label, fill[key]]])
    ]));
  }
  return traceView;
}

export function tradeInspection(offer, group, evidence, {mode, position, basis, checkedAt, pinned, pairLeg, pairFee, pairAcquisition}) {
  const result = document.createDocumentFragment();
  result.append(el('p', group.game_title, 'inspection-matchup'));
  if (mode) result.append(el('p', mode, 'inspection-mode'));
  const sportsbook = offer.sportsbook;
  const selectedRef = basis === 'sportsbooks' ? sportsbook : offer.reference_current && offer.reference_calculation;
  const cost = sportsbook?.cost ?? offer.cost_per_normal_claim ?? evidence?.inspection?.before_fees?.cost_usd;
  const quote = el('span');
  quote.append(odd(offer.odds));
  const priceFreshness = el('small', mode ? (offer.current ? 'At capture' : 'Last known at capture')
    : priceStatus(offer.current, offer.source_at || offer.source_clock_at, checkedAt, true), 'inspection-price-unit');
  priceFreshness.dataset.inspectionPrice = '1';
  quote.append(priceFreshness);
  if (cost != null) quote.append(el('small', `${usd(cost)} per $1 payout`, 'inspection-price-unit'));
  const activeFee = (offer.current || mode) && offer.trade_fee?.available ? offer.trade_fee.trade_fee_usd : null;
  const ev = el('span', signedPercent(offer.value), tone(offer.value));
  if (offer.value != null) {
    const evFreshness = el('small', mode ? 'At capture' : 'Current at inspection', 'inspection-price-unit');
    evFreshness.dataset.inspectionEv = '1';
    ev.append(evFreshness);
  }
  result.append(tiles([
    [offer.current ? 'Offered odds' : 'Last-known odds', quote],
    ...(!pairLeg ? [[basisName(basis) || 'EV result', ev]] : []),
    [offer.trade_fee?.classification === 'synthetic' ? 'Fictional trading fee' : 'Modeled trading fee', usd(activeFee)],
    ...(!pairLeg ? [['Fair win chance', probability(selectedRef?.probability ?? offer.probability)]] : [])
  ]));
  const tradeFee = offer.trade_fee;
  const estimated = tradeFee?.classification === 'conservative' ? 'Est. ' : '';
  const size = tradeFee?.available && tradingFeeSize(tradeFee);
  const fictionalRate = tradeFee?.classification === 'synthetic' ? tradeFee.evidence?.fictional_rate : null;
  const feeSummary = activeFee == null ? 'Fee unavailable'
    : fictionalRate != null ? `${percent(num(fictionalRate) * 100)} fictional fee on acquisition cost${size ? ' · ' + size : ''}`
      : `${estimated}${usd(activeFee)} fee${size ? ' for ' + size : ''}`;
  const summary = [feeSummary];
  if (!pairLeg && offer.value == null) {
    summary.push(`EV unavailable · ${reasons(offer.reason, 'No qualified same-line sportsbook pair.')}`);
  }
  result.append(el('p', summary.join(' · '), 'inspection-quote-status desk-meta'));
  if (pairFee?.available) {
    const modeled = pairFee.classification === 'synthetic' ? 'Fictional fee for this pairing' : 'Modeled fee for this pairing';
    const acquisition = pairAcquisition != null ? ` on ${usd(pairAcquisition)} of acquisition cost` : '';
    result.append(el('p', `${modeled} · ${usd(pairFee.at_fill_usd)} at fill${acquisition}.`, 'desk-meta'));
  }
  const comparison = [winPayout(offer), settlementLabel(group)].filter(Boolean);
  if (comparison.length) result.append(el('p', comparison.join(' · '), 'desk-meta'));
  if (offer.value != null) {
    const estimate = num(offer.value);
    result.append(el('p', `${usd(Math.abs(estimate))} average ${estimate < 0 ? 'loss' : 'profit'} per $100 risked under this model.`, 'desk-meta'));
  }
  if (group.sportsbook_quotes) {
    result.append(sportsbookQuotes(group, selectedReference(offer, basis), checkedAt, mode, true));
  }
  markPinned(result, pinned);
  if (selectedRef) {
    const book = selectedRef.contributors?.find(item => item.venue === selectedRef.venue) ?? selectedRef.contributors?.[0];
    if (sportsbook && basis === 'sportsbooks') result.append(sportsbookReference(sportsbook));
    else if (book) result.append(sportsbookReference({book:book.venue, prices:book.inputs,
      probability:selectedRef.probability, fair_odds:offer.reference,
      candidates:Object.fromEntries(selectedRef.contributors.map(item => [item.venue, item.inputs]))}));
  }
  if (!evidence?.inspection) {
    result.append(el('p', 'Loading the pinned calculation…', 'desk-meta inspection-loading'));
    return result;
  }
  const details = disclosure('Calculations and settlement');
  result.append(details);
  const data = pinnedInspection(offer, evidence.inspection);
  const original = data.original || {};
  const ref = data.fair_reference;
  const gross = data.before_fees;
  details.append(el('p', `Math at capture · ${evidence.captured_at || offer.captured_at}`, 'desk-meta'));
  details.append(section('Price and outcome', facts([
    ['Selected outcome', position], ['Market', [name(offer.market.market), human(offer.market.period)].join(' · ')],
    ['Price provider', data.source?.provider === 'oddslink_public_board' ? 'OddsLink' : data.source?.provider === 'sportsgameodds' ? 'SportsGameOdds' : data.source?.provider === 'practice' ? 'Synthetic practice' : null],
    ['Native side', data.source?.native_side && human(data.source.native_side)], ['Original price', original.value == null ? null : `${original.value} ${human(original.units)}`],
    ['Cost per $1 normal claim', usd(gross.cost_usd)],
    ['Venue outcome and settlement', data.identity.outcome?.supported ? 'Exact outcome identified'
      : reasons(data.identity.outcome?.reason || 'Exact settlement evidence missing')],
    ['Reference used for this result', basis === 'sportsbooks' && sportsbook
      ? 'Indicative sportsbook match by matchup, scheduled start and exact line'
      : ref.available ? (ref.contract ? 'Game link verified for this reference' : 'See the reference evidence below')
        : reasons(ref.reason || data.identity.reference_reason || 'exact_reference_pair_unavailable')]
  ])));
  if (offer.trade_fee) details.append(tradingFee(offer.trade_fee));
  if (sportsbook) details.append(section('Sportsbook de-vig', facts([
    ['Books with a current pair', sportsbook.candidate_books],
    ['Fair probability', probability(sportsbook.probability)],
    ['Offered price per $1 payout', usd(cost)],
    ['Estimated return before fees', signedPercent(sportsbook.return_percent)],
    ...sportsbook.prices.map((leg, index) => [index ? 'Opposite price and clock' : 'Selected price and clock', `${leg.price_american} American · ${leg.source_at}`])
  ]), el('p', 'Fair probability equals selected implied probability divided by the sum of both implied probabilities from the same book. Estimated return is 100 × (fair probability ÷ price per $1 payout − 1).', 'inspection-formula'),
    el('p', 'The estimate uses the full-game two-way result. Pushes, ties, voids and cancellations can settle differently across sites.', 'desk-meta')));
  const aggregatePrice = ['sportsgameodds', 'oddslink_public_board'].includes(data.source?.provider);
  const native = evidence.row?.sgo_native_contract;
  if (native?.available) {
    const rules = native.settlement;
    const block = section('Verified Novig contract', facts([
      ['Native market', native.market_id], ['Native outcome', native.outcome_id],
      ['Phase', native.phase_verified ? human(native.phase) : 'Current phase not confirmed for this price'],
      ...(rules?.available ? [
        ['Scoring', rules.extra_innings === 'included' ? 'Full game, including extra innings' : 'Full game, including overtime'],
        ...(rules.shootout === 'official_final_score' ? [['Shootout', 'Official final score']] : []),
        ['Equality', ({half_face: 'Recorded tie pays $0.50 per $1 claim',
          void_without_official_winner: 'Void if there is no official winner',
          not_possible: 'The final score cannot land on this half-point line'})[rules.equality]],
        ['Void', 'Fair market value · payout unavailable']
      ] : [['Settlement', 'Exact rules unreviewed']])
    ]));
    if (/^https:\/\/ludlow-filings\.s3\.us-east-1\.amazonaws\.com\/[A-Za-z0-9%._-]+\.pdf$/.test(rules?.source_url || '')) {
      const filing = el('a', 'Official contract terms');
      filing.href = rules.source_url;
      filing.target = '_blank';
      filing.rel = 'noopener noreferrer';
      const note = el('p');
      note.append(filing);
      block.append(note);
    }
    details.append(block);
  } else if (data.settlement) details.append(settlement(data.settlement, offer.venue, aggregatePrice));
  const reference = section(basis === 'sportsbooks' ? 'Separate qualified reference check' : 'Qualified reference');
  if (ref.available && ref.contributors?.length) {
    const method = ref.method === 'sgo-best-payout-proportional-1'
      ? `${name(ref.venue)} highest payout · same-book de-vig`
      : ref.contributors.length > 1 ? 'Median of qualified sportsbook pairs' : `${name(ref.venue)} price pair`;
    reference.append(facts([
      ['Method', method],
      ['Fair probability', probability(ref.probability)], ['Fair decimal odds', number(ref.fair_decimal_odds)],
      ['Maximum source age', `${ref.maximum_age_seconds} seconds`],
      ...ref.contributors.flatMap(book => book.inputs.map((leg, index) => [
        `${name(book.venue)} ${index === 0 ? 'selected' : 'opposite'}`,
        `${human(leg.side)}${leg.line == null ? '' : ' · '+leg.line} · ${leg.price_american} American · ${leg.source_at}`
      ]))
    ]), el('p', ref.conditioning, 'desk-meta'));
    const excluded = Object.entries(ref.exclusions || {});
    if (excluded.length) reference.append(disclosure('Other sportsbook checks', facts(excluded.map(([book, reason]) => [
      name(book), human(reason)
    ]))));
  } else if (ref.available && ref.pair?.length) {
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
  details.append(reference);
  details.append(section('Before-fee cashflows', facts([
    ['Normal winning payout', usd(gross.win_receipt_usd)], ['Profit if it wins', usd(gross.win_profit_usd)],
    ['Profit if it loses', usd(gross.loss_profit_usd)], ['Expected profit per claim', usd(gross.expected_profit_usd)],
    ['Risk per claim', usd(gross.risk_usd)], ['Return on risk', percent(gross.return_percent)]
  ]), el('p', 'Expected profit = fair chance × win profit + losing chance × loss profit. Return = expected profit ÷ risk.', 'inspection-formula')),
  fee('EV with reviewed trading fees', data.reviewed, aggregatePrice ? null : data.starting_fee_terms), fee('EV with conservative fees', data.conservative));
  const model = data.assumed_scenario || {};
  const scenario = section('Full net EV');
  if (model.available) {
    scenario.append(facts([
      ['Assumed quantity', number(model.quantity_per_leg)], ['Expected profit after assumed fees', usd(model.fee_adjusted_expected_profit_usd)],
      ['Expected profit after buffer', usd(model.buffered_profit_usd)], ['Modeled return', percent(model.buffered_return_percent)],
      ...Object.entries(model.scenario_profits_usd || {}).map(([key, value]) => [human(key), usd(value)])
    ]), el('p', model.meaning, 'desk-meta'));
  }
  const gaps = [...new Set([...(model.missing || []), ...(data.reviewed?.missing || []),
    'Full outcome probabilities for pushes, ties and voids'])]
    .filter(gap => gap !== 'native quantity and executable depth')
    .map(gap => gap === 'sizing/depth assumption' ? 'Modeled stake' : gap);
  const list = el('ul'); gaps.forEach(gap => list.append(el('li', gap.includes('_') ? reasons(gap) : gap)));
  scenario.append(el('p', 'Still needed to establish full economics', 'desk-meta'), list); details.append(scenario);
  details.append(section('Quote clocks', facts([
    ['Original update', offer.source_clock_at], ['Book confirmation', offer.confirmed_at],
    ['Capture', offer.captured_at], ['Game state', human(offer.game_state)]
  ])));
  return result;
}

export function markPinned(root, pinned) {
  if (!pinned) return;
  const price = root.querySelector('[data-inspection-price]');
  const ev = root.querySelector('[data-inspection-ev]');
  if (price) price.textContent = pinned.price ? 'Last known · pinned' : 'Pinned price';
  if (ev) {
    ev.textContent = 'Last known EV · pinned';
    ev.parentElement.classList.remove('positive', 'negative');
  }
  for (const book of root.querySelectorAll('[data-inspection-book]')) {
    book.textContent = 'Pinned sportsbook quote';
  }
}

export function pairInspection(pair, offers, {group, game, position, inspect, mode}) {
  const result = document.createDocumentFragment();
  const math = pair.inspection;
  const retail = pair.retail_payoff;
  const sizing = retail?.sizing;
  const sum = values => values.every(value => value != null) ? values.reduce((total, value) => total + num(value), 0) : null;
  result.append(el('p', group.game_title, 'inspection-matchup'));
  if (mode) result.append(el('p', mode, 'inspection-mode'));
  const minimum = retail?.available ? retail.minimum_net_profit_usd : null;
  const receipts = Object.values(retail?.states || {}).map(state => num(state.net_receipt_usd)).filter(Number.isFinite);
  result.append(tiles([
    ['Worst modeled profit/loss', usd(minimum), tone(minimum)],
    ['Lowest payout', usd(receipts.length ? Math.min(...receipts) : null)],
    ['Return on total funding', signedPercent(pair.score), tone(pair.score)],
    ['Total funding', usd(retail?.funding_usd)],
    ['Fees paid at fill', usd(retail?.available ? sum(retail.legs.map(leg => leg.at_fill_usd)) : null)]
  ]));
  if (retail?.available) {
    result.append(el('p', `Calculated for a ${usd(sizing?.requested_stake_usd ?? math.funding_usd)} stake before fees. Lowest payout covers the settlement states shown below.`, 'desk-meta'));
    if (!Object.keys(retail.states).some(state => state.includes('void') || state.includes('cancel'))) {
      result.append(el('p', 'Void and cancellation cashflows are unavailable for this pair.', 'desk-meta'));
    }
  }
  if (!retail?.available) result.append(el('p', reasons(retail?.reason || 'pair_settlement_unverified'), 'inspection-gap'));
  const legs = section('Two legs');
  const evidence = disclosure('Exact prices, settlement terms and fee rounding');
  const assumptions = section('Funding and allocation', facts([
    ['Requested stake before fees', usd(sizing?.requested_stake_usd ?? math.funding_usd)],
    ['Acquisition cost', usd(sizing?.acquisition_usd ?? math.funding_usd)],
    ...(sizing ? [['Unused stake', usd(sizing.unused_stake_usd)], ['Quantity per leg', sizing.quantity]] : []),
    ...(!sizing ? [['Lower decisive profit before fees', usd(math.minimum_profit_usd)]] : [])
  ]), el('p', sizing
    ? 'Buy the same whole number of claims on both legs, within the requested stake and the captured quantity grid. Add both fill fees to acquisition cost for total funding.'
    : math.rounding, 'inspection-formula'));
  evidence.append(assumptions);
  if (pair.settlement_payouts) {
    evidence.append(section('Joint settlement terms', facts(Object.entries(pair.settlement_payouts).map(([state, payouts]) => [
      pairState(state), payouts.map((payout, index) => `${name(offers.get(pair.legs[index]).venue)} ${usd(payout)} per $1 claim`).join(' · ')
    ]))));
  }
  if (retail?.available && retail.legs.every(leg => leg.receipts_usd)) {
    evidence.append(section('Payout by leg', facts(Object.keys(retail.states).map(state => [
      pairState(state), retail.legs.map((leg, index) =>
        `${name(offers.get(pair.legs[index]).venue)} ${usd(leg.receipts_usd[state])}`).join(' · ')
    ]))));
  }
  math.legs.forEach((leg, index) => {
    const offer = offers.get(pair.legs[index]);
    const charge = retail?.legs[index];
    const info = el('div', null, 'inspection-leg');
    const label = `${name(offer.venue)} · ${position(offer, game)}`;
    const offered = el('strong');
    offered.append(odd(offer.odds));
    info.append(el('h4', label), offered,
      facts([['Modeled $1 claims', charge?.quantity],
        ['Acquisition cost', usd(charge?.acquisition_usd ?? leg.allocation_usd)],
        [charge?.classification === 'synthetic' ? 'Fictional fee at fill' : 'Fee at fill',
          charge?.available ? usd(charge.at_fill_usd) : 'Unavailable'],
        ...(offer.trade_fee?.evidence?.fictional_rate != null
          ? [['Fictional rate', `${percent(num(offer.trade_fee.evidence.fictional_rate) * 100)} of the acquisition cost`]] : [])]),
      button('Inspect offer and fees', () => inspect(offer), 'desk-action'));
    legs.append(info);
    const feeTerms = offer.trade_fee?.evidence || {};
    const exactLeg = section(label, facts([
      ['Cost per $1 claim', usd(leg.cost_per_claim)],
      ['Exact cost per claim', leg.cost_per_claim],
      ['Source update', offer.source_clock_at || offer.source_at],
      ['Book confirmation', offer.confirmed_at], ['Local receipt', offer.received_at],
      ...(charge?.available ? [
        ...Object.entries(charge.settlement_usd).map(([state, fee]) => [`Settlement fee · ${pairState(state)}`, usd(fee)]),
        ['Fee evidence', feeClasses[charge.classification]],
        ...(feeTerms.version ? [['Fee schedule', feeTerms.version]] : []),
        ...((feeTerms.coefficient ?? feeTerms.fee_rate) != null ? [['Fee coefficient', feeTerms.coefficient ?? feeTerms.fee_rate]] : [])
      ] : [['Fee at this stake', reasons(charge?.reason || retail?.reason || 'pair_fee_size_unverified')]])
    ]), ...(charge?.assumptions || offer.trade_fee?.assumptions || []).map(note => el('p', note, 'desk-meta')));
    if (charge?.rounding_trace?.length) exactLeg.append(roundingTrace(charge.rounding_trace));
    evidence.append(exactLeg);
  });
  const net = section('Payoff by settlement state');
  if (retail?.available) {
    const table = el('table', null, 'inspection-payoffs');
    const head = el('thead'), headings = el('tr'), rows = el('tbody');
    for (const label of ['Settlement', 'Net payout', 'Net profit']) {
      const column = el('th', label);
      column.scope = 'col';
      headings.append(column);
    }
    head.append(headings);
    table.append(head, rows);
    for (const [state, values] of Object.entries(retail.states)) {
      const tr = el('tr'), label = el('th', pairState(state));
      label.scope = 'row';
      tr.append(label, el('td', usd(values.net_receipt_usd)),
        el('td', usd(values.net_profit_usd), tone(values.net_profit_usd)));
      rows.append(tr);
    }
    net.append(table, el('p', 'Return is the lowest modeled net profit across the shown states divided by total funding.', 'desk-meta'));
  }
  const columns = el('div', null, 'inspection-columns');
  columns.append(legs);
  if (retail?.available) columns.append(net);
  result.append(columns, evidence);
  const raw = disclosure('Raw pair calculation');
  raw.addEventListener('toggle', () => {
    if (raw.open && raw.children.length === 1) raw.append(el('pre', JSON.stringify(pair, null, 2)));
  });
  result.append(raw);
  return result;
}

const pairState = state => ({
  first_wins:'First leg wins', second_wins:'Second leg wins', equality:'Tie or exact-line settlement',
  void:'Void', both_void:'Both void', push:'Push', canceled:'Canceled'
})[state] || human(state);
