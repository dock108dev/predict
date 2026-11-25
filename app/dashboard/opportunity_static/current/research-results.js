import {count, details, label, link, node, pairs, pct, stack, table, time, usd} from './workspace-ui.js';
import {selection, venue} from './workspace-format.js';
import {qualityComparison} from './research-quality.js';

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
const action = (title, href) => link(title, href, 'research-button');
const selectionGraded = grade => ['win', 'loss', 'push', 'void'].includes(grade?.state);

function dropdown(title, options, current, change) {
  const field = node('label', title), select = node('select');
  select.append(...options.map(([value, text]) => new Option(text, value)));
  select.value = current;
  select.onchange = () => change(select.value);
  field.append(select);
  return field;
}

function statusNotice(analysis, pinned, summary) {
  const state = analysis.status?.state;
  const notice = node('div', undefined, 'workspace-notice results-status');
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
  const message = historical ? `Historical result · ${reportStates[reportingState] || 'Published'}`
    : analysis.error ? 'Result analysis unavailable' : reportStates[summary ? reportingState : state] || 'Reading result analysis…';
  notice.append(node('strong', message));
  if (analysis.error) notice.append(node('p', analysis.error));
  else if (historical) notice.append(node('p', 'This version shows the scores and grades published at its recorded time. Open the latest result to check for changes.'));
  else if (analysis.status?.stale) notice.append(node('p', 'Retained evidence or grading inputs changed. The previous report is available in result history. Current grades will appear after processing.'));
  else if (state === 'collecting' || state === 'update_pending') notice.append(node('p', 'The background worker will publish this report automatically from retained evidence.'));
  if (analysis.status?.reason && !historical) notice.append(node('p', label(analysis.status.reason)));
  const {observed_at, processed_at} = analysis.version || {};
  if (observed_at || processed_at) notice.append(node('p', [observed_at && `Result evidence observed ${time(observed_at)}`,
    processed_at && `Report published ${time(processed_at)}`].filter(Boolean).join(' · '), 'workspace-clocks'));
  return notice;
}

function coverageLine(coverage, games) {
  const scheduled = coverage.pending_games || 0;
  const gaps = games?.length ? games.filter(game => !captured(game) && !['pending', 'claimed'].includes(game.capture_status)).length
    : (coverage.missing_tracked_games || 0) + (coverage.untracked_games || 0);
  const context = [
    `${count(coverage.captured_games || 0)} frozen`,
    coverage.reconstructed_games && `${count(coverage.reconstructed_games)} reconstructed`,
    gaps && `${count(gaps)} ${gaps === 1 ? 'game' : 'games'} without retained T−10 evidence`,
    scheduled && `${count(scheduled)} awaiting capture`,
    coverage.expected_games == null ? 'Complete slate unknown' : `${count(coverage.expected_games)} expected games`,
  ];
  return node('p', `Capture coverage · ${context.filter(Boolean).join(' · ')}`, 'results-coverage');
}

function resultActions(analysis, navigation) {
  const group = node('div', undefined, 'workspace-links');
  const {version, versions, links} = analysis;
  if (links && (navigation.pinned || !analysis.status?.stale)) {
    for (const [type, title] of [['report', 'Export graded report'], ['games', 'Export game rows'], ['trades', 'Export trade rows']]) {
      if (links[type]) group.append(action(title, links[type]));
    }
  }
  if (version) group.append(link('Link to this result version', navigation.href({result:version.id})));
  if (navigation.pinned) group.append(link('Open latest result', navigation.href({result:null})));
  if (versions?.length) {
    const history = node('details'), rows = node('ul');
    history.append(node('summary', 'Result history'), rows);
    for (const item of versions) {
      const row = node('li');
      const entry = link(`${time(item.processed_at)} · ${item.id.slice(0, 12)}`, navigation.href({result:item.id}));
      if (item.id === version?.id) entry.setAttribute('aria-current', 'true');
      row.append(entry);
      rows.append(row);
    }
    if (version) history.append(details('Exact result version and evidence revision', version));
    group.append(history);
  }
  return group;
}

