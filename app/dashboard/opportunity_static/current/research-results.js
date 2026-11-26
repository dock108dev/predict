import {count, details, label, link, node, pairs, pct, stack, table, time, usd} from './workspace-ui.js';
import {number, selection, venue} from './workspace-format.js';
import {qualityComparison} from './research-quality.js';
import {band, comparisonCounts, exactMoney, fixedProfitFields, mainFirstRule, sizingTitle, workbenchPeriod, workbenchSizing} from './research-campaigns.js';
import {portfolioSelectionFields} from './research-run.js';
import {familyFilters, gameLeague, gradeFilters, ledgerPageSizes, ledgerViewModel, matchesTradeFilters,
  requestedTrade, selectedSport, sportFilters, tradeFilters, tradeSorts, venueFilters} from './research-ledger.js';

const variants = {best_venue:'Best venue only', all_venues:'All qualifying venues'};
const reportStates = {
  collecting:'Collecting evidence', awaiting_results:'Awaiting results', partially_graded:'Partially graded',
  graded:'Graded', unresolved:'Grading unresolved', no_selected_tickets:'No selected paper trades',
  update_pending:'Result update pending', failed:'Result update failed',
};
const gradeStates = {
  pending:'Pending result', win:'Win', loss:'Loss', push:'Push', void:'Void',
  conflict:'Conflicting result', conflicting:'Conflicting result', unsupported:'Unsupported', unresolved:'Unresolved',
};
const captureStates = {
  captured:'Frozen T−10', frozen:'Frozen T−10', reconstructed:'Reconstructed T−10',
  pending:'Awaiting T−10', claimed:'Capturing T−10', no_task:'No T−10 task',
  missed:'Missed T−10', failed:'Failed capture', refused:'Capture refused', cancelled:'Capture canceled',
  superseded_by_reschedule:'Capture superseded',
};
const resultStates = {
  final:'Final', pending:'Awaiting result', missing:'Awaiting result', conflicting:'Conflicting results',
  conflict:'Conflicting results', unresolved:'Result unresolved', canceled:'Canceled', cancelled:'Canceled',
  postponed:'Postponed', removed:'Removed',
};
const captured = game => ['captured', 'frozen', 'reconstructed'].includes(game.capture_status);
const money = value => value == null ? '—' : usd(value);
const ticketSelection = ticket => selection({...ticket, selection_label:ticket.label});
const gradeLabel = ticket => gradeStates[ticket.grade?.state] || 'Unresolved';
const marketContext = ticket => [
  {moneyline:'Moneyline', spread:'Spread', total:'Total'}[ticket.family] || label(ticket.family),
  {full_game:'Full game', first_half:'First half', second_half:'Second half', '1h':'First half', '2h':'Second half'}[ticket.period] ||
    (ticket.period ? label(ticket.period) : 'Period not recorded'),
].join(' · ');
const action = (title, href) => link(title, href, 'research-button');
export function oddsBreakdown(buckets, sizing = '') {
  if (!buckets?.length) return null;
  const title = sizing ? `Posted odds buckets · ${sizing}` : 'Posted odds buckets';
  const panel = node('details');
  const headers = ['Posted American odds', 'Selected trades', 'Graded trades', 'Stake', 'Stake share',
    'Expected paper profit', 'Expected ROI', 'Paper P/L', 'Realized ROI'];
  const scroll = table(headers, buckets.map(({label, stake_share_percent:share, summary}) => [
    label, count(summary.tickets), count(summary.resolved), money(summary.stake_usd),
    share == null ? '—' : `${share}%`, money(summary.expected_profit_usd),
    summary.expected_roi_percent == null ? '—' : `${summary.expected_roi_percent}%`,
    money(summary.pnl_usd), summary.roi_percent == null ? '—'
      : `${summary.roi_percent}% on ${money(summary.roi_stake_usd)} graded stake`,
  ]));
  scroll.firstElementChild.setAttribute('aria-label', title);
  panel.append(node('summary', title), node('p',
    'Grouped by each selected trade’s posted American odds. Expected ROI uses all selected stake. Realized ROI uses graded stake.',
    'workspace-caption'), scroll);
  return panel;
}

const focusKey = (element, key) => {
  element.dataset.workbenchFocus = key;
  return element;
};

function dropdown(title, options, current, change, key) {
  const field = node('label'), caption = node('span', title), select = node('select');
  select.append(...options.map(([value, text]) => new Option(text, value)));
  select.value = current;
  select.onchange = () => change(select.value);
  if (key) {
    caption.id = 'result-label-' + key;
    select.setAttribute('aria-labelledby', caption.id);
    focusKey(select, key);
  }
  field.append(caption, select);
  return field;
}

function keyboardScroll(container, name, navigation) {
  if (navigation.embedded) {
    container.tabIndex = 0;
    container.setAttribute('role', 'region');
    container.setAttribute('aria-label', name);
  }
  return container;
}

function statusNotice(analysis, pinned, summary, compact=false) {
  const state = analysis.status?.state;
  const notice = node('div', undefined, compact ? 'results-status-compact' : 'workspace-notice results-status');
  notice.setAttribute('role', 'status');
  const historical = pinned && analysis.version && (analysis.status?.stale ||
    (analysis.status?.latest_version && analysis.version.id !== analysis.status.latest_version));
  if (analysis.status?.stale || analysis.error || historical) notice.dataset.state = 'incomplete';
  let reportingState = analysis.report?.status;
  if (summary?.tickets) {
    if (summary.resolved === summary.tickets) reportingState = 'graded';
    else if (summary.resolved) reportingState = 'partially_graded';
    else reportingState = summary.grade_counts?.pending ? 'awaiting_results' : 'unresolved';
  }
  const games=analysis.report?.games;
  const emptyEvidence=games && !games.some(captured);
  const awaitingCapture=emptyEvidence && games.some(game=>['pending','claimed'].includes(game.capture_status));
  const message = historical ? `Historical result · ${reportStates[reportingState] || 'Published'}`
    : analysis.error ? 'Result analysis unavailable'
      : emptyEvidence ? awaitingCapture ? 'Awaiting T−10 capture' : 'Missing usable T−10 evidence'
        : reportStates[summary ? reportingState : state] || 'Reading result analysis…';
  notice.append(node('strong', message));
  if (compact) {
    if (analysis.error) notice.append(node('span', analysis.error));
    return notice;
  }
  if (analysis.error) notice.append(node('p', analysis.error));
  else if (!historical && analysis.status?.stale) notice.append(node('p', 'Retained evidence or grading inputs changed. The previous report is available in result history. Current grades will appear after processing.'));
  else if (!historical && (state === 'collecting' || state === 'update_pending')) notice.append(node('p', 'The background worker will publish this report automatically from retained evidence.'));
  if (analysis.status?.reason && !historical) notice.append(node('p', label(analysis.status.reason)));
  return notice;
}

