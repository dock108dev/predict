import {card, count, details, label, link, list, node, pairs, pct, stack, table, text, time, usd} from './workspace-ui.js';
import {number, selection, venue} from './workspace-format.js';
import {exactMoney, fixedProfitFields, mainFirstRule} from './research-campaigns.js';

const variants = {best_venue:'Best venue only', all_venues:'All qualifying venues'};
const validity = {
  no_valid_capture:'No valid T−10 captures',
  incomplete_tracked_capture:'Incomplete tracked population',
  tracked_captures_only:'Tracked capture coverage only',
};
const statuses = {
  screened:'Captured population screened', incomplete:'Run incomplete', awaiting_captures:'Awaiting captures',
  pending:'Pending capture', captured:'Captured', refused:'Capture refused', missed:'Capture missed',
  reconstructed:'Reconstructed from original T−10 response',
  superseded_by_reschedule:'Capture superseded by reschedule',
};
const resultLabel = {win:'Modeled win', loss:'Modeled loss', unresolved:'Unresolved'};
const capturedFee = mode => mode?.enabled === true ? 'Captured with fees included' : mode?.enabled === false ? '$0 fees assumed in capture' : 'Captured fee treatment unknown';
const evidenceLink = (title, href) => link(title, href, 'research-button');
const evidenceClock = new Intl.DateTimeFormat('en-US', {timeZone:'America/New_York',
  month:'short', day:'numeric', hour:'numeric', minute:'2-digit', second:'2-digit', fractionalSecondDigits:3, timeZoneName:'short'});
const preciseTime = value => value && Number.isFinite(Date.parse(value)) ? evidenceClock.format(new Date(value)) : 'Not recorded';

export function portfolioSelectionFields(choice, family) {
  const tier = {main:'Qualifying main line', nearby_alternate:'Closest qualifying alternate'}[choice?.tier];
  if (!tier) return {};
  const {anchor, basis, ranked_quote_venue, fair_probability, selected_quote_line_role} = choice;
  const distance = number(choice.distance_points);
  const source = {two_way_moneyline:'Two-way moneyline', venue_main_line:'Main line at the ranking venue',
    other_venue_main_line:'Main line recorded at another venue'}[basis];
  const role = {main:'Main', alternate:'Alternate', unknown:'Unconfirmed'}[selected_quote_line_role];
  const anchorLabel = family==='spread' ? 'Recorded main line (home spread)' : 'Recorded main line';
  const anchorLine = number(anchor?.line) ?? anchor?.line;
  const anchorVenue = anchor?.venue ? ` · ${venue(anchor.venue)}` : '';
  return {
    'Selection tier':tier,
    ...(source ? {'Line evidence':source} : {}),
    ...(anchorLine == null ? {} : {[anchorLabel]:`${anchorLine}${anchorVenue}`}),
    ...(choice.tier==='nearby_alternate' && distance!=null ? {'Distance from main line':`${distance} ${distance===1 ? 'point' : 'points'}`} : {}),
    ...(ranked_quote_venue ? {'Ranking quote venue':venue(ranked_quote_venue)} : {}),
    ...(fair_probability == null ? {} : {'Fair win probability used to rank':pct(fair_probability)}),
    ...(role ? {'Selected quote line role':role} : {}),
  };
}