function summaryView(summary, gameCount) {
  const partial = summary.resolved > 0 && summary.unresolved > 0;
  const metrics = pairs({
    Tickets:count(summary.tickets), 'Games with tickets':count(summary.games), 'Games in report':count(gameCount),
    Staked:money(summary.stake_usd), 'Expected profit at entry':money(summary.expected_profit_usd),
    ...(partial ? {'Expected profit · resolved':money(summary.resolved_expected_profit_usd)} : {}),
    [partial ? 'Returned · resolved' : 'Returned']:money(summary.return_usd),
    [partial ? 'Modeled net P/L · resolved' : 'Modeled net P/L']:money(summary.pnl_usd),
    'Modeled ROI':summary.roi_percent != null ? `${summary.roi_percent}%` : summary.roi == null ? '—' : pct(summary.roi),
  }, 'workspace-stats');
  const graded = summary.tickets && summary.tickets === summary.resolved
    ? `${summary.tickets === 1 ? '1 selected ticket graded' : `All ${count(summary.tickets)} selected tickets graded`} · ` : '';
  const row = node('p', `${graded}${count(summary.wins)} wins · ${count(summary.losses)} losses · ${count(summary.pushes)} pushes · ${count(summary.voids)} voids · ${count(summary.unresolved)} unresolved (${money(summary.unresolved_stake_usd)} staked)`, 'results-counts');
  const population = partial
    ? `ROI uses ${money(summary.roi_stake_usd)} in resolved stake. Unresolved stakes are tracked separately.`
    : summary.roi != null ? `ROI uses ${money(summary.roi_stake_usd)} in total stake.` : 'ROI is unavailable without resolved stake.';
  return [metrics, row, node('p', population, 'workspace-caption')];
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
  const content = node('div'), controls = node('div', undefined, 'workspace-form');
  const gameFilter = [
    ['all', 'All games'], ['traded', 'Games with trades'], ['zero', 'Zero qualifying trades'],
    ['frozen', 'Frozen T−10 only'], ['reconstructed', 'Retrospective reconstructions only'],
    ['missing', 'Missing capture'], ['unresolved', 'Unresolved trades'],
  ];
  panel.append(node('h3', 'Games'), controls, content);
  controls.append(dropdown('Show games', gameFilter, navigation.filter, filter => navigation.go({filter:filter === 'all' ? null : filter})));
  const games = report.games.filter(game => {
    const summary = portfolio.by_game[game.game_id];
    if (navigation.filter === 'traded') return summary?.tickets;
    if (navigation.filter === 'zero') return captured(game) && !summary?.tickets;
    if (navigation.filter === 'frozen') return ['captured', 'frozen'].includes(game.capture_status);
    if (navigation.filter === 'reconstructed') return game.capture_status === 'reconstructed';
    if (navigation.filter === 'missing') return !captured(game) && !['pending', 'claimed'].includes(game.capture_status);
    if (navigation.filter === 'unresolved') return summary?.unresolved;
    return true;
  });
  if (!games.length) content.append(node('p', 'No games match this view.'));
  else content.append(table(['Game', 'Score / status', 'Trades', 'Staked', 'Returned', 'P/L', 'Capture status'], games.map(game => {
    const summary = portfolio.by_game[game.game_id];
    const gameLink = node('div');
    const usable = captured(game);
    gameLink.append(link(game.title, navigation.href({game:game.game_id, trade:null})), node('small', time(game.starts_at)));
    return [gameLink, scoreCell(game.result),
      usable ? count(summary?.tickets || 0) : 'Unavailable', money(usable ? summary?.stake_usd : null),
      money(usable ? summary?.return_usd : null), money(usable ? summary?.pnl_usd : null),
      captureDescription(game, summary)];
  })));
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
  const matching = allTickets.filter(ticket => navigation.tradeFilter === 'all' || (navigation.tradeFilter === 'unresolved'
    ? !selectionGraded(ticket.grade) : ticket.grade?.state === navigation.tradeFilter));
  const trade = allTickets.find(ticket => ticket.id === navigation.trade);
  const headline = node('h3', game.title);
  headline.tabIndex = -1;
  const resultStatus = resultStates[game.result?.state] || 'Result';
  const scoreLine = score(game.result);
  panel.append(link('All games', navigation.href({game:null, trade:null, trade_filter:null})), headline,
    node('p', resultStatus === scoreLine ? scoreLine : `${resultStatus} · ${scoreLine}`, 'results-score'),
    node('p', `${time(game.starts_at)} · ${captureDescription(game, summary)}`, 'workspace-caption'));
  if (navigation.coverageHref) panel.append(link('Game coverage and issue decisions', navigation.coverageHref(game)));
  if (!trade) panel.append(resultEvidence(game.result));
  if (game.capture_reason) panel.append(node('p', label(game.capture_reason), 'workspace-caption'));
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
  if (trade) panel.append(tradeView(trade, game, navigation, inspectTrade));
  else if (navigation.trade) panel.append(node('p', 'That trade is unavailable in this portfolio.'));
  const controls = node('div', undefined, 'workspace-form');
  controls.append(dropdown('Show trades', [['all', 'All grades'], ['win', 'Wins'], ['loss', 'Losses'], ['push', 'Pushes'], ['void', 'Voids'], ['unresolved', 'Unresolved']],
    navigation.tradeFilter, filter => navigation.go({trade_filter:filter === 'all' ? null : filter})));
  panel.append(node('h4', 'Selected paper trades'), controls);
  if (!matching.length) panel.append(node('p', 'No trades match this view.'));
  else panel.append(table(['Selection', 'Venue', 'Odds', 'Probability', 'EV', 'Stake', 'Expected profit', 'Grade', 'Return', 'P/L'], matching.map(ticket => {
    const selectionLink = link(ticketSelection(ticket), navigation.href({trade:ticket.id}));
    if (trade?.id === ticket.id) selectionLink.setAttribute('aria-current', 'true');
    return [selectionLink, venue(ticket.venue), ticket.posted_odds, pct(ticket.probability), pct(ticket.ev), money(ticket.stake_usd),
      money(ticket.expected_profit_usd), gradeStates[ticket.grade?.state] || label(ticket.grade?.state), money(ticket.return_usd), money(ticket.pnl_usd)];
  })));
  return panel;
}