function coverageLine(coverage, games) {
  const pending = game => ['pending', 'claimed'].includes(game.capture_status);
  const reviewed = games?.length ?? coverage.known_games ?? coverage.dated_eligible_games ?? coverage.tracked_games;
  const finals = games?.filter(game => game.result?.state === 'final').length ?? coverage.final_games;
  const frozen = games?.filter(game => ['captured', 'frozen'].includes(game.capture_status)).length ?? coverage.captured_games;
  const reconstructed = games?.filter(game => game.capture_status === 'reconstructed').length ?? coverage.reconstructed_games;
  const scheduled = games?.filter(pending).length ?? coverage.pending_games;
  const gaps = games?.filter(game => !captured(game) && !pending(game)).length ?? coverage.missing_capture_games ??
    ((coverage.missing_tracked_games || 0) + (coverage.untracked_games || 0));
  const context = [
    reviewed != null && `${count(reviewed)} ${reviewed === 1 ? 'game' : 'games'} reviewed`,
    finals != null && `${count(finals)} ${finals === 1 ? 'final' : 'finals'}`,
    frozen != null && `${count(frozen)} frozen`,
    reconstructed && `${count(reconstructed)} reconstructed`,
    gaps && `${count(gaps)} ${gaps === 1 ? 'game' : 'games'} without retained T−10 evidence`,
    scheduled && `${count(scheduled)} awaiting capture`,
    coverage.expected_games == null ? 'Complete slate unknown' : `${count(coverage.expected_games)} expected games`,
  ];
  return node('p', `Capture coverage · ${context.filter(Boolean).join(' · ')}`, 'results-coverage');
}

function resultActions(analysis, navigation) {
  const group = node('div', undefined, 'workspace-links result-actions');
  const {version, versions, links} = analysis;
  if (links && (navigation.pinned || !analysis.status?.stale)) {
    for (const [type, title] of [['report', 'Export graded report'], ['games', 'Export game rows'], ['trades', 'Export trade rows']]) {
      if (links[type]) group.append(action(title, links[type]));
    }
  }
  if (version) group.append(link('Link to this result version', navigation.href({result:version.id})));
  if (navigation.pinned && !navigation.embedded) group.append(link('Open latest result', navigation.href({result:null})));
  if (versions?.length || version) {
    const history = node('details'), rows = node('ul');
    history.append(node('summary', 'Result history'));
    const {observed_at, processed_at} = version || {};
    if (observed_at || processed_at) history.append(node('p', [observed_at && `Result evidence observed ${time(observed_at)}`,
      processed_at && `Report published ${time(processed_at)}`].filter(Boolean).join(' · '), 'workspace-clocks'));
    for (const item of versions || []) {
      const row = node('li');
      const entry = link(`${time(item.processed_at)} · ${item.id.slice(0, 12)}`, navigation.href({result:item.id}));
      if (item.id === version?.id) entry.setAttribute('aria-current', 'true');
      row.append(entry);
      rows.append(row);
    }
    if (rows.childElementCount) history.append(rows);
    if (version) history.append(details('Exact result version and evidence revision', version));
    group.append(history);
  }
  return group;
}

function summaryView(summary, gameCount) {
  const partial = summary.resolved > 0 && summary.unresolved > 0;
  const metrics = pairs({
    [partial ? 'Modeled net P/L · resolved' : 'Modeled net P/L']:money(summary.pnl_usd),
    Staked:money(summary.stake_usd),
    [partial ? 'Returned · resolved' : 'Returned']:money(summary.return_usd),
    'Expected profit at entry':money(summary.expected_profit_usd),
    'Modeled ROI':summary.roi_percent != null ? `${summary.roi_percent}%` : summary.roi == null ? '—' : pct(summary.roi),
    ...(partial ? {'Expected profit · resolved':money(summary.resolved_expected_profit_usd)} : {}),
  }, 'workspace-stats');
  const pnl = metrics.querySelector('dd');
  if (number(summary.pnl_usd) > 0) pnl.classList.add('result-positive');
  if (number(summary.pnl_usd) < 0) pnl.classList.add('result-negative');
  const graded = summary.tickets && summary.tickets === summary.resolved
    ? summary.tickets === 1 ? '1 selected ticket graded' : `All ${count(summary.tickets)} selected tickets graded`
    : `${count(summary.tickets)} ${summary.tickets === 1 ? 'selected ticket' : 'selected tickets'}`;
  const population = partial
    ? `ROI uses ${money(summary.roi_stake_usd)} in resolved stake. Unresolved stakes are tracked separately.`
    : summary.roi != null ? `ROI uses ${money(summary.roi_stake_usd)} in total stake.` : 'ROI is unavailable without resolved stake.';
  const section = node('section', undefined, 'result-portfolio-summary');
  section.append(node('h3', 'Full portfolio'), metrics,
    node('p', `${graded} · ${count(summary.games)} of ${count(gameCount)} games with trades · ${count(summary.wins)} wins · ${count(summary.losses)} losses · ${count(summary.pushes)} pushes · ${count(summary.voids)} voids · ${count(summary.unresolved)} unresolved (${money(summary.unresolved_stake_usd)} staked)`, 'results-counts'),
    node('p', population, 'workspace-caption'));
  return section;
}

