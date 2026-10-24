// Authored states: presentation semantics only; no financial qualification.
const assert=require('node:assert/strict'),path=require('node:path');
const {pathToFileURL}=require('node:url'),{Element}=require('./ev07_dom.cjs');
(async()=>{
const asset=n=>pathToFileURL(path.resolve('app/dashboard/opportunity_static/current',n));
const {dashboardScope,drawOpportunityDashboard}=await import(asset('opportunity-dashboard.js'));
const {coverageCellState,cellRatio}=await import(asset('coverage-model.js'));
const {renderCoverageOutcome,coverageAge}=await import(asset('coverage-view.js'));
const game={game_key:'healthy',title:'Authored healthy game',participants:[]},bad={game_key:'failed',title:'Authored failed game',participants:[]};
const slate={games:[game,bad],boards:[{game_key:'healthy',rows:[],prices:[],availability:{evaluation_complete:false}}],errors:[{game_key:'failed',reason:'local_board_failure'}]};
assert.equal(dashboardScope(slate,'ev').state,'partial');
const root=new Element('section');drawOpportunityDashboard(root,{ev:slate},{},()=>{},['ev']);
assert.match(root.textContent,/Partially evaluated/);assert.match(root.textContent,/Authored failed game/);assert.doesNotMatch(root.textContent,/Positive arbitrage/);
assert(root.querySelectorAll('details').every(d=>!d.open));
const cell={id:'a',sport:'NFL',venue:'kalshi',family:'winner',period:'full_game',configuration_state:'enabled',counts:{retained_observations:2,retained_comparison_observations:2,current_comparison_observations:0},reasons:[]};
for(const [state,expected] of [['held','Source held'],['paused','Source paused'],['not_configured','Not configured']])assert.equal(coverageCellState({...cell,configuration_state:state}),expected);
assert.equal(coverageCellState({...cell,reasons:[{code:'source_failed',category:'source'}]}),'Source query failed');
assert.equal(coverageCellState({...cell,reasons:[{code:'waiting_for_publication',category:'publication'}]}),'Pending publication');
assert.equal(coverageCellState({...cell,reasons:[{code:'identity_missing',category:'identity'}]}),'Matching facts or peers missing');
assert.equal(coverageCellState({...cell,counts:{...cell.counts,last_known_observations:2}}),'Last-known observations');
assert.equal(coverageCellState({...cell,counts:{...cell.counts,current_comparison_observations:2}}),'Current supported comparisons');
assert.equal(cellRatio({...cell,counts:{retained_observations:99,supported_comparison_observations:1}}).denominator,null,'never substitute retained references for unavailable purchase denominator');
const data={captured_at:'2026-10-01T00:00:00Z',publication_at:'2026-10-01T00:00:01Z',publication_state:'stale',publication_error:'background_coverage_unavailable',cells:[cell],global_totals:cell.counts};
renderCoverageOutcome(root,data,{});assert.match(root.textContent,/Coverage publication failed/);assert.match(root.textContent,/background_coverage_unavailable/);assert.match(root.textContent,/freshness is unverified/);assert.match(root.textContent,/Reference observations excluded/);
renderCoverageOutcome(root,data,{league:'NFL'},'authored_read_failure');assert.match(root.textContent,/Coverage read failed/);
renderCoverageOutcome(root,{...data,captured_at:null,publication_error:null,publication_state:'pending'},{});assert.match(root.textContent,/counts unmeasured/);assert.doesNotMatch(root.textContent,/0 retained/);
assert.equal(coverageAge(null),'Unknown');assert.equal(coverageAge('2026-10-01T00:00:00Z',Date.parse('2026-10-01T02:12:00Z')),'2h 12m ago');
console.log('PASS U3 single EV, named partial failures, Coverage independent states, original clock ages and unknown purchase denominators');
})().catch(e=>{console.error(e);process.exitCode=1});