function tradeView(trade, game, navigation, inspectTrade) {
  const panel = node('section', undefined, 'workspace-panel workspace-card paper-result-trade');
  const grade = trade.grade || {};
  const headline = node('h4', ticketSelection(trade) + ' · ' + venue(trade.venue));
  headline.tabIndex = -1;
  const calculation = node('div');
  panel.append(link('Back to game trades', navigation.href({trade:null})), headline,
    node('p', gradeStates[grade.state] || 'Unresolved', 'results-score'));
  if (grade.explanation || grade.reason) panel.append(node('p', grade.explanation || label(grade.reason)));
  panel.append(pairs({
    [trade.capture_origin === 'reconstructed' ? 'Reconstructed probability' : 'Frozen probability']:pct(trade.probability),
    'Net EV at commitment':pct(trade.ev), Stake:money(trade.stake_usd),
    'Expected profit · stake × net EV':money(trade.expected_profit_usd), 'Modeled return':money(trade.return_usd),
    'Modeled P/L · return minus stake':money(trade.pnl_usd), 'Capture origin':label(trade.capture_origin),
  }), resultEvidence(game.result, grade), details('Exact grading inputs and ticket identity', trade), calculation);
  inspectTrade(calculation, trade);
  return panel;
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

export function renderResults(root, selected, analysis, navigation, inspectTrade) {
  const header = node('section', undefined, 'workspace-panel workspace-card paper-result-summary');
  header.append(node('h2', selected.run.title), node('p', `${selected.run.date} Eastern · Paper results`, 'workspace-caption'));
  const controls = node('div', undefined, 'results-controls');
  const dates = node('div', undefined, 'workspace-form');
  dates.append(dropdown('Saved game date (Eastern)', navigation.dates.map(day => [day, day]), selected.run.date, navigation.changeDate));
  const variantsNav = node('nav', undefined, 'workspace-variant');
  variantsNav.setAttribute('aria-label', 'Paper portfolios');
  for (const [name, title] of Object.entries(variants)) {
    const entry = action(title, navigation.href({variant:name}));
    if (name === navigation.variant) entry.setAttribute('aria-current', 'true');
    variantsNav.append(entry);
  }
  controls.append(dates, variantsNav);
  const report = navigation.pinned || !analysis.status?.stale ? analysis.report : null;
  const portfolio = report?.portfolios?.[navigation.variant];
  const usable = report?.games.some(captured);
  header.append(controls, statusNotice(analysis, navigation.pinned, portfolio?.summary), coverageLine(report?.coverage || selected.run.coverage || {}, report?.games));
  if (portfolio && usable) header.append(...summaryView(portfolio.summary, report.games.length));
  else {
    const original = selected.report.portfolios[navigation.variant];
    const originalUsable = selected.report.games?.some(game => captured({capture_status:game.status}));
    if (!portfolio && (originalUsable || original.count)) {
      header.append(pairs({Tickets:count(original.count), 'Games with tickets':count(original.unique_games),
        Staked:money(original.turnover_usd), 'Expected profit at entry':money(original.expected_profit_usd)}, 'workspace-stats'));
    } else header.append(node('p', 'Paper financials require usable T−10 evidence.'));
  }
  header.append(node('p', 'Paper outcomes use recorded fee and quoted-size assumptions. Actual fees, executable size and venue settlement are unverified. A venue-native contract ID is shown when retained.', 'workspace-caption'), resultActions(analysis, navigation));
  root.replaceChildren(header);
  if (!portfolio) return;
  const game = report.games.find(row => row.game_id === navigation.game);
  if (game) root.append(gameView(game, portfolio, navigation, inspectTrade));
  else {
    if (navigation.game) root.append(node('p', 'That game is unavailable in this report.'));
    const quality = qualityComparison(analysis.quality);
    if (quality && usable) root.append(quality);
    root.append(gamesView(report, portfolio, navigation));
  }
  if (usable) root.append(breakdowns(portfolio));
}