function score(result = {}) {
  const name = team => typeof team === 'string' ? team : team?.name || team?.id;
  const available = result.away_score != null && result.home_score != null;
  const overtime = result.overtime_periods > 1 ? `(${result.overtime_periods}OT)` : result.overtime_periods === 1 ? '(OT)' : null;
  return available ? [name(result.away), result.away_score, '–', name(result.home), result.home_score, overtime].filter(value => value != null).join(' ')
    : resultStates[result.state] || label(result.state || 'pending');
}

function scoreCell(result = {}) {
  const status = resultStates[result.state] || label(result.state || 'pending');
  const value = score(result);
  return stack(value, value === status ? null : status);
}

function captureDescription(game, summary) {
  const state = captureStates[game.capture_status] || label(game.capture_status);
  const description = captured(game) ? (summary?.tickets ? '' : 'Zero qualifying trades')
    : ['pending', 'claimed'].includes(game.capture_status) ? 'Capture outstanding' : 'No retained T−10 evidence';
  const original = game.original_capture_status && game.original_capture_status !== game.capture_status
    ? `Original task ${label(game.original_capture_status)}` : null;
  return [state, description, original].filter(Boolean).join(' · ');
}

function gamesView(report, portfolio, navigation) {
  const panel = node('section', undefined, 'workspace-panel paper-result-games');
  const content = node('div'), controls = node('div', undefined, 'workspace-form result-ledger-controls');
  const gameFilter = [
    ['all', 'All games'], ['traded', 'Games with trades'], ['zero', 'Zero qualifying trades'],
    ['frozen', 'Frozen T−10 only'], ['reconstructed', 'Retrospective reconstructions only'],
    ['missing', 'Missing capture'], ['missing_results', 'Started games without a usable final'],
    ['unresolved', 'Unresolved trades'],
  ];
  panel.append(node('h3', 'Games'), controls, content);
  const sport = selectedSport(navigation.params.game_sport);
  controls.append(dropdown('Sport', sportFilters, sport,
    value => navigation.go({game_sport:value === 'all' ? null : value, ledger_view:'games'}), 'game-sport'),
    dropdown('Show games', gameFilter, navigation.filter,
      filter => navigation.go({filter:filter === 'all' ? null : filter, ledger_view:'games'}), 'game-filter'));
  const now = Date.now();
  const games = report.games.filter(game => {
    if (sport !== 'all' && gameLeague(game, navigation.config) !== sport) return false;
    const summary = portfolio.by_game[game.game_id];
    if (navigation.filter === 'traded') return summary?.tickets;
    if (navigation.filter === 'zero') return captured(game) && !summary?.tickets;
    if (navigation.filter === 'frozen') return ['captured', 'frozen'].includes(game.capture_status);
    if (navigation.filter === 'reconstructed') return game.capture_status === 'reconstructed';
    if (navigation.filter === 'missing') return !captured(game) && !['pending', 'claimed'].includes(game.capture_status);
    if (navigation.filter === 'missing_results') return Date.parse(game.starts_at) <= now &&
      ['pending','missing','unresolved','conflicting','conflict'].includes(game.result?.state);
    if (navigation.filter === 'unresolved') return summary?.unresolved;
    return true;
  });
  if (!games.length) content.append(node('p', 'No games match this view.'));
  else content.append(keyboardScroll(table(['Game', 'Score / status', 'Trades', 'Staked', 'Returned', 'P/L', 'Capture status'], games.map(game => {
    const summary = portfolio.by_game[game.game_id];
    const gameLink = node('div');
    const usable = captured(game);
    gameLink.append(link(game.title, navigation.href({game:game.game_id, trade:null})),
      node('small', [gameLeague(game, navigation.config), time(game.starts_at)].filter(Boolean).join(' · ')));
    return [gameLink, scoreCell(game.result),
      usable ? count(summary?.tickets || 0) : 'Unavailable', money(usable ? summary?.stake_usd : null),
      money(usable ? summary?.return_usd : null), money(usable ? summary?.pnl_usd : null),
      captureDescription(game, summary)];
  })), 'Game rows', navigation));
  return panel;
}

function resultEvidence(result, grade) {
  const panel = node('details', undefined, 'results-provenance');
  panel.append(node('summary', 'Retained result evidence'), pairs({
    'Observed at':time(result?.observed_at), 'Result status':resultStates[result?.state] || label(result?.state),
    ...(grade ? {'Grade identity':grade.id, 'Result evidence identities':grade.evidence_ids?.join(', ')} : {}),
  }));
  if (result?.reason) panel.append(node('p', label(result.reason)));
  for (const evidence of result?.evidence || []) {
    const title = label(evidence.source || evidence.provider || evidence.kind || 'retained result');
    const entry = details(title, evidence);
    if (typeof evidence.url === 'string' && /^\/api\/(?:workspace\/mens-d1\/(?:receipts|provider-results)|research\/workspace\/result-evidence)\/[a-f0-9]{64}$/.test(evidence.url))
      entry.append(link('Download original result receipt', evidence.url));
    else if (typeof evidence.receipt_id === 'string' && /^[a-f0-9]{64}$/.test(evidence.receipt_id))
      entry.append(link('Download original source receipt', '/api/workspace/mens-d1/receipts/' + evidence.receipt_id));
    panel.append(entry);
  }
  return panel;
}