function coverageDescription(run) {
  if (run.coverage?.reconstructed_games) return 'This opportunity record separates frozen calculations from reconstructions that used the original T−10 responses. Sporting grades appear in the separate result reports.';
  if (run.validity === 'no_valid_capture') return 'No paper result can be evaluated from this saved run. Capture dispositions show why evidence is unavailable.';
  if (run.coverage?.missing_tracked_games) return 'Some tracked games have no valid T−10 capture. Financial metrics are limited to tickets from captured games.';
  return 'Financial metrics use the available frozen T−10 captures. Slate-wide completeness is unknown.';
}
function exposure(root, portfolio, games) {
  const gameNames = new Map(games.map(game => [game.game_id, game.title]));
  const grid = node('div', undefined, 'workspace-grid');
  for (const [scope, title, display] of [
    ['venue', 'Exposure by venue', venue],
    ['game', 'Exposure by game', id => gameNames.get(id) || id],
  ]) {
    const panel = card(title);
    const entries = Object.entries(portfolio['by_' + scope] || {});
    if (entries.length) panel.append(table([scope === 'venue' ? 'Venue' : 'Game', 'Total committed', 'Unresolved committed'], entries.map(([key, amount]) => [
      display(key), usd(amount), usd(portfolio['unresolved_by_' + scope]?.[key] ?? 0),
    ])));
    else panel.append(node('p', 'No commitment recorded for this variant.'));
    grid.append(panel);
  }
  root.append(grid);
}
function ticketTable(portfolio, ticketLink) {
  return table(['Game and start', 'Selection', 'Venue and price', 'EV and probability', 'Committed', 'Sporting-result grading', 'Evidence'], (portfolio.tickets || []).map(ticket => [
    stack(ticket.title, time(ticket.starts_at)),
    stack(selection({ ...ticket, selection_label:ticket.label }), label(ticket.family)),
    stack(venue(ticket.venue), ticket.posted_odds),
    stack(pct(ticket.ev), pct(ticket.probability) + ' probability'),
    usd(ticket.stake_usd),
    stack(resultLabel[ticket.grading?.state] || 'Unresolved', ticket.grading?.pnl_usd == null ? label(ticket.grading?.reason) : usd(ticket.grading.pnl_usd)),
    evidenceLink('Inspect ticket', ticketLink(ticket)),
  ]));
}
function runComparison(comparison, priorRunLink) {
  const panel = node('section', undefined, 'workspace-panel');
  panel.append(node('h2', 'Changes from the previous saved run'),
    link(`Open prior run · ${comparison.prior_run_id.slice(0, 12)}`, priorRunLink(comparison.prior_run_id)));
  const rows = [];
  function add(name, change, format = count) {
    if (!change) return;
    const delta = number(change.delta);
    rows.push([name, format(change.before), format(change.after), delta == null ? 'Unknown'
      : `${delta > 0 ? '+' : ''}${format(change.delta)}`]);
  }
  add('Eligible games', comparison.games);
  for (const [key, value] of Object.entries(comparison.captures || {})) add(statuses[key] || label(key), value);
  add('Offers observed', comparison.offers);
  for (const [key, value] of Object.entries(comparison.exclusions || {})) add(label(key), value);
  for (const [variant, value] of Object.entries(comparison.variants || {})) {
    add(`${variants[variant]} tickets`, value.tickets);
    add(`${variants[variant]} paper turnover`, value.turnover_usd, usd);
  }
  panel.append(table(['Evidence or measure', 'Prior run', 'This run', 'Change'], rows));
  if (comparison.added_games?.length) panel.append(node('h3', 'Games added to this run'), list(comparison.added_games));
  if (comparison.removed_games?.length) panel.append(node('h3', 'Games removed from this run'), list(comparison.removed_games));
  return panel;
}

