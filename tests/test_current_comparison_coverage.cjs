// Authored captured pairs only: no provider calls, SQL, estimates or owner state.
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {Element} = require('./ev07_dom.cjs');
const {fixture, board, copy} = require('./current_board_fixture.cjs');
document.createTextNode = value => {const node = new Element('span'); node.textContent = value; return node;};
let dispatches = 0;
global.fetch = () => {dispatches++; throw Error('Coverage must remain local');};
const asset = name => pathToFileURL(path.resolve('app/dashboard/opportunity_static/current', name)).href;
const at = Date.parse('2026-10-17T17:00:00Z'), originalNow = Date.now;
Date.now = () => at;
const targets = [
  ['HOUJAC', '141502', '1198902', [['JAC','Jacksonville Jaguars','2397287','short'], ['HOU','Houston Texans','2397286','long']]],
  ['CARPHI', '141504', '1198904', [['CAR','Carolina Panthers','2397290','long'], ['PHI','Philadelphia Eagles','2397291','short']]],
  ['BALCLE', '141506', '1198906', [['BAL','Baltimore Ravens','2397294','long'], ['CLE','Cleveland Browns','2397295','short']]],
];
function display(state = 'current', codes = []) {
  return {state, current_until:new Date(at + 10000).toISOString(), reason_codes:codes, read_at:new Date(at).toISOString()};
}
function captured(q) {
  return copy({quote_id:q.quote_id, quote_revision:q.quote_revision, venue:q.venue, native_side:q.native_side,
    selection:q.selection, original:q.original, times:q.times, observation_display:q.observation_display});
}
function comparison(q, p) {
  return {available:true, metric:'lowest_current', value:'0.25', unit:'cents', exact:{numerator:'1',denominator:'4'},
    comparison_quote_id:p.quote_id, comparison_venue:p.venue, inputs:[captured(q), captured(p)], display_status:'current',
    reason_codes:[], selection_valid_until:new Date(at + 10000).toISOString()};
}
function slate() {
  const games = [], boards = [];
  for (const [event, usEvent, usMarket, teams] of targets) {
    const b = board(fixture.odds, event), g = {...copy(fixture.catalog.games[0]), game_key:event,
      title:teams.map(team => team[1]).join(' at '), participants:teams.map(team => ({id:team[0],name:team[1]})), start_at:new Date(at + 86400000).toISOString()};
    b.prices = [];
    for (const [id, name, usOutcome, usSide] of teams) {
      const q = copy(fixture.odds.prices[0]), p = copy(q);
      q.quote_id = 'KXNFLGAME-26OCT18' + event + '-' + id; q.venue = 'kalshi'; q.native_side = 'yes';
      p.quote_id = [usEvent, usMarket, usOutcome].join('/'); p.venue = 'polymarket_us'; p.native_side = usSide;
      for (const input of [q,p]) {
        input.selection = {...input.selection, participant:id, predicate:'win'};
        input.times = {source_at:new Date(at - 1000).toISOString(), received_at:new Date(at).toISOString()};
        input.observation_display = display(); input.freshness = {status:'current'};
      }
      q.current_comparison = comparison(q,p); p.current_comparison = comparison(p,q);
      q.gross_comparison = copy(q.current_comparison); p.gross_comparison = copy(p.current_comparison);
      b.prices.push(q,p);
    }
    b.rows = b.prices; games.push(g); boards.push(b);
  }
  return {games, boards, policy:boards[0].policy, read_at:new Date(at).toISOString()};
}
(async () => {
  const {scopedCurrentComparisonCoverage, appendComparisonCoverage} = await import(asset('comparison-coverage.js'));
  const {comparisonState, updateRelativeAges, preserveDisclosures} = await import(asset('board-elements.js'));
  const {createComparisonSlate} = await import(asset('comparison-slate-views.js'));
  const {createBoardViews} = await import(asset('stored-views.js'));
  const v = slate(), before = JSON.stringify(v), full = scopedCurrentComparisonCoverage(v.boards, at);
  assert.equal(full.current_games,3); assert.equal(full.current_team_outcomes,6);
  assert.equal(full.current_pairs,6,'twelve signed directions cover six underlying pairs');
  assert.equal(full.retained_observations,12);
  assert.equal(scopedCurrentComparisonCoverage([...v.boards,v.boards[0]],at).retained_observations,12,'duplicate boards do not duplicate observations');
  assert.equal(scopedCurrentComparisonCoverage([...v.boards,v.boards[0]],at).current_pairs,6);
  const noWin = copy(v.boards[0].prices[0]); noWin.quote_id = 'authored-not-win'; noWin.selection.predicate = 'not_win';
  const alternatives = scopedCurrentComparisonCoverage([{...v.boards[0],prices:[...v.boards[0].prices,noWin]}],at);
  assert.equal(alternatives.current_team_outcomes,2,'not_win never becomes an additional team-win outcome');
  assert.equal(alternatives.retained_observations,5,'native alternatives remain retained observations');
  // A cheaper historical comparison never substitutes for unavailable current support.
  const history = copy(v.boards[0]);
  for (const q of history.prices) q.current_comparison = {available:false,inputs:[],reason_code:'comparison_peer_missing'};
  assert.equal(scopedCurrentComparisonCoverage([history],at).current_team_outcomes,0);
  assert.equal(scopedCurrentComparisonCoverage([history],at).reasons.missing_peers.outcomes.size,2);
  // Selection boundaries and original source deadlines use the exact row helper.
  const boundary = copy(v);
  for (const q of boundary.boards[0].prices) q.current_comparison.selection_valid_until = new Date(at+1000).toISOString();
  assert.equal(comparisonState(boundary.boards[0].prices[0].current_comparison,at+999),'current');
  const pending = scopedCurrentComparisonCoverage(boundary.boards,at+1000);
  assert.equal(pending.current_games,2); assert.equal(pending.current_team_outcomes,4); assert.equal(pending.current_pairs,4);
  assert.equal(pending.reasons.pending_publication.outcomes.size,2);
  assert.equal(comparisonState(boundary.boards[0].prices[0].current_comparison,at+10001),'last_known');
  const expired = scopedCurrentComparisonCoverage(boundary.boards,at+10001);
  assert.equal(expired.current_games,0); assert.equal(expired.retained_observations,12);
  assert.equal(expired.reasons.stale_inputs.outcomes.size,6);
  const limited = copy(v.boards[0]);
  limited.prices[0].current_comparison = {available:false,inputs:[],reason_code:'comparison_selected_not_current',reason_codes:['source_expired']};
  limited.prices[1].current_comparison = {available:false,inputs:[],reason_code:'comparison_peer_matching_unsupported'};
  limited.prices[2].current_comparison = {available:false,inputs:[],reason_code:'scoring_overtime_facts_conflict'};
  limited.prices[3].current_comparison = {available:false,inputs:[],reason_code:'comparison_peers_not_current',reason_codes:['source_unavailable']};
  const causes = scopedCurrentComparisonCoverage([limited],at).reasons;
  assert.equal(causes.stale_inputs.observations.size,1);
  assert.equal(causes.unsupported_matching.outcomes.size,2);
  assert.equal(causes.unknown_inputs.observations.size,1,'source unavailability is distinct from stale clocks');
  const unpaired = copy(v.boards[0]);
  for (const q of unpaired.prices) {
    q.source_state = 'available'; q.source_health = {state:'available'};
    q.current_comparison = {available:false,inputs:[],reason_code:'comparison_peer_missing',reason_codes:[]};
  }
  assert.equal(scopedCurrentComparisonCoverage([unpaired],at+10000).reasons.stale_inputs.observations.size,0,'exact source deadline follows the row helper');
  const unpairedAged = scopedCurrentComparisonCoverage([unpaired],at+10001).reasons;
  assert.equal(unpairedAged.stale_inputs.observations.size,4,'unavailable pairs still reflect local aging of selected observations');
  assert.equal(unpairedAged.unknown_inputs.observations.size,0);
  unpaired.prices[0].source_health.state = 'paused';
  const unavailableAged = scopedCurrentComparisonCoverage([unpaired],at+10001).reasons;
  assert.equal(unavailableAged.stale_inputs.observations.size,3,'known source unavailability is not silently labeled stale');
  assert.equal(unavailableAged.unknown_inputs.observations.size,1);
  const changedPeer = copy(v.boards[0]);
  for (const q of changedPeer.prices) q.current_comparison = {available:false,inputs:[],reason_code:'comparison_peer_missing',reason_codes:['current_dependencies_changed']};
  const peerPending = scopedCurrentComparisonCoverage([changedPeer],at).reasons;
  assert.equal(peerPending.pending_publication.outcomes.size,2,'peer-only publication invalidation remains pending while own observations are current');
  assert.equal(peerPending.pending_publication.observations.size,4);
  assert.equal(peerPending.stale_inputs.observations.size,0);
  const staleMissing = copy(v.boards[0]);
  for (const q of staleMissing.prices) q.current_comparison = {available:false,inputs:[],reason_code:'comparison_selected_not_current',reason_codes:['source_expired','comparison_peer_missing']};
  const overlapping = scopedCurrentComparisonCoverage([staleMissing],at).reasons;
  assert.equal(overlapping.stale_inputs.outcomes.size,2);
  assert.equal(overlapping.missing_peers.outcomes.size,2,'a stale selected input does not conceal its missing peer');
  assert.equal(overlapping.stale_inputs.observations.size,4);
  assert.equal(overlapping.missing_peers.observations.size,4,'overlapping reasons retain independent observation counts');
  const root = new Element('section');
  appendComparisonCoverage(root,boundary.boards);
  const disclosure = root.querySelector('details'); disclosure.open = true;
  const summary = disclosure.querySelector('summary'); summary.focus();
  updateRelativeAges(root,at+1000);
  assert(root.querySelector('.current-comparison-counts').textContent.includes('2 games with current comparisons · 4 market outcomes covered · 12 retained price observations'));
  assert(root.querySelector('.comparison-coverage-reasons').textContent.includes('Pending publication: 2 market outcomes'));
  assert(disclosure.open); assert.equal(document.activeElement,summary);
  const content = new Element('section'), renderer = createComparisonSlate({content,onOriginal:()=>{},onDetails:()=>{}});
  renderer.draw(v,{view:'odds',filter:'all'});
  assert(content.querySelector('.current-comparison-counts').textContent.includes('3 games with current comparisons · 6 market outcomes covered · 12 retained price observations'));
  assert(!content.querySelector('.observation-coverage-details').open,'source details begin behind disclosure');
  renderer.draw(v,{view:'odds',filter:'all',game:'CARPHI'});
  assert(content.querySelector('.current-comparison-counts').textContent.includes('1 game with current comparisons · 2 market outcomes covered · 4 retained price observations'));
  renderer.draw(v,{view:'odds',filter:'all',search:'Baltimore Ravens'});
  assert(content.querySelector('.current-comparison-counts').textContent.includes('2 market outcomes covered · 4 retained price observations'));
  renderer.draw(v,{view:'odds',filter:'all',search:'no matching team'});
  assert(content.querySelector('.current-comparison-counts').textContent.includes('0 games with current comparisons · 0 market outcomes covered · 0 retained price observations'));
  const draw = () => renderer.draw(v,{view:'odds',filter:'all'}); draw();
  content.querySelector('.comparison-coverage-reasons').open = true;
  preserveDisclosures(content,draw);
  assert(content.querySelector('.comparison-coverage-reasons').open);
  const single = new Element('section'), singleRenderer = createBoardViews({content:single,participants:v.games[1].participants,onOriginal:()=>{},onDetails:()=>{}});
  singleRenderer.draw(v.boards[1],{view:'odds',filter:'all'});
  assert(single.querySelector('.current-comparison-counts').textContent.includes('1 game with current comparisons · 2 market outcomes covered · 4 retained price observations'));
  assert.equal(JSON.stringify(v),before,'coverage and filtering preserve all captured facts');
  assert.equal(dispatches,0);
  console.log('PASS current coverage across six outcomes/three games, signed-direction deduplication, retained alternatives/history, stale/missing/unsupported/pending/health reasons, displayed scope, identical aging and preserved disclosures with zero dispatches');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{Date.now=originalNow;});