function gameView(game, portfolio, navigation, inspectTrade) {
  const panel = node('section', undefined, 'workspace-panel paper-result-game');
  const summary = portfolio.by_game[game.game_id];
  const allTickets = portfolio.tickets.filter(ticket => ticket.game_id === game.game_id);
  const filters = tradeFilters({...navigation.params, trade_sport:null});
  const matching = allTickets.filter(ticket => matchesTradeFilters(ticket, filters));
  const requested = requestedTrade(matching,navigation.params);
  const hasSelection = navigation.trade || navigation.params.sizing_quote || navigation.params.sizing_bet;
  const trade = hasSelection ? requested || matching[0] : null;
  const headline = node('h3', game.title);
  headline.tabIndex = -1;
  const resultStatus = resultStates[game.result?.state] || 'Result';
  const scoreLine = score(game.result);
  panel.append(link('Back to games', navigation.href({game:null, trade:null, sizing_quote:null, sizing_bet:null, ledger_view:'games'})), headline,
    node('p', resultStatus === scoreLine ? scoreLine : `${resultStatus} · ${scoreLine}`, 'results-score'),
    node('p', `${time(game.starts_at)} · ${captureDescription(game, summary)}`, 'workspace-caption'));
  const coverage = navigation.coverageHref?.(game);
  if (coverage) panel.append(link('Game coverage and issue decisions', coverage));
  if (!trade) panel.append(resultEvidence(game.result));
  if (game.capture_reason) panel.append(node('p', label(game.capture_reason), 'workspace-caption'));
  if (game.selection_audit) {
    const {main=0,nearby_alternate:alternates=0,unranked=0}=game.selection_audit;
    panel.append(node('h4','Qualifying quotes reviewed'),pairs({
      'Main-line quotes':count(main), 'Ranked alternate quotes':count(alternates), 'Quotes without a verified main line':count(unranked),
    }));
  }
  if (!allTickets.length) {
    const message = captured(game) ? 'No trades qualified under this portfolio’s saved selection rules.'
      : ['pending', 'claimed'].includes(game.capture_status) ? 'T−10 evidence is still pending for this game.'
      : 'T−10 evidence is unavailable. The number of opportunities and modeled outcome are unknown.';
    panel.append(node('p', message));
    return panel;
  }
  const partial = summary?.resolved && summary.unresolved;
  panel.append(pairs({Tickets:count(summary?.tickets), Staked:money(summary?.stake_usd), 'Expected profit at entry':money(summary?.expected_profit_usd),
    ...(partial ? {'Expected profit · resolved':money(summary.resolved_expected_profit_usd)} : {}),
    [partial ? 'Returned · resolved' : 'Returned']:money(summary?.return_usd),
    [partial ? 'Modeled P/L · resolved' : 'Modeled P/L']:money(summary?.pnl_usd)}, 'workspace-stats'));
  if (hasSelection && !requested) panel.append(node('p', trade
    ? 'The requested trade is outside this view. Showing an available trade.'
    : 'The requested trade is outside this view.'));
  if (trade) panel.append(tradeView(trade, game, navigation, inspectTrade));
  const controls = node('div', undefined, 'workspace-form result-ledger-controls');
  const change = (key, value) => navigation.go({[key]:value === 'all' ? null : value, trade_page:1});
  controls.append(dropdown('Bet type', familyFilters, filters.family, value => change('trade_family', value), 'game-trade-family'),
    dropdown('Venue', venueFilters, filters.venue, value => change('trade_venue', value), 'game-trade-venue'),
    dropdown('Show trades', gradeFilters, filters.grade, value => change('trade_filter', value), 'game-trade-filter'));
  panel.append(node('h4', 'Selected paper trades'), controls);
  if (!matching.length) panel.append(node('p', 'No trades match this view.'));
  else panel.append(keyboardScroll(table(['Selection', 'Venue', 'Odds', 'Probability', 'EV', 'Stake', 'Expected profit', 'Grade', 'Return', 'P/L'], matching.map(ticket => {
    const selectionLink = link(ticketSelection(ticket), navigation.href({trade:ticket.id,sizing_quote:null,sizing_bet:null}));
    if (trade?.id === ticket.id) selectionLink.setAttribute('aria-current', 'true');
    return [selectionLink, venue(ticket.venue), ticket.posted_odds, pct(ticket.probability), pct(ticket.ev), money(ticket.stake_usd),
      money(ticket.expected_profit_usd), gradeLabel(ticket), money(ticket.return_usd), money(ticket.pnl_usd)];
  })), 'Game trade rows', navigation));
  return panel;
}

function tradeView(trade, game, navigation, inspectTrade) {
  const panel = node('section', undefined, 'workspace-panel workspace-card paper-result-trade');
  panel.dataset.tradeId = trade.id;
  const grade = trade.grade || {};
  const headline = node('h4', ticketSelection(trade) + ' · ' + venue(trade.venue));
  headline.tabIndex = -1;
  const calculation = node('div');
  panel.append(link('Back to game trades', navigation.href({trade:null,sizing_quote:null,sizing_bet:null})), headline,
    node('p', gradeStates[grade.state] || 'Unresolved', 'results-score'));
  if (grade.explanation || grade.reason) panel.append(node('p', grade.explanation || label(grade.reason)));
  panel.append(pairs({
    [trade.capture_origin === 'reconstructed' ? 'Reconstructed probability' : 'Frozen probability']:pct(trade.probability),
    'Net EV at commitment':pct(trade.ev), Stake:money(trade.stake_usd),
    'Expected profit · stake × net EV':money(trade.expected_profit_usd), 'Modeled return':money(trade.return_usd),
    'Modeled P/L · return minus stake':money(trade.pnl_usd), 'Capture origin':label(trade.capture_origin),
    ...portfolioSelectionFields(trade.portfolio_selection,trade.family),
  }), resultEvidence(game.result, grade), details('Exact grading inputs and ticket identity', trade), calculation);
  inspectTrade(calculation, trade);
  return panel;
}

function moneyCell(value) {
  const amount = number(value);
  return node('span', money(value), amount > 0 ? 'result-positive' : amount < 0 ? 'result-negative' : undefined);
}

