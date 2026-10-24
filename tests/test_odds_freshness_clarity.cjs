// Small authored display frames: no provider, calculation, SQL or owner state.
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {Element} = require('./ev07_dom.cjs');
const {fixture, board, coverage, bounds} = require('./current_board_fixture.cjs');
document.createTextNode = value => { const node = new Element('span'); node.textContent = value; return node; };
let dispatches = 0;
global.fetch = () => { dispatches++; throw Error('Display must not dispatch'); };
const copy = value => JSON.parse(JSON.stringify(value));
const asset = name => pathToFileURL(path.resolve('app/dashboard/opportunity_static/current', name)).href;
const read = '2026-10-17T14:00:00.000Z', at = Date.parse(read), originalNow = Date.now;
Date.now = () => at;
function display(state, until = '2026-10-17T14:15:00Z', reasons = []) {
  return {state, read_at: read, source_age_seconds: state === 'unknown' ? null : 1, received_age_seconds: 0,
    current_until: state === 'unknown' ? null : until, reason_codes: reasons,
    source_reason_codes: state === 'last_known' ? reasons : [], publication_reason_codes: state === 'pending' ? reasons : []};
}
function input(q) { return copy({quote_id:q.quote_id, quote_revision:q.quote_revision, venue:q.venue, native_side:q.native_side,
  selection:q.selection, original:q.original, times:q.times, source_state:q.source_state, source_health:q.source_health,
  observation_display:q.observation_display}); }
