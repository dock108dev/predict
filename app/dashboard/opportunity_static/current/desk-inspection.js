import {evidenceReason as reasons} from './desk-reasons.js';
import {pinnedInspection} from './desk-evidence.js';
import {basisName, quoteFreshness, selectedReference, settlementLabel, sportsbookQuotes, winPayout, percent as signedPercent, tone} from './opportunity-cards.js';
// The server owns the exact inputs and cashflows. Formatting happens here.
const {el, num, fmt, odd, name, button} = window.PredictUI;
const percent = value => value == null ? 'Unavailable' : `${fmt(value)}%`;
const probability = value => value == null ? 'Unavailable' : percent(num(value) * 100);
const usd = (value, maximumFractionDigits = 6) => value == null ? 'Unavailable' : new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits
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

function fee(title, model) {
  model ||= {};
  const block = section(title);
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
  recorded_scope: 'Recorded fee for this saved scenario',
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
      ['Trade profile', fictional ? 'Authored scenario' : 'Manual retail'],
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
    block.append(el('p', 'A tie or exact-line outcome can change expected profit. The before-fee scenario covers decisive win and loss. Full EV also needs the probability and net receipt for each material outcome.', 'inspection-formula'));
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

function metrics(entries, className) {
  const list = el('dl', null, className);
  for (const [label, value, style] of entries) {
    const tile = el('div');
    const total = el('dd', null, style);
    total.append(value);
    tile.append(el('dt', label), total);
    list.append(tile);
  }
  return list;
}

function tiles(primary, supporting = []) {
  const overview = el('div', null, 'inspection-tiles');
  overview.append(metrics(primary, 'inspection-primary'));
  if (supporting.length) overview.append(metrics(supporting, 'inspection-supporting'));
  return overview;
}

function sportsbookReference(reference) {
  return metrics([
    ['Selected book', name(reference.book)],
    ...(reference.prices?.[0] ? [['Selected odds', reference.prices[0].price_american]] : []),
    ...(reference.prices?.[1] ? [['Opposite odds', reference.prices[1].price_american]] : []),
    ...(reference.fair_odds ? [['Estimated fair odds', odd(reference.fair_odds)]] : []),
    ...(reference.probability != null ? [['Fair win chance', probability(reference.probability)]] : [])
  ], 'inspection-reference-prices');
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

export function tradeInspection(offer, group, evidence, {mode, position, basis, checkedAt, pinned, pairLeg, pairFee, pairAcquisition, publication}) {
  const result = document.createDocumentFragment();
  result.append(el('p', group.game_title, 'inspection-matchup'));
  if (mode) result.append(el('p', mode, 'inspection-mode'));
  const payout = winPayout(offer);
  if (payout) result.append(el('p', payout, 'inspection-win-example'));
  const sportsbook = offer.sportsbook;
  const selectedRef = (basis !== 'sportsbooks' && offer.reference_current && offer.reference_calculation) || sportsbook;
  const cost = offer.cost_per_normal_claim ?? evidence?.inspection?.before_fees?.cost_usd;
  const quote = el('span');
  quote.append(odd(offer.odds, 'p-odds inspection-metric-value'));
  const priceFreshness = el('small', quoteFreshness(offer, mode, true), 'inspection-price-unit');
  priceFreshness.dataset.inspectionPrice = '1';
  quote.append(priceFreshness);
  if (cost != null) quote.append(el('small', `${usd(cost)} per $1 payout`, 'inspection-price-unit'));
  const priceBasis = {native_book:'Native order book ask', aggregate_snapshot:'Aggregate quote', synthetic:'Authored scenario quote'}[offer.price_basis];
  if (offer.book_size) quote.append(el('small', `${offer.book_size.quantity} ${offer.book_size.quantity_unit} at this price`, 'inspection-price-unit'));
  const tradeFee = offer.trade_fee;
  const activeFee = (offer.current || mode) && tradeFee?.available ? tradeFee.trade_fee_usd : null;
  const value = offer.value ?? offer.last_known_ev;
  const ev = el('span', null, tone(offer.value));
  if (value != null) {
    ev.append(el('span', signedPercent(value), 'inspection-metric-value'));
    const freshness = offer.value == null ? 'Last known EV' : mode ? 'At capture' : 'Current at inspection';
    const evFreshness = el('small', freshness, 'inspection-price-unit');
    evFreshness.dataset.inspectionEv = '1';
    ev.append(evFreshness);
    const estimate = num(value);
    ev.append(el('small', `${usd(Math.abs(estimate), 2)} average ${estimate < 0 ? 'loss' : 'profit'} per $100 risked`, 'inspection-price-unit'));
  } else {
    ev.append(el('span', 'Unavailable', 'inspection-unavailable'),
      el('small', reasons(offer.reason, 'No qualified same-line sportsbook pair.'), 'inspection-price-unit'));
  }
  const feeReadout = el('span');
  feeReadout.append(el('span', usd(activeFee), activeFee == null ? 'inspection-unavailable' : ''));
  if (activeFee != null) {
    const feeClass = feeClasses[tradeFee.classification];
    const timing = tradeFee.fee_cashflows?.winning_settlement_usd != null ? 'if it wins' : 'at fill';
    feeReadout.append(el('small', [feeClass, timing].filter(Boolean).join(' · '), 'inspection-price-unit'));
  } else {
    const reason = tradeFee?.reason || (tradeFee?.available && 'fee_source_price_not_current')
      || (offer.trade_fee_available === false && 'fee_outcome_not_published');
    if (reason) feeReadout.append(el('small', reasons(reason), 'inspection-price-unit'));
  }
  const effective = el('span', offer.effective_quote ? number(offer.effective_quote.decimal_odds) : 'Unavailable',
    offer.effective_quote ? '' : 'inspection-unavailable');
  if (!offer.effective_quote && offer.effective_reason) {
    effective.append(el('small', reasons(offer.effective_reason), 'inspection-price-unit'));
  }
  result.append(tiles([['Venue quote', quote], ...(!pairLeg ? [[basisName(basis) || 'Expected value', ev]] : [])], [
    ['Trading fee', feeReadout], ['Effective decimal odds', effective]
  ]));
  const terms = evidence?.inspection?.starting_fee_terms;
  if (terms) {
    const policy = section('Recorded fee policy', facts(terms.values), el('p', terms.scope, 'desk-meta'));
    if (terms.in_review_window === false) {
      policy.append(el('p', 'This capture falls outside the recorded fee review window.', 'desk-meta'));
    }
    result.append(policy);
  }
  if (pairFee?.available) {
    const modeled = pairFee.classification === 'synthetic' ? 'Fictional pairing fee' : 'Modeled pairing fee';
    const acquisition = pairAcquisition != null ? ` on ${usd(pairAcquisition)} of acquisition cost` : '';
    result.append(el('p', `${modeled} · ${usd(pairFee.at_fill_usd)} at fill${acquisition}`, 'desk-meta'));
  }
  const settlementStatus = settlementLabel(group);
  if (settlementStatus && group.settlement_match !== 'matched') result.append(el('p', settlementStatus, 'desk-meta'));
  const referenceBook = selectedRef?.contributors?.find(item => item.venue === selectedRef.venue) ?? selectedRef?.contributors?.[0];
  const comparison = basis === 'sportsbooks' && sportsbook ? sportsbook : referenceBook ? {
    book:referenceBook.venue, prices:referenceBook.inputs, probability:selectedRef.probability, fair_odds:offer.reference,
    candidates:Object.fromEntries(selectedRef.contributors.map(item => [item.venue, item.inputs]))
  } : null;
  const bookQuotes = Object.values(group.sportsbook_quotes || {}).some(quotes => quotes.length);
  if (comparison || bookQuotes || group.sportsbook_source_reason) {
    const books = section('Same-line sportsbook quotes');
    const extra = [];
    if (comparison) {
      books.append(sportsbookReference(comparison));
      if (comparison.indicative) {
        books.append(el('p', 'Before fees · decisive win or loss only', 'desk-meta'));
      }
      const candidates = Object.entries(comparison.candidates || {}).filter(([book]) => book !== comparison.book);
      if (candidates.length) {
        extra.push(facts(candidates.map(([book, prices]) => [
          name(book), prices.map(leg => leg.price_american).join(' / ')
        ])));
      }
    }
    if (bookQuotes) {
      extra.push(sportsbookQuotes({...group, sportsbook_source_reason:null},
        selectedReference(offer, basis), checkedAt, mode, true));
    }
    if (extra.length) books.append(...(comparison ? [disclosure('More sportsbook prices', ...extra)] : extra));
    if (group.sportsbook_source_reason) books.append(el('p', evidenceReason(group.sportsbook_source_reason), 'desk-meta'));
    result.append(books);
  } else if (!pairLeg && offer.probability != null) {
    result.append(metrics([['Fair win chance', probability(offer.probability)]], 'inspection-reference-prices'));
  }
  const directRead = offer.live_native_desk ? 'Native book read'
    : offer.live_aggregate_desk && !offer.evidence_result_id ? 'Aggregate quote read' : null;
  const quoteClocks = offer.price_basis === 'synthetic' ? [['Authored scenario time', offer.source_clock_at]] : [
    ['Original source update', offer.source_clock_at],
    ...(offer.confirmed_at || offer.price_basis === 'native_book' ? [['Book confirmation', offer.confirmed_at]] : []),
    ['Collector receipt', offer.received_at],
    [directRead || 'Price capture', offer.captured_at],
    ...(!mode && !directRead ? [['Board publication', publication?.published_at]] : [])
  ];
  result.append(disclosure('Quote times', facts(quoteClocks)));
  markPinned(result, pinned);
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
    ...[['Price provider', data.source?.provider === 'oddslink_public_board' ? 'OddsLink' : data.source?.provider === 'sportsgameodds' ? 'SportsGameOdds' : data.source?.provider === 'practice' ? 'Authored scenario' : null],
      ['Quote type', priceBasis]].filter(([, value]) => value),
    ['Native side', data.source?.native_side && human(data.source.native_side)], ['Original price', original.value == null ? null : `${original.value} ${human(original.units)}`],
    ...[['Native event', data.source?.native_event_id], ['Native market', data.source?.native_market_id],
      ['Native outcome', data.source?.native_outcome_id]].filter(([, value]) => value != null),
    ['Payout unit', original.payout && `${original.payout} ${original.payout_units || 'USD'}`],
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
  } else if (ref.available && ref.method === 'authored_probability') {
    reference.append(facts([
      ['Authored scenario probability', probability(ref.probability)],
      ['Scenario fair decimal odds', number(ref.fair_decimal_odds)]
    ]), el('p', ref.conditioning, 'desk-meta'));
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
  fee('EV with reviewed trading fees', data.reviewed), fee('EV with conservative fees', data.conservative));
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
  return result;
}

export function markPinned(root, pinned) {
  if (!pinned) return;
  const price = root.querySelector('[data-inspection-price]');
  const ev = root.querySelector('[data-inspection-ev]');
  if (price) price.textContent = 'Price at inspection';
  if (ev) {
    ev.textContent = 'EV at inspection';
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
  const scoring = pair.scoring_scopes?.length && section('Scoring scope by venue', facts(pair.scoring_scopes.map((scope, i) => [
    name(offers.get(pair.legs[i])?.venue),
    [`Overtime ${scope.overtime}`, scope.extra_innings && scope.extra_innings !== 'not_applicable'
      && `extra innings ${scope.extra_innings}`, scope.shootout && scope.shootout !== 'not_applicable'
      && (scope.shootout === 'official_final_score' ? 'shootout uses official final score' : `shootout ${scope.shootout}`)]
      .filter(Boolean).join(' · ')
  ])));
  if (!math) {
    result.append(el('p', reasons(retail?.reason || 'pair_settlement_unverified'), 'inspection-gap'));
    for (const id of pair.legs) {
      const offer = offers.get(id);
      if (!offer) continue;
      const action = button(`Inspect ${name(offer.venue)} offer`, event => inspect(offer, event.currentTarget), 'desk-action');
      const label = el('p', `${position(offer, game)} · ${quoteFreshness(offer, mode)}`);
      label.append(' ', odd(offer.odds));
      result.append(label, action);
    }
    if (scoring) result.append(scoring);
    return result;
  }
  const decisiveReceipts = sizing?.quantity != null
    ? math.legs.map(() => num(sizing.quantity))
    : math.legs.map(leg => num(leg.win_receipt_usd));
  if (decisiveReceipts.length === 2 && decisiveReceipts.every(value => Number.isFinite(value) && value > 0)) {
    const stake = sizing ? `${usd(sizing.requested_stake_usd, 2)} budget` : `${usd(math.funding_usd, 2)} staked`;
    result.append(section('Lowest decisive payout before fees', el('strong', `${usd(Math.min(...decisiveReceipts), 2)} on ${stake}`)));
  }
  const feeStatus = retail?.available
    ? retail.fee_basis === 'conservative' ? 'After-fee payoff modeled with conservative fees.' : 'After-fee payoff modeled with applicable fees.'
    : `After-fee payoff unavailable. ${retail?.reason === 'pair_settlement_unverified'
      ? 'Joint settlement cashflows are missing.' : reasons(retail?.reason)}`;
  const jointStatus = retail?.full_arbitrage_qualified ? 'Joint settlement verified.'
    : 'Full joint settlement unverified for outcomes such as voids, cancellations and postponed games.';
  result.append(el('p', `${feeStatus} ${jointStatus}`, 'desk-meta'));
  const minimum = retail?.available ? retail.minimum_net_profit_usd : null;
  const receipts = Object.values(retail?.states || {}).map(state => num(state.net_receipt_usd)).filter(Number.isFinite);
  if (retail?.available) {
    result.append(tiles([
      ['Return on total funding', signedPercent(pair.score), tone(pair.score)],
      ['Worst modeled profit/loss', usd(minimum), tone(minimum)]
    ], [
      ['Lowest net payout', usd(retail.minimum_net_payout_usd ?? (receipts.length ? Math.min(...receipts) : null))],
      ['Total funding', usd(retail.funding_usd)],
      ['Fees paid at fill', usd(sum(retail.legs.map(leg => leg.at_fill_usd)))],
      ['Stake used before fees', usd(sizing?.requested_stake_usd ?? math.funding_usd)]
    ]));
  }
  if (retail?.execution_reason) result.append(el('p', reasons(retail.execution_reason), 'desk-meta'));
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
  if (scoring) evidence.append(scoring);
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
    const priceBasis = {native_book:'Native order book', aggregate_snapshot:'Aggregate quote'}[offer.price_basis];
    info.append(el('h4', label), offered,
      facts([['Price basis', [priceBasis, quoteFreshness(offer, mode)].filter(Boolean).join(' · ')],
        ...(charge?.quantity == null ? [] : [['Modeled $1 claims', charge.quantity]]),
        ['Acquisition cost', usd(charge?.acquisition_usd ?? leg.allocation_usd)],
        [charge?.classification === 'synthetic' ? 'Fictional fee at fill' : 'Fee at fill',
          charge?.available ? [usd(charge.at_fill_usd), feeClasses[charge.classification]].filter(Boolean).join(' · ')
            : `Unavailable · ${reasons(charge?.reason || 'pair_fee_size_unverified')}`],
        ...(offer.trade_fee?.evidence?.fictional_rate != null
          ? [['Fictional rate', `${percent(num(offer.trade_fee.evidence.fictional_rate) * 100)} of the acquisition cost`]] : [])]),
      button('Inspect offer and fees', event => inspect(offer, event.currentTarget), 'desk-action'));
    legs.append(info);
    const feeTerms = offer.trade_fee?.evidence || {};
    const exactLeg = section(label, facts([
      ['Cost per $1 claim', usd(leg.cost_per_claim)],
      ['Exact cost per claim', leg.cost_per_claim],
      ['Captured claims at this price', charge?.depth_evidence?.quantity],
      ['Original source update', offer.source_clock_at],
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
    net.append(table, el('p', 'Return = lowest modeled net profit ÷ total funding.', 'desk-meta'));
  }
  const columns = el('div', null, 'inspection-columns');
  if (retail?.available) columns.append(net);
  columns.append(legs);
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