function tradeInspector(trade, game, ledger, navigation, inspectTrade) {
  const panel = node('aside', undefined, 'workspace-panel result-inspector paper-result-trade');
  panel.setAttribute('aria-label', 'Trade inspector');
  panel.id = 'trade-inspector';
  panel.dataset.tradeId = trade.id;
  const headline = node('h3', ticketSelection(trade));
  headline.tabIndex = -1;
  const context = node('div', undefined, 'result-inspector-context');
  if (game) context.append(node('p', game.title));
  context.append(node('p', `${venue(trade.venue)} · ${marketContext(trade)} · ${gradeLabel(trade)}`));
  panel.append(link('Back to trade ledger', '#trade-ledger-title', 'result-inspector-back'), headline, context);
  if (ledger.missingSelection) {
    panel.append(node('p', 'The requested trade is outside this view. Showing an available trade.', 'workspace-caption'));
  } else if (ledger.changedVenue) {
    panel.append(node('p', 'Showing a different venue for the same exact bet. The original quote is outside this view.', 'workspace-caption'));
  } else if (ledger.selectionPage && ledger.selectionPage !== ledger.page) {
    panel.append(link('Show selected trade in ledger', navigation.href({trade_page:ledger.selectionPage})));
  }
  const probability = trade.capture_origin === 'reconstructed' ? 'Reconstructed probability' : 'Frozen probability';
  panel.append(pairs({
    'Posted odds':trade.posted_odds,
    [probability]:pct(trade.probability),
    'Net EV at commitment':pct(trade.ev),
    Stake:money(trade.stake_usd),
    'Expected profit at entry':money(trade.expected_profit_usd),
    'Modeled return':money(trade.return_usd),
    ...portfolioSelectionFields(trade.portfolio_selection,trade.family),
  }));
  const pnl = node('p', undefined, 'result-inspector-pnl');
  pnl.append(node('strong', 'Modeled P/L'), moneyCell(trade.pnl_usd));
  panel.append(pnl);
  if (game) {
    panel.append(node('p', score(game.result), 'results-score'),
      link('Game result and coverage', navigation.href({game:game.game_id, ledger_view:'games', trade:trade.id})));
  }
  const witness = node('div', undefined, 'result-inspector-provenance');
  const sizing = trade.sizing;
  witness.append(pairs({
    ...(sizing?.mode==='fixed_profit' ? fixedProfitFields(sizing) : {}),
    'T−10 origin':label(trade.capture_origin),
  }));
  panel.append(witness);

  const evidence = node('details', undefined, 'result-inspector-evidence'), calculation = node('div');
  evidence.append(node('summary', 'Trade calculation and frozen evidence'), calculation);
  const grade = trade.grade || {};
  if (grade.explanation || grade.reason) {
    const explanation = node('details');
    explanation.append(node('summary', 'Grading explanation'), node('p', grade.explanation || label(grade.reason)));
    panel.append(explanation);
  }
  panel.append(evidence, resultEvidence(game?.result, grade), details('Exact grading inputs and ticket identity', trade));
  const showWitness = value => {
    const {kelly, clocks} = value.evidence?.trade || {};
    const actualSizing = value.evidence?.trade?.sizing || value.ticket?.sizing || sizing;
    const age = clocks?.quote_age_at_receipt_seconds;
    witness.replaceChildren(pairs({
      ...(actualSizing?.mode==='fixed_profit' ? fixedProfitFields(actualSizing) : {
        'Kelly fraction':kelly?.multiplier ? `${kelly.multiplier} full Kelly` : 'Unknown',
        'Bankroll reference':kelly?.reference_bankroll_usd == null ? 'Unknown' : usd(kelly.reference_bankroll_usd),
      }),
      'T−10 origin':label(trade.capture_origin),
      'Quote age at receipt':age != null ? `${Number(age).toFixed(3)} seconds`
        : clocks?.quote_age_state === 'future' ? 'Source timestamp after receipt' : 'Unknown',
    }));
  };
  if (navigation.trade === trade.id) inspectTrade(calculation, trade, showWitness);
  else evidence.addEventListener('toggle', () => {
    if (evidence.open && !calculation.hasChildNodes()) inspectTrade(calculation, trade, showWitness);
  });
  return panel;
}

function ledgerTable(ledger, games, leagueFor, navigation, showInspector) {
  const headers = ['Selection', 'Venue', 'Odds', 'EV', 'Stake', 'Grade', 'Modeled P/L'];
  const scroll = table(headers, ledger.rows.map(ticket => {
    const game = games.get(ticket.game_id);
    const selected = showInspector && ticket.id === ledger.selected?.id;
    const exactSelection = ticketSelection(ticket);
    const selectionName = ticketSelection({...ticket, line:null});
    const pick = focusKey(link(exactSelection, navigation.href({
      game:null, ledger_view:null, trade:ticket.id, sizing_quote:null, sizing_bet:null, trade_page:ledger.page,
    }), 'result-ledger-selection'), 'trade-' + ticket.id);
    if (exactSelection !== selectionName) {
      const line = node('span', exactSelection.slice(selectionName.length + 1), 'result-ledger-exact-line');
      pick.replaceChildren(selectionName + ' ', line);
    }
    if (selected) pick.setAttribute('aria-current', 'true');
    const selectionCell = node('div');
    const family = familyFilters.find(([id]) => id === ticket.family)?.[1];
    const market = ticket.period === 'full_game' && family ? family : marketContext(ticket);
    const context = [leagueFor(ticket), market, game?.title].filter(Boolean).join(' · ');
    selectionCell.append(pick, node('small', context, 'result-ledger-game'));
    const grade = gradeLabel(ticket), tone = grade === 'Win' ? 'result-positive' : grade === 'Loss' ? 'result-negative' : '';
    return [selectionCell, venue(ticket.venue), ticket.posted_odds, pct(ticket.ev), money(ticket.stake_usd),
      node('span', grade, tone), moneyCell(ticket.pnl_usd)];
  }));
  scroll.classList.add('result-ledger-table');
  const tableElement = scroll.firstElementChild;
  tableElement.setAttribute('aria-labelledby', 'trade-ledger-title');
  tableElement.setAttribute('role', 'table');
  for (const group of tableElement.querySelectorAll('thead, tbody')) group.setAttribute('role', 'rowgroup');
  for (const row of tableElement.querySelectorAll('tr')) row.setAttribute('role', 'row');
  for (const column of tableElement.querySelectorAll('th')) column.setAttribute('role', 'columnheader');
  for (const cell of tableElement.querySelectorAll('td')) cell.setAttribute('role', 'cell');
  const direction = ledger.sort === 'ev_asc' ? 'ascending' : 'descending';
  const sortHeader = {ev_asc:3, ev_desc:3, stake_desc:4, pnl_desc:6}[ledger.sort];
  tableElement.querySelectorAll('th')[sortHeader].setAttribute('aria-sort', direction);
  tableElement.querySelector('a[aria-current]')?.closest('tr')?.classList.add('result-ledger-selected');
  return keyboardScroll(scroll, 'Trade rows', navigation);
}