export function renderRun(root, {run, definition, report, comparison}, navigation) {
  const {variant, variantLink, ticketLink, gameLink, exportLink, offerExportLink, definitionLink} = navigation;
  const coverage = run.coverage || {};
  const intro = node('section', undefined, 'workspace-panel');
  intro.append(node('h2', run.title));
  if (definition?.question) intro.append(node('p', definition.question));
  intro.append(node('p', `${run.date} Eastern · ${label(definition?.designation)} · Definition ${run.definition_version} · Saved ${time(run.created_at)}`, 'workspace-clocks'));
  const notice = node('div', undefined, 'workspace-notice');
  notice.dataset.state = run.status === 'screened' && run.validity === 'tracked_captures_only' ? 'screened' : 'incomplete';
  notice.append(node('strong', validity[run.validity] || label(run.validity)), node('p', coverageDescription(run)));
  intro.append(notice, pairs({
    'Expected games':count(coverage.expected_games),
    'Tracked games':count(coverage.tracked_games),
    'Valid T−10 captures':count(coverage.captured_games),
    'Missing among tracked':count(coverage.missing_tracked_games),
    'Pending checkpoints':count(coverage.pending_games),
    'Untracked games':count(coverage.untracked_games),
  }, 'workspace-stats'));
  if (coverage.reconstructed_games) intro.append(pairs({'Raw T−10 responses reconstructed later':count(coverage.reconstructed_games)}, 'workspace-stats'));
  if (coverage.source_coverage_unconfirmed_games) intro.append(node('p', `Source coverage is unconfirmed for ${count(coverage.source_coverage_unconfirmed_games)} captured games.`));
  const methods = node('details');
  methods.open = true;
  methods.append(node('summary', 'Frozen assumptions for this run'));
  const policy = report?.policy || definition?.policy || {};
  if (policy.recovered_checkpoints) methods.append(node('p', 'Retrospective recovery: the original pilot is preserved. Recovered probabilities and EV were calculated after the game from the original response, under an explicit $0-fee assumption. These are hypothetical opportunities, not evidence that EV was displayed at T−10.'));
  const feeModes = [...new Set((report?.games || []).filter(game => game.fee_mode).map(game => capturedFee(game.fee_mode)))];
  const sizing=policy.sizing_mode==='fixed_profit'
    ? `The replay targets ${exactMoney(policy.target_profit_usd)} net profit on each win. If the target is between achievable amounts, it takes the closest positive profit and breaks ties at the lower commitment.`
    : `The replay uses ${pct(policy.kelly_multiplier)} of Kelly against a fixed ${usd(policy.reference_bankroll_usd)} sizing reference.`;
  methods.append(node('p', `The game date uses Eastern time. Screening requires ${policy.recovered_checkpoints ? 'an original frozen checkpoint or an explicitly reconstructed T−10 response' : 'a valid frozen T−10 checkpoint'} and unrounded EV of at least ${pct(policy.minimum_ev)}. ${sizing}`));
  if (policy.minimum_stake_usd != null) methods.append(node('p',
    `The minimum stake per trade is ${exactMoney(policy.minimum_stake_usd)} after sizing and modeled fees.`));
  if (policy.portfolio_rule===mainFirstRule.id) methods.append(node('p',`${mainFirstRule.title}. ${mainFirstRule.description}`));
  methods.append(node('p','Paper commitments are sized independently without an aggregate budget cap or intraday compounding.'));
  methods.append(node('p', `Each paper commitment is repriced under the original fee assumption. ${feeModes.length ? feeModes.join(' · ') + '.' : 'No captured fee treatments are recorded for this run.'} Quoted price is assumed available at the modeled size.`));
  methods.append(node('p', 'Paper replay and sporting-result grading are recorded separately. Execution and actual venue settlement are unverified.'));
  if (definitionLink) methods.append(definitionLink);
  intro.append(methods);
  const actions = node('div', undefined, 'workspace-links');
  actions.append(evidenceLink('Export saved run and evidence', exportLink));
  if (offerExportLink) actions.append(evidenceLink('Export dated offer ledger', offerExportLink));
  intro.append(actions);
  root.append(intro);
  if (comparison?.prior_run_id && navigation.priorRunLink) root.append(runComparison(comparison, navigation.priorRunLink));

  const runs = node('section', undefined, 'workspace-panel');
  if (!navigation.embedded) {
    const constrained = policy.portfolio_rule===mainFirstRule.id;
    runs.append(node('h2', 'Portfolio variants'), node('p', constrained ? mainFirstRule.description
      : 'Both variants use the same observations. Best venue keeps the highest qualifying sized EV for each exact bet; all qualifying venues keeps one ticket per exact bet per venue.'));
    const nav = node('div', undefined, 'workspace-variant');
    for (const [name, title] of Object.entries(variants)) {
      if (constrained && name!=='best_venue') continue;
      const action = evidenceLink(title, variantLink(name));
      if (name === variant) action.setAttribute('aria-current', 'true');
      nav.append(action);
    }
    runs.append(nav);
  }
  const portfolio = report?.portfolios?.[variant];
  if (portfolio && (coverage.captured_games || coverage.reconstructed_games)) {
    runs.append(node('h3', variants[variant]), pairs({
      'Qualifying tickets':count(portfolio.count), 'Unique games':count(portfolio.unique_games),
      'Days represented':count(portfolio.days_represented), Turnover:usd(portfolio.turnover_usd),
      ...(!policy.defer_results ? {'Peak overlapping commitment':usd(portfolio.peak_committed_usd)} : {}),
    }, 'workspace-stats'));
    const resultGrid = node('div', undefined, 'workspace-grid');
    const resolved = card(policy.defer_results ? 'Original opportunity record' : 'Resolved tickets');
    resolved.append(node('p', policy.defer_results ? 'Sporting grades are published separately. This saved selection preserves the original calculations and commitments.' : portfolio.resolved ? 'Expected and realized-model values use the same resolved-ticket population.' : 'No tickets have a decisive sporting result in this saved run.'), pairs({
      'Resolved tickets':count(portfolio.resolved),
      'Expected profit at entry':portfolio.resolved ? usd(portfolio.resolved_expected_profit_usd) : 'Unavailable',
      'Modeled P/L':portfolio.resolved ? usd(portfolio.modeled_resolved_pnl_usd) : 'Unavailable',
    }));
    const unresolved = card('Unresolved exposure');
    unresolved.append(pairs({
      'Unresolved tickets':count(portfolio.unresolved),
      'Unresolved committed':usd(portfolio.unresolved_turnover_usd),
      'Outstanding cash commitment':usd(portfolio.outstanding_usd),
    }));
    resultGrid.append(resolved, unresolved);
    runs.append(resultGrid, node('h3', 'Paper tickets'));
    if (portfolio.tickets?.length) runs.append(ticketTable(portfolio, ticketLink));
    else runs.append(node('p', 'No tickets qualified among the available frozen captures.'));
    exposure(runs, portfolio, report.games || []);
  } else runs.append(node('p', 'Financial metrics are unavailable without a valid capture.'));
  root.append(runs);

  const dispositions = node('section', undefined, 'workspace-panel');
  const ticketsByGame = new Map();
  for (const ticket of portfolio?.tickets || []) ticketsByGame.set(ticket.game_id, (ticketsByGame.get(ticket.game_id) || 0) + 1);
  dispositions.append(node('h2', 'Capture dispositions and exclusions'));
  if (report?.games?.length) dispositions.append(table(['Tracked game', 'T−10 capture', 'Qualifying offers', 'Evidence'], report.games.map(game => [
    stack(game.title, time(game.starts_at)),
    stack(statuses[game.status] || label(game.status), game.reason ? label(game.reason) : null),
    ['captured', 'reconstructed'].includes(game.status) ? count(ticketsByGame.get(game.game_id) || 0) : 'Unavailable',
    evidenceLink('Inspect capture', gameLink(game)),
  ])));
  else dispositions.append(node('p', 'No tracked game records are available on this date. The expected population remains unknown.'));
  if (report?.exclusions && Object.keys(report.exclusions).length) dispositions.append(pairs(Object.fromEntries(Object.entries(report.exclusions).map(([key,value]) => [label(key),count(value)]))));
  dispositions.append(details('Run identity, clocks and report revision', {
    run_id:run.id, status:run.status, validity:run.validity, definition_version:run.definition_version,
    report_revision:run.report_revision, portfolio_revision:report?.portfolio_revision, as_of:report?.as_of,
  }));
  root.append(dispositions);
}
function evidenceSection(root, title, description, values, technical) {
  const section = node('section', undefined, 'workspace-panel');
  section.append(node('h3', title));
  if (description) section.append(node('p', description));
  if (values) section.append(pairs(values));
  if (technical) section.append(details('Exact evidence and source details', technical));
  root.append(section);
}
export function renderSavedEvidence(root, value, {ticket, resultReview = false, showPortfolioSelection = !resultReview, exportLink, gameLink}) {
  root.replaceChildren();
  if (!ticket) {
    const game = value.game || value.disposition || value.evidence?.game || value;
    const checkpoint = value.checkpoint || value.evidence?.checkpoint;
    root.append(node('h3', game.title || 'T−10 capture disposition'));
    root.append(node('p', game.status === 'reconstructed' ? 'This calculation was reconstructed after the game from the original response received inside its T−10 window. The original failed capture remains recorded.' : game.status === 'captured' ? 'This is the frozen checkpoint used in the saved replay.' : 'This game remains in the tracked population. Its unavailable or ineligible checkpoint contributed no paper tickets.'));
    evidenceSection(root, 'Capture provenance', null, {
      Status:statuses[game.status] || label(game.status || checkpoint?.status),
      Reason:game.reason ? label(game.reason) : 'None recorded',
      'Scheduled start':time(game.starts_at),
      'Checkpoint time':time(checkpoint?.persisted_at || checkpoint?.captured_at || checkpoint?.received_at),
      'Original receipt time':time(checkpoint?.received_at),
      'Capture type':game.status === 'reconstructed' ? 'Retrospective raw-response reconstruction' : 'Frozen T−10 checkpoint',
      'Experiment eligibility':['captured', 'reconstructed'].includes(game.status) ? 'Included under saved definition' : 'Unavailable or ineligible',
    }, value);
    for (const attempt of value.attempts || []) {
      const fields = attempt.data || attempt.payload || attempt;
      evidenceSection(root, 'Recorded capture attempt', null, {
        State:label(fields.state || fields.status), Reason:label(fields.reason),
        Time:time(fields.known_at || fields.attempted_at || fields.at),
      }, attempt);
    }
    const outcome = value.sporting_result;
    if (outcome) evidenceSection(root, 'Recorded sporting result', 'This evidence is a sporting observation.', {
      'Result known at':time(outcome.known_at), Final:outcome.data?.final == null ? 'Unknown' : outcome.data.final ? 'Yes' : 'No',
    }, outcome);
    const source = node('div', undefined, 'workspace-links');
    if (value.links?.export) source.append(evidenceLink('Export frozen checkpoint and dependencies', value.links.export));
    if (value.original_response?.state === 'retained' && value.links?.raw) source.append(evidenceLink('Download original provider response', value.links.raw));
    else if (value.receipt_sha256) source.append(node('p', 'Original provider response: ' + label(value.original_response?.state)));
    root.append(source);
  } else {
    const item = value.ticket, evidence = value.evidence || {}, witness = item.witness || {};
    const offer = evidence.original_offer || witness.original_offer || {};
    const sized = evidence.sized_calculation || witness.sized_calculation || {};
    const reference = offer.calculation_payload?.reference || sized.reference || {};
    const original = offer.record?.quote?.original;
    const fee = sized.fee || {};
    const cashflows = fee.cashflows || {};
    const trade = evidence.trade || {}, clocks = trade.clocks || {}, quote = trade.quote || {};
    const kelly = trade.kelly || {};
    const sizing = trade.sizing || item.sizing;
    const portfolioSelection = item.portfolio_selection || trade.portfolio_selection;
    const fixed = sizing?.mode === 'fixed_profit';
    const recovered = item.source_kind === 'retrospective_raw_t10';
    if (!resultReview) {
      root.append(node('h3', item.title + ' · ' + selection({ ...item, selection_label:item.label })));
      root.append(node('p', `${venue(item.venue)} at ${text(item.posted_odds)}. This modeled ticket uses the frozen T−10 offer and its recorded probability.`));
    }
    if (recovered) root.append(node('p', `The model used the retained original T−10 response to reconstruct probability and EV. Reconstruction saved ${time(item.reconstructed_at)}.`, 'workspace-notice'));
    if (item.game_id) root.append(evidenceLink('Open frozen checkpoint', gameLink(item.game_id)));
    evidenceSection(root, 'Frozen quote', null, {
      'Posted odds':item.posted_odds, 'Original source price':original?.value ?? item.posted_odds,
      Venue:venue(item.venue), Provider:quote.provider || item.identity?.provider,
      'Provider event ID':quote.provider_event_id, 'Provider outcome ID':quote.provider_odd_id,
      'Venue-native contract ID':quote.venue_contract_id || 'Unavailable in captured evidence',
      'Exact period / selection / line':`${label(item.period)} · ${selection({...item, selection_label:item.label})}`,
      'Source time':preciseTime(clocks.source_at || item.times?.source_at), 'Source clock basis':label(clocks.source_time_kind),
      'Quote age at receipt':clocks.quote_age_at_receipt_seconds == null ? 'Unknown' : `${clocks.quote_age_at_receipt_seconds.toFixed(3)} seconds`,
      'Requested at':preciseTime(clocks.requested_at), 'Dispatched at':preciseTime(clocks.dispatched_at),
      'Quote receipt time':preciseTime(clocks.quote_received_at || item.times?.received_at),
      'Provider response received':preciseTime(clocks.received_at), 'Known to capture worker':preciseTime(clocks.known_at),
      'Capture clock':preciseTime(clocks.captured_at), 'Persistence clock':preciseTime(clocks.persisted_at),
      'Modeled decision time':preciseTime(item.decision_at), 'Capture eligibility':recovered ? 'Retrospective reconstruction; original T−10 response' : 'Valid frozen T−10 checkpoint',
    }, {checkpoint:evidence.checkpoint, original_offer:offer, source_quote:quote, clocks});
    evidenceSection(root, 'Probability and screening', 'Net EV weights the modeled win and loss return rates by their frozen outcome probabilities.', {
      'Estimated outcome probability':pct(item.probability), 'Reference book':reference.book ? venue(reference.book) : 'Unknown',
      'Gross EV at quoted price':pct(trade.gross_ev), 'Screening EV (rounded for display)':pct(item.screen_ev),
      'EV at modeled commitment':pct(item.ev),
    }, {reference, exact_probability:item.probability, exact_screen_ev:item.screen_ev, exact_sized_ev:item.ev});
    if (portfolioSelection?.tier) evidenceSection(root, 'Portfolio selection', mainFirstRule.description,
      showPortfolioSelection ? portfolioSelectionFields(portfolioSelection,item.family) : null, portfolioSelection);
    const depth = evidence.depth;
    const rule = depth ? 'The nearest permitted size at the frozen limit is modeled using public book levels and the versioned public venue fees.'
      : fixed
      ? 'The closest positive modeled win profit wins, with ties going to the lower commitment. Quantity and fees are repriced at the frozen quote.'
      : 'The saved Kelly calculation uses the modeled win and loss returns, then applies the recorded multiplier and bankroll. Quantity and fee rounding determine the final commitment.';
    evidenceSection(root, 'Paper sizing and fee treatment', depth ? rule : `${capturedFee(item.fee_mode)}. ${rule}`, {
      'Fee evidence for an actual order':trade.fees?.actual_fee_evidence === 'unknown' ? 'Unknown' : trade.fees?.actual_fee_evidence,
      ...(depth ? {
        'Displayed native quantity within limit':depth.available_native_quantity,
        'Displayed purchase value within limit':exactMoney(depth.available_purchase_usd),
        'Average modeled contract price':pct(depth.modeled_average_price),
        'Public book receipt bundle':depth.bundle_id,
      } : {'Executable size at the quoted price':trade.size?.executable_size_evidence === 'unavailable'
        ? 'Unavailable in captured evidence' : trade.size?.executable_size_evidence}),
      ...(fixed ? {
        ...fixedProfitFields(sizing),
        'Sizing rule':sizing.rule,
        'Ideal stake before fees and rounding':exactMoney(sizing.ideal_purchase_usd),
        'Quantity increment':sizing.quantity_increment,
        'Quantity unit':label(sizing.quantity_unit),
        'Price increment':sizing.price_increment ?? 'Unavailable in captured evidence',
        'Sizing grid':label(sizing.grid_basis),
      } : {
        'Reference bankroll':usd(kelly.reference_bankroll_usd), 'Kelly multiplier':pct(kelly.multiplier),
        'Modeled win / loss net return':`${pct(kelly.outcome_returns?.win)} / ${pct(kelly.outcome_returns?.loss)}`,
        'Kelly budget':usd(item.kelly_budget_usd),
      }),
      'Recorded net receipt on win':exactMoney(cashflows.win?.net_receipt_usd),
      'Recorded net receipt on loss':exactMoney(cashflows.loss?.net_receipt_usd),
      ...(cashflows.push ? {'Recorded net receipt on push':exactMoney(cashflows.push.net_receipt_usd)} : {}),
      ...(cashflows.void ? {'Recorded net receipt on void':exactMoney(cashflows.void.net_receipt_usd)} : {}),
      'Paper commitment':exactMoney(item.stake_usd),
      'Purchase':exactMoney(item.purchase_usd), Quantity:fee.quantity, 'Modeled entry fee':exactMoney(fee.entry_usd),
      'Expected profit at entry':exactMoney(item.expected_profit_usd),
    }, {sizing, fee_input:offer.fee_input, sized_calculation:sized, trade_evidence:trade, ...(depth ? {depth} : {})});
    if (!resultReview) {
      const result = evidence.sporting_result;
      evidenceSection(root, 'Sporting-result grading', 'This grade belongs to the original saved selection.', {
        'Sporting grade':resultLabel[item.grading?.state] || 'Unresolved',
        'Modeled P/L':item.grading?.pnl_usd == null ? 'Unavailable' : usd(item.grading.pnl_usd),
        'Result known at':time(result?.known_at || item.grading?.released_at),
        Reason:label(item.grading?.reason),
      }, result || item.grading);
      root.append(details('Ticket identity, revisions and complete witness', value));
    }
  }
  root.append(evidenceLink('Export saved run and evidence', exportLink));
}
