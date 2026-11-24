import {card, count, details, label, link, node, pairs, pct, stack, table, text, time, usd} from './workspace-ui.js';
import {selection, venue} from './workspace-format.js';

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
function coverageDescription(run) {
  if (run.coverage?.reconstructed_games) return 'This opportunity record separates original frozen calculations from calculations made later using retained responses received inside the T−10 window. Missing games and unseen source markets remain unavailable. Results integration is deferred.';
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
export function renderRun(root, {run, definition, report}, navigation) {
  const {variant, variantLink, ticketLink, gameLink, exportLink, definitionLink} = navigation;
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
  methods.append(node('p', `The game date uses Eastern time. Screening requires ${policy.recovered_checkpoints ? 'an original frozen checkpoint or an explicitly reconstructed T−10 response' : 'a valid frozen T−10 checkpoint'} and unrounded EV of at least ${pct(policy.minimum_ev)}. The replay uses ${pct(policy.kelly_multiplier)} of Kelly against a fixed ${usd(policy.reference_bankroll_usd)} sizing reference, without an aggregate budget cap or intraday compounding.`));
  methods.append(node('p', `Each paper commitment is repriced under the original fee assumption. ${feeModes.length ? feeModes.join(' · ') + '.' : 'No captured fee treatments are recorded for this run.'} Quoted price is assumed available at the modeled size.`));
  methods.append(node('p', 'Paper replay and sporting-result grading are recorded separately. Execution and actual venue settlement are unverified.'), definitionLink);
  intro.append(methods);
  const actions = node('div', undefined, 'workspace-links');
  actions.append(evidenceLink('Export saved run and evidence', exportLink));
  intro.append(actions);
  root.append(intro);

  const runs = node('section', undefined, 'workspace-panel');
  runs.append(node('h2', 'Portfolio variants'), node('p', 'Both variants use the same observations. Best venue keeps the highest qualifying sized EV for each exact bet; all qualifying venues keeps one ticket per exact bet per venue.'));
  const nav = node('div', undefined, 'workspace-variant');
  for (const [name, title] of Object.entries(variants)) {
    const action = evidenceLink(title, variantLink(name));
    if (name === variant) action.setAttribute('aria-current', 'true');
    nav.append(action);
  }
  runs.append(nav);
  const portfolio = report?.portfolios?.[variant];
  if (portfolio && (coverage.captured_games || coverage.reconstructed_games)) {
    runs.append(node('h3', variants[variant]), pairs({
      'Qualifying tickets':count(portfolio.count), 'Unique games':count(portfolio.unique_games),
      'Days represented':count(portfolio.days_represented), Turnover:usd(portfolio.turnover_usd),
      ...(!policy.defer_results ? {'Peak overlapping commitment':usd(portfolio.peak_committed_usd)} : {}),
    }, 'workspace-stats'));
    const resultGrid = node('div', undefined, 'workspace-grid');
    const resolved = card(policy.defer_results ? 'Results integration deferred' : 'Resolved tickets');
    resolved.append(node('p', policy.defer_results ? 'Results are deliberately excluded from this opportunity record. Cash releases and peak capital after results have not been modeled.' : portfolio.resolved ? 'Expected and realized-model values use the same resolved-ticket population.' : 'No tickets have a decisive sporting result in this saved run.'), pairs({
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
  dispositions.append(node('h2', 'Capture dispositions and exclusions'));
  if (report?.games?.length) dispositions.append(table(['Tracked game', 'T−10 capture', 'Qualifying offers', 'Evidence'], report.games.map(game => [
    stack(game.title, time(game.starts_at)),
    stack(statuses[game.status] || label(game.status), game.reason ? label(game.reason) : null),
    ['captured', 'reconstructed'].includes(game.status) ? count(game.tickets) : 'Unavailable',
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
export function renderSavedEvidence(root, value, {ticket, exportLink, gameLink}) {
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
    const recovered = item.source_kind === 'retrospective_raw_t10';
    root.append(node('h3', item.title + ' · ' + selection({ ...item, selection_label:item.label })));
    root.append(node('p', `${venue(item.venue)} at ${text(item.posted_odds)}. This modeled ticket uses the frozen T−10 offer and its recorded probability.`));
    if (recovered) root.append(node('p', `Calculated retrospectively from an original T−10 response. Reconstruction saved ${time(item.reconstructed_at)}. EV was not successfully frozen at T−10. Results integration is deferred.`, 'workspace-notice'));
    if (item.game_id) root.append(evidenceLink('Open frozen checkpoint', gameLink(item.game_id)));
    evidenceSection(root, 'Frozen quote', null, {
      'Posted odds':item.posted_odds, 'Original source price':original?.value ?? item.posted_odds,
      'Source time':time(item.times?.source_at), 'Receipt time':time(item.times?.received_at),
      'Modeled decision time':time(item.decision_at), 'Capture eligibility':recovered ? 'Retrospective reconstruction; original T−10 response' : 'Valid frozen T−10 checkpoint',
    }, {checkpoint:evidence.checkpoint, original_offer:offer});
    evidenceSection(root, 'Probability and screening', 'The captured probability is used for both screening and paper sizing.', {
      'Estimated outcome probability':pct(item.probability), 'Reference book':reference.book ? venue(reference.book) : 'Unknown',
      'Screening EV (rounded for display)':pct(item.screen_ev), 'EV at modeled commitment':pct(item.ev),
    }, {reference, exact_probability:item.probability, exact_screen_ev:item.screen_ev, exact_sized_ev:item.ev});
    evidenceSection(root, 'Paper sizing and fee treatment', capturedFee(item.fee_mode), {
      'Kelly budget':usd(item.kelly_budget_usd), 'Paper commitment':usd(item.stake_usd),
      'Purchase':usd(item.purchase_usd), Quantity:fee.quantity, 'Entry fee':usd(fee.entry_usd),
      'Expected profit at entry':usd(item.expected_profit_usd),
    }, {fee_input:offer.fee_input, sized_calculation:sized});
    const result = evidence.sporting_result;
    evidenceSection(root, 'Sporting-result grading', 'Actual execution and venue settlement remain unverified.', {
      'Sporting grade':resultLabel[item.grading?.state] || 'Unresolved',
      'Modeled P/L':item.grading?.pnl_usd == null ? 'Unavailable' : usd(item.grading.pnl_usd),
      'Result known at':time(result?.known_at || item.grading?.released_at),
      Reason:label(item.grading?.reason),
    }, result || item.grading);
    root.append(details('Ticket identity, revisions and complete witness', value));
  }
  root.append(evidenceLink('Export saved run and evidence', exportLink));
}