function ledgerPagination(ledger, navigation) {
  const footer = node('div', undefined, 'result-ledger-pagination');
  if (ledger.pageCount === 1) {
    footer.append(node('p', `${count(ledger.total)} trades`));
    return footer;
  }
  const pager = node('nav');
  pager.setAttribute('aria-label', 'Trade pagination');
  for (const [title, page] of [['Previous', ledger.page - 1], ['Next', ledger.page + 1]]) {
    if (page >= 1 && page <= ledger.pageCount) {
      pager.append(focusKey(action(title, navigation.href({trade_page:page})), 'page-' + title.toLowerCase()));
    } else {
      const button = node('button', title, 'research-button');
      button.type = 'button';
      button.disabled = true;
      pager.append(button);
    }
  }
  footer.append(node('p', `${count(ledger.offset + 1)}–${count(ledger.offset + ledger.rows.length)} of ${count(ledger.total)} trades`), pager);
  return footer;
}

function tradeLedger(report, portfolio, selected, analysis, navigation, inspectTrade, views) {
  // The daily and freshness comparisons share the campaign's configured bucket edges.
  const buckets = analysis.quality?.fresh_target_only?.buckets || [];
  const {portfolios} = selected.report;
  const originals = portfolios.all_venues?.tickets || portfolios[navigation.variant]?.tickets || [];
  const games = new Map(report.games.map(game => [game.game_id, game]));
  const policy = {...navigation.config, ...selected.report.policy};
  const leagueFor = ticket => gameLeague(games.get(ticket.game_id), policy);
  const ledger = ledgerViewModel(portfolio.tickets, originals, buckets, navigation.params, leagueFor);
  const {params} = navigation;
  const showInspector = ledger.selected && (!navigation.embedded || params.trade || params.sizing_quote || params.sizing_bet);
  const section = node('section', undefined, 'result-workbench');
  const heading = node('div', undefined, 'result-ledger-heading');
  const title = node('h3', 'Trades');
  title.id = 'trade-ledger-title';
  title.tabIndex = -1;
  const controls = node('div', undefined, 'workspace-form result-ledger-controls');
  const change = (key, value) => navigation.go({[key]:value === 'all' ? null : value, trade_page:1});
  controls.append(dropdown('Sport', sportFilters, ledger.filters.sport, value => change('trade_sport', value), 'ledger-sport'),
    dropdown('Bet type', familyFilters, ledger.filters.family, value => change('trade_family', value), 'ledger-family'),
    dropdown('Venue', venueFilters, ledger.filters.venue, value => change('trade_venue', value), 'ledger-venue'),
    dropdown('Grade', gradeFilters, ledger.filters.grade, value => change('trade_filter', value), 'ledger-grade'));
  if (buckets.length > 1) {
    controls.append(dropdown('Screening EV', [['all', 'All EV buckets'], ...buckets.map(bucket => [bucket.minimum, band(bucket)])],
      ledger.bucket?.minimum || 'all', value => change('trade_ev', value), 'ledger-ev'));
  }
  controls.append(dropdown('Sort trades', tradeSorts, ledger.sort, value => change('trade_sort', value === 'ev_desc' ? null : value), 'ledger-sort'),
    dropdown('Rows per page', ledgerPageSizes.map(size => [size, size]), String(ledger.pageSize),
      value => change('trade_rows', value), 'ledger-rows'));
  if (ledger.subset) {
    const clear = focusKey(node('button', 'Clear filters', 'research-button'), 'ledger-sport');
    clear.type = 'button';
    clear.onclick = () => navigation.go({trade_sport:null, trade_family:null, trade_venue:null, trade_filter:null, trade_ev:null, trade_page:1});
    controls.append(clear);
  }
  heading.append(title, views, controls);
  section.append(heading);
  if (ledger.subset && ledger.total) {
    const {tickets, resolved, stake, pnl} = ledger.subset;
    const partial = resolved !== tickets;
    const caption = [
      `${count(tickets)} of ${count(portfolio.tickets.length)} trades`,
      `Staked ${money(stake)}`,
      `${partial ? 'Graded P/L' : 'P/L'} ${money(pnl)}`,
      ...(partial ? [`${count(resolved)} graded`] : []),
    ];
    section.append(node('p', caption.join(' · '), 'result-ledger-subset'));
  }
  if (!ledger.rows.length) {
    section.append(node('p', portfolio.tickets.length ? 'No trades match the current filters.'
      : 'No selected paper trades in this portfolio.'));
    return section;
  }
  const sheet = node('div', undefined, 'result-ledger');
  if (showInspector) sheet.append(link('Selected trade details', '#trade-inspector', 'result-jump-inspector'));
  sheet.append(ledgerTable(ledger, games, leagueFor, navigation, showInspector));
  if (!ledger.subset || ledger.pageCount > 1) sheet.append(ledgerPagination(ledger, navigation));
  if (showInspector) {
    const split = node('div', undefined, 'result-workbench-split');
    split.append(sheet, tradeInspector(ledger.selected, games.get(ledger.selected.game_id), ledger, navigation, inspectTrade));
    section.append(split);
  } else section.append(sheet);
  return section;
}