(async () => {
  const {checkBoard, checkSlate, SlateAccumulator, defaults} = await import(asset('board-client.js'));
  const {createComparisonSlate, scopedObservationCoverage} = await import(asset('comparison-slate-views.js'));
  const {renderOriginalDetails} = await import(asset('stored-details.js'));
  const {updateRelativeAges, preserveDisclosures, relativeAge, ageNode, observationSummary} = await import(asset('board-elements.js'));
  const b = board(fixture.odds, fixture.odds.game_key), g = copy(fixture.catalog.games[0]);
  b.prices = b.prices.slice(0, 4); b.rows = []; b.delivery_state = 'pending';
  const states = ['current', 'pending', 'last_known', 'unknown'];
  b.prices.forEach((q, index) => {
    q.source_state = 'available'; q.source_health = {state:'available', reason:'Healthy source'};
    q.times = {source_at: index === 3 ? null : index === 2 ? '2026-10-15T15:09:00Z' : '2026-10-17T13:59:59Z', received_at:read, source_time_kind:'original_provider_book'};
    q.observation_display = display(states[index], undefined, index === 1 ? ['source_publication_pending','shared_reason'] : index === 2 ? ['source_expired','shared_reason'] : index === 3 ? ['source_unknown'] : []);
    q.gross_comparison = {available:false, value:null, inputs:[], display_status:'unavailable', reason_codes:[], read_at:read, source_time_skew_seconds:null, reason:'No compatible peer'};
  });
  const selected = b.prices[0], peer = b.prices[2];
  peer.venue = selected.venue === 'novig' ? 'polymarket_us' : 'novig';
  selected.gross_comparison = {available:true, value:'-0.021739130434782608695652', unit:'cents', exact:{numerator:'-1',denominator:'46'},
    comparison_quote_id:peer.quote_id, comparison_venue:peer.venue, inputs:[input(selected), input(peer)],
    display_status:'last_known', reason_codes:['source_expired'], read_at:read, source_time_skew_seconds:168659};
  b.estimate_availability = {state:'unavailable', reason_codes:['selected_reference_missing','calculation_failed']};
  const absent = {...copy(g), game_key:'authored-missing', title:'Missing synthetic game'};
  const slate = {version:'predict-comparison-slate-2', epoch:b.calculation_context.epoch, read_revision:'authored-read',
    read_at:read, as_of:'2026-10-15T00:00:00Z', view:'odds', filter:'all', policy:b.policy, games:[g,absent], boards:[b],
    errors:[{game_key:absent.game_key,reason:'source_board_read_failed'}], stopped:false, coverage:coverage(2), bounds:copy(bounds)};
  const c = {...defaults, view:'odds', filter:'all'};
  checkSlate(slate,c);
  const scoped = scopedObservationCoverage([b]);
  assert.deepEqual(scoped.counts,{current:1,pending:1,last_known:1,unknown:1});
  assert.equal(scoped.total,4); assert.equal(scoped.reasons.get('shared_reason'),2);
  assert.equal(scopedObservationCoverage([{...b,prices:[...b.prices,b.prices[0]]}]).total,4,'duplicate quote identities counted once');
  const content = new Element('section'), renderer = createComparisonSlate({content,onOriginal:()=>{},onDetails:()=>{}});
  renderer.draw(slate,{view:'odds',filter:'all'});
  for (const text of ['2 games shown · 2 in catalog','4 price observations','1 current · 1 pending publication · 1 last-known · 1 unknown/unavailable observations','Requested pages retrieved','board errors exclude unknown observations','source_board_read_failed','Updating stored observations']) assert(content.textContent.includes(text),text);
  const priceCells=content.querySelectorAll('.slate-price-cell');
  assert.equal(content.querySelectorAll('.compact-price-status').length,4);
  assert(priceCells.some(cell=>cell.textContent.includes('Current · 1s old')));
  assert(!priceCells.some(cell=>cell.textContent.includes('Observed depth unknown') || cell.textContent.includes('Gross difference')),'price cards leave technical/comparison evidence to Details');
  assert(!content.querySelector('.odds-research').open,'old observations start collapsed, independently of financial availability');
  assert(content.querySelector('.odds-research').querySelectorAll('.compact-price-status').length>0,'old originals remain inspectable');
  const brief=new Element('section');observationSummary(brief,selected,{compact:true});
  assert.equal(brief.children.length,1);assert.equal(brief.textContent,'Current · 1s old');
  updateRelativeAges(brief,at+16*60*1000);assert(brief.textContent.startsWith('Last-known · '));
  assert.equal(content.querySelectorAll('.observation-estimate-status').length,1,'one shared estimate message');
  assert(content.querySelector('.estimate-reasons').textContent.includes('selected_reference_missing'));
  renderer.draw(slate,{view:'odds',filter:'all',game:absent.game_key});
  assert(content.textContent.includes('Shown scope: 0 price observations'));
  assert(content.textContent.includes('Catalog: 4 returned price observations'));
  assert(content.textContent.includes('source_board_read_failed'));
  renderer.draw(slate,{view:'odds',filter:'all',search:g.participants[0].name});
  assert.equal(content.querySelectorAll('.slate-odds').length,2,'current and research observations have separate game sections');
  const manyGames = Array.from({length:51}, (_,index) => ({...copy(g),game_key:'authored-page-game:'+index,title:'Paged synthetic game '+index}));
  const accumulator = new SlateAccumulator(c);
  for (const offset of [0,50]) {
    const games = manyGames.slice(offset,offset+50), pageBoards = offset ? [] : games.map(game => board(b,game.game_key));
    const page = {...copy(slate), games:manyGames, boards:pageBoards, errors:offset ? [{game_key:games[0].game_key,reason:'source_board_read_failed'}] : [],coverage:coverage(51,offset)};
    accumulator.append(page,Buffer.byteLength(JSON.stringify(page)));
  }
  const complete = accumulator.result(); renderer.draw(complete,{view:'odds',filter:'all'});
  assert.equal(scopedObservationCoverage(complete.boards).total,200,'all retrieved pages contribute once');
  assert(content.textContent.includes('Requested pages retrieved · 2 pages'));
  assert(content.textContent.includes('200 price observations'));
  renderer.draw(complete,{view:'odds',filter:'all',game:manyGames[49].game_key});
  assert(content.textContent.includes('Shown scope: 4 price observations')); assert(content.textContent.includes('Catalog: 200 returned price observations'));
  const root = new Element('section'), render = () => renderOriginalDetails(selected,{estimate_availability:b.estimate_availability,evidence:{}},{root,participants:g.participants});
  render();
  const before = JSON.stringify(selected.gross_comparison);
  for (const text of ['-1/46 cents','Native side','Original price',peer.times.source_at,selected.times.source_at,'Healthy source','168,659 seconds','Positive means the selected price is lower','negative means it is higher']) assert(root.textContent.includes(text),text);
  const evidenceBody = root.querySelector('.original-comparison').parentNode;
  const comparisonIndex = evidenceBody.children.findIndex(node => node.className === 'original-comparison');
  assert(comparisonIndex < evidenceBody.children.findIndex(node => node.className === 'observed-depth'),'comparison precedes depth inside collapsed evidence');
  const disclosure = root.querySelector('.estimate-reasons'); disclosure.open = true;
  const summary = disclosure.querySelector('summary'); summary.closest = () => disclosure; summary.focus();
  await Promise.resolve(); preserveDisclosures(root,render);
  assert(root.querySelector('.estimate-reasons').open,'async evidence completion keeps disclosure');
  assert.equal(document.activeElement,root.querySelector('.estimate-reasons').querySelector('summary'),'summary focus restored');
  // A selected comparison remains frozen when the board peer is replaced.
  b.prices[2] = {...copy(peer), original:{...peer.original,value:'0.999999'}, times:{...peer.times,source_at:read}};
  render(); assert.equal(JSON.stringify(selected.gross_comparison),before); assert(root.textContent.includes(peer.times.source_at));
  const current = copy(selected);
  current.observation_display = display('current','2026-10-17T14:00:01Z');
  current.gross_comparison.inputs = [input(current),{...input(peer),observation_display:display('current','2026-10-17T14:00:02Z')}];
  current.gross_comparison.display_status = 'current';
  renderOriginalDetails(current,{evidence:{}},{root,participants:g.participants});
  const hold = root.querySelector('.observation-identity'); hold.open = true;
  const heldSummary = hold.querySelector('summary'); heldSummary.focus();
  assert(root.textContent.includes('Current comparison'));
  const sourceTimes = JSON.stringify(current.gross_comparison.inputs.map(i=>i.times));
  updateRelativeAges(root,at+3000);
  assert(root.textContent.includes('Last-known comparison'),'comparison ages without a price change');
  assert(hold.open); assert.equal(document.activeElement,heldSummary); assert.equal(JSON.stringify(current.gross_comparison.inputs.map(i=>i.times)),sourceTimes);
  assert.equal(relativeAge(null,at),'Unknown age');
  const futureClock=ageNode(new Date(Date.now()+60000).toISOString(),'Source ');
  assert.equal(futureClock.textContent,'Source clock is ahead');
  const clockRoot=new Element('section');clockRoot.append(futureClock);
  updateRelativeAges(clockRoot,Date.now());assert.equal(futureClock.textContent,'Source clock is ahead');
  const unknown = copy(current); unknown.gross_comparison.source_time_skew_seconds = null; unknown.gross_comparison.inputs[1].times.source_at = null;
  unknown.gross_comparison.inputs[1].observation_display = display('unknown'); unknown.gross_comparison.display_status = 'unknown';
  renderOriginalDetails(unknown,{evidence:{}},{root,participants:g.participants});
  assert(root.textContent.includes('Source-time separation: Unknown')); assert(root.textContent.includes('Unknown age'));
  for (const edit of [q=>q.observation_display.state='fresh', q=>q.observation_display.source_age_seconds='1',q=>q.observation_display.current_until='invalid',q=>q.gross_comparison.inputs.pop(),q=>q.gross_comparison.inputs[0].original.value='crossed',q=>q.gross_comparison.inputs[0].quote_revision=999,q=>q.gross_comparison.inputs[0].selection.participant='crossed',q=>q.gross_comparison.exact.denominator='0',q=>q.gross_comparison.comparison_venue=q.venue,q=>q.gross_comparison.source_time_skew_seconds=-1,q=>q.gross_comparison.inputs[1].times.source_at='different']) {
    const invalid = copy(b); invalid.prices[0] = copy(selected); edit(invalid.prices[0]);
    // A comparator may have a different valid clock; invalid source clock syntax
    // is checked here when the additive age metadata is present.
    assert.throws(()=>checkBoard(invalid,{...c,game:b.game_key}));
  }
  assert.equal(dispatches,0);
  console.log('PASS precise disjoint scoped counts/errors/overlapping reasons, frozen exact comparison provenance, clocks/skew/sign/native inputs, source-publication wording, shared reasons, additive guards and quiet age/focus/disclosure updates with zero dispatches');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{Date.now=originalNow;});