function breakdowns(portfolio) {
  const panel = node('details', undefined, 'workspace-panel');
  panel.append(node('summary', 'Results by venue and capture origin'));
  for (const [title, rows, name] of [['Venue', portfolio.by_venue, venue], ['Capture origin', portfolio.by_capture, label]]) {
    const entries = Object.entries(rows || {});
    if (entries.length) panel.append(table([title, 'Trades', 'Staked', 'Expected profit at entry', 'Expected profit · resolved',
      'Returned · resolved', 'P/L · resolved', 'Unresolved stake'],
      entries.map(([key, summary]) => [name(key), count(summary.tickets), money(summary.stake_usd), money(summary.expected_profit_usd),
        money(summary.resolved_expected_profit_usd), money(summary.return_usd), money(summary.pnl_usd), money(summary.unresolved_stake_usd)])));
  }
  return panel;
}

const sizingExclusionReasons = {
  captured_fee_inputs_unavailable:'Captured fee inputs unavailable',
  fixed_profit_fee_rounding_unverified:'Fee rounding could not be verified',
  fixed_profit_frozen_odds_mismatch:'Frozen odds conflict with the recorded price',
  fixed_profit_positive_win_unavailable:'No achievable positive net win profit',
  fixed_profit_price_or_quantity_grid_conflict:'Frozen price conflicts with the captured increment',
  fixed_profit_price_or_quantity_grid_unavailable:'Captured price or quantity increment unavailable',
  fixed_profit_quantity_increment_unavailable:'Captured quantity increment unavailable',
  fixed_profit_quantity_unit_unavailable:'Captured quantity unit unavailable',
  kelly_below_one_cent:'Kelly commitment below one cent',
  kelly_sizing_did_not_converge:'Kelly sizing did not converge',
  sized_ev_below_4pct:'Net EV after sizing fell below 4%',
  sized_ev_below_minimum:'Net EV after sizing fell below the minimum',
  sized_stake_below_minimum:'Stake below minimum after sizing',
  sizing_inputs_incomplete:'Sizing inputs incomplete',
  unsupported_cashflow_states:'Captured cashflows do not describe a supported bet',
};

function sizingExclusions(selected) {
  const counts = new Map();
  for (const game of selected.report.games || []) {
    for (const exclusion of game.sizing_exclusions || []) {
      const reason = sizingExclusionReasons[exclusion.reason] || label(exclusion.reason);
      counts.set(reason, (counts.get(reason) || 0) + 1);
    }
  }
  if (!counts.size) return null;
  const reasons = [...counts.entries()].sort(([a, x], [b, y]) => y - x || a.localeCompare(b));
  const panel = node('details', undefined, 'workspace-panel workspace-card');
  const minimum = selected.report.policy?.minimum_stake_usd;
  panel.append(node('summary', 'Sizing exclusions'),
    node('p', 'These frozen quotes were excluded while sizing this day’s paper trades. Counts are for the current sizing mode across the full day.'));
  if (minimum != null) panel.append(node('p', `Minimum stake for this run is ${exactMoney(minimum)} after sizing and modeled fees.`));
  panel.append(table(['Reason', 'Quotes'], reasons.map(([reason, total]) => [reason, count(total)])),
    link('Export dated offer ledger', '/api/research/workspace/runs/' + encodeURIComponent(selected.run.id) + '/offers'));
  return panel;
}

function sizingComparison(value, navigation) {
  const panel=node('details',undefined,'workspace-panel workspace-card');
  panel.append(node('summary','Sizing qualification and venue changes'),pairs(comparisonCounts(value.counts)));
  if(!value.changes?.length)return panel;
  const modes=['fixed_profit','kelly'];
  const headers=['Frozen quote',...modes.map(mode=>sizingTitle(navigation.config,mode))];
  panel.append(table(headers,value.changes.map(change=>{
    const selection=change.label ? ticketSelection(change) : change.frozen_quote_id?.slice(0,12) || 'Recorded quote';
    const title=`${selection} · ${venue(change.venue)}`;
    return [title,...modes.map(mode=>{
      const item=change[mode];
      if(!item)return 'Sizing unavailable';
      if(!item.qualifies) {
        const reason=item.reason ? label(item.reason) : 'Sizing unavailable';
        return item.ev==null ? reason : `${pct(item.ev)} · ${reason}`;
      }
      const caption=`${venue(item.venue)} · ${pct(item.ev)} · ${item.selected ? 'Selected' : 'Qualified'}`;
      if(!item.selected)return caption;
      const destination=mode===navigation.mode
        ? navigation.href({trade:item.ticket_id,sizing_quote:null,sizing_bet:null,trade_page:null,game:null,ledger_view:null,filter:null})
        : navigation.modeHref(mode,change);
      return link(caption,destination);
    })];
  })));
  return panel;
}

export function renderResults(root, selected, analysis, navigation, inspectTrade) {
  const header = node('section', undefined, 'workspace-panel workspace-card paper-result-summary');
  const dayHeader = node('div', undefined, 'result-day-header'), title = node('div');
  const policy = selected.report.policy || {};
  const report = navigation.pinned || !analysis.status?.stale ? analysis.report : null;
  const portfolio = report?.portfolios?.[navigation.variant];
  const usable = report?.games.some(captured);
  const context = [`${selected.run.date} Eastern`, 'Paper results',
    policy.minimum_ev && `EV ≥${pct(policy.minimum_ev)}`,
    policy.minimum_stake_usd != null && `Stake ≥${exactMoney(policy.minimum_stake_usd)}`,
    policy.portfolio_rule===mainFirstRule.id && mainFirstRule.title,
    navigation.mode==='fixed_profit' ? sizingTitle(navigation.config,navigation.mode)
      : policy.kelly_multiplier && `${policy.kelly_multiplier} full Kelly`];
  if (!navigation.embedded) {
    title.append(node('h2', selected.run.title), node('p', context.filter(Boolean).join(' · '), 'workspace-caption'));
    dayHeader.append(title, statusNotice(analysis, navigation.pinned, portfolio?.summary));
    header.append(dayHeader);
    const controls = node('div', undefined, 'results-controls');
    const dates = node('div', undefined, 'workspace-form result-date-control');
    dates.append(dropdown('Game date (Eastern)', navigation.dates.map(day => [day, day]), selected.run.date, navigation.changeDate, 'game-date'));
    const variantsNav = node('nav', undefined, 'workspace-variant');
    variantsNav.setAttribute('aria-label', 'Paper portfolios');
    for (const name of navigation.config.portfolios || Object.keys(variants)) {
      const entry = focusKey(action(variants[name], navigation.href({variant:name})), 'portfolio-' + name);
      if (name === navigation.variant) entry.setAttribute('aria-current', 'true');
      variantsNav.append(entry);
    }
    if (navigation.weeklyHref) controls.append(workbenchPeriod(navigation.href({view:null}), navigation.weeklyHref, 'daily'));
    const chosen=requestedTrade(portfolio?.tickets || [],navigation.params);
    const sizing=workbenchSizing(navigation.config,navigation.sizingModes,navigation.mode,mode=>navigation.modeHref(mode,chosen));
    if (sizing) controls.append(sizing);
    controls.append(dates, variantsNav);
    header.append(controls);
  }
  if (portfolio && usable && !navigation.embedded) {
    header.append(summaryView(portfolio.summary, report.games.length));
  } else if (!navigation.embedded && !usable) {
    const original = selected.report.portfolios[navigation.variant];
    const originalUsable = selected.report.games?.some(game => captured({capture_status:game.status}));
    if (!portfolio && (originalUsable || original.count)) {
      const saved = node('section', undefined, 'result-portfolio-summary');
      saved.append(node('h3', 'Full portfolio at entry'),
        pairs({Tickets:count(original.count), 'Games with tickets':count(original.unique_games),
          Staked:money(original.turnover_usd), 'Expected profit at entry':money(original.expected_profit_usd)}, 'workspace-stats'));
      header.append(saved);
    } else header.append(node('p', 'Paper financials require usable T−10 evidence.'));
  }
  const coverage = coverageLine(report?.coverage || selected.run.coverage || {}, report?.games);
  const tools = node('div', undefined, 'result-report-tools');
  tools.append(resultActions(analysis, navigation));
  if (!navigation.embedded) {
    const assumptions = node('details');
    assumptions.append(node('summary', 'Paper assumptions'), node('p', 'Paper outcomes use recorded fee and quoted-size assumptions. Actual fees, executable size and venue settlement are unverified. A venue-native contract ID is shown when retained.'));
    tools.append(assumptions);
    header.append(coverage);
  }
  if(navigation.editHref)tools.append(link('Edit as a new version',navigation.editHref));
  root.replaceChildren();
  if (!navigation.embedded) root.append(header);
  if (navigation.embedded && (!portfolio || !usable || navigation.pinned || analysis.status?.state === 'failed')) {
    const status = statusNotice(analysis, navigation.pinned, portfolio?.summary, true);
    if (navigation.pinned) status.append(link('Open latest result', navigation.href({result:null})));
    root.append(status);
  }
  const detailsPanel = node('details', undefined, 'result-metadata');
  detailsPanel.append(node('summary', 'Coverage, history and exports'));
  const exclusions = sizingExclusions(selected);
  if (!portfolio) {
    if (navigation.embedded) {
      detailsPanel.append(coverage, tools);
      if (exclusions) detailsPanel.append(exclusions);
      root.append(detailsPanel);
    } else {
      header.append(tools);
      if (exclusions) root.append(exclusions);
    }
    return;
  }
  const odds = usable && (!navigation.embedded || navigation.showSnapshotOdds) &&
    oddsBreakdown(portfolio.odds_buckets, navigation.showSnapshotOdds && navigation.embedded ? 'Saved result' : '');
  if (odds) (navigation.embedded ? detailsPanel : root).append(odds);
  const game = report.games.find(row => row.game_id === navigation.game);
  const showGames = Boolean(navigation.game || navigation.params.ledger_view === 'games' || navigation.filter !== 'all');
  const views = node('nav', undefined, 'workspace-variant result-view-controls');
  views.setAttribute('aria-label', 'Report detail');
  const trades = action('Trades', showGames ? navigation.href({ledger_view:null, game:null, filter:null}) : '#trade-ledger-title');
  const games = action('Games and coverage', navigation.href({ledger_view:'games', game:null}));
  (showGames ? games : trades).setAttribute('aria-current', 'page');
  views.append(trades, games);
  if (showGames) {
    root.append(views);
    if (game) root.append(gameView(game, portfolio, navigation, inspectTrade));
    else {
      if (navigation.game) root.append(node('p', 'That game is unavailable in this report.'));
      root.append(gamesView(report, portfolio, navigation));
    }
  } else {
    root.append(tradeLedger(report, portfolio, selected, analysis, navigation, inspectTrade, views));
  }
  if (navigation.embedded) {
    detailsPanel.append(coverage, tools);
    if (exclusions) detailsPanel.append(exclusions);
    root.append(detailsPanel);
  } else {
    root.append(tools);
    if (exclusions) root.append(exclusions);
  }
  if (usable && !navigation.embedded) {
    const comparison=selected.sizing_comparison?.[navigation.variant];
    if(comparison?.counts)root.append(sizingComparison(comparison,navigation));
    const quality = qualityComparison(analysis.quality);
    if (quality) root.append(quality);
    root.append(breakdowns(portfolio));
  }
}
