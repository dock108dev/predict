// Table-driven captured six-league / three-family presentation; no source requests.
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {Element} = require('./ev07_dom.cjs');
const {fixture,board,copy} = require('./current_board_fixture.cjs');
document.createTextNode = text => {const n=new Element('span');n.textContent=text;return n;};
let dispatches=0;global.fetch=()=>{dispatches++;throw Error('Local filters and Details cannot dispatch');};
const asset = name => pathToFileURL(path.resolve('app/dashboard/opportunity_static/current',name)).href;
const now=Date.parse('2026-10-17T19:00:00Z'), oldNow=Date.now;Date.now=()=>now;
const display={state:'current',read_at:new Date(now).toISOString(),reason_codes:[],current_until:new Date(now+10000).toISOString()};
function matrix() {
 const games=[],boards=[];
 for(const league of ['NFL','NCAAF','NBA','NCAAB','MLB','NHL']) {
  const key=league+':new-after-startup',participants=[{id:league+':away',name:league+' Visitors',role:'away'},{id:league+':home',name:league+' Hosts',role:'home'}];
  const g={...copy(fixture.catalog.games[0]),game_key:key,league,sport:{NFL:'football',NCAAF:'football',NBA:'basketball',NCAAB:'basketball',MLB:'baseball',NHL:'hockey'}[league],title:participants.map(p=>p.name).join(' at '),start_at:new Date(now+86400000).toISOString(),participants,families:['winner','spread','total'],periods:['full_game']};
  const b=board(fixture.odds,key);b.prices=[];
  for(const family of g.families)for(const direction of [0,1]) {
   const pairs=[];
   for(const venue of ['kalshi','polymarket_us']) {
    const q=copy(fixture.odds.prices[0]);q.quote_id=[key,family,direction,venue].join(':');q.venue=venue;q.native_side=venue==='kalshi'?'yes':direction?'short':'long';
    q.selection={...q.selection,participant:family==='total'?null:participants[direction].id,predicate:family==='total'?(direction?'under':'over'):family==='spread'?'cover':'win',signed_line:family==='spread'?(direction?'3.5':'-3.5'):family==='total'?'45.5':null};
    q.event={title:g.title,sport:g.sport,league,start_at:g.start_at};q.market={market:family,period:'full_game',line:q.selection.signed_line,period_boundary:'Full game; original exact scoring rules'};
    q.times={source_at:new Date(now-1000).toISOString(),received_at:new Date(now).toISOString()};q.observation_display=copy(display);q.source_state='available';q.source_health={state:'available'};
    q.same_outcome={supported:true,key:['authored-same-outcome',key,family,direction,'full_game'],reason:null,missing_fields:[]};pairs.push(q);
   }
   for(const [index,q] of pairs.entries()) {
    const p=pairs[1-index],captured=x=>copy({quote_id:x.quote_id,quote_revision:x.quote_revision,venue:x.venue,native_side:x.native_side,selection:x.selection,market:x.market,same_outcome:x.same_outcome,original:x.original,times:x.times,observation_display:x.observation_display});
    q.current_comparison={available:true,metric:'lowest_current',value:'0.25',unit:'cents',exact:{numerator:'1',denominator:'4'},comparison_quote_id:p.quote_id,comparison_venue:p.venue,inputs:[captured(q),captured(p)],display_status:'current',read_at:new Date(now).toISOString(),reason_codes:[],selection_valid_until:new Date(now+10000).toISOString()};
    q.gross_comparison=copy(q.current_comparison);q.gross_comparison.metric='lowest_observed';b.prices.push(q);
   }
  }
  b.rows=b.prices;games.push(g);boards.push(b);
 }
 return {games,boards,policy:boards[0].policy,read_at:new Date(now).toISOString()};
}
(async()=>{
 const {createComparisonSlate}=await import(asset('comparison-slate-views.js'));
 const {scopedCurrentComparisonCoverage}=await import(asset('comparison-coverage.js'));
 const {labelsFor,marketFamily,outcomeDisplayKey}=await import(asset('board-elements.js'));
 const {renderOriginalDetails}=await import(asset('stored-details.js'));
 const v=matrix(),before=JSON.stringify(v),root=new Element('section'),selected=[];
 const views=createComparisonSlate({content:root,onOriginal:(q,b,g)=>selected.push({q,g}),onDetails:()=>{}});
 views.draw(v,{view:'odds',filter:'all'});
 assert.equal(root.querySelectorAll('.slate-game').length,6);assert.equal(root.querySelectorAll('.slate-price-row').length,36);
 assert(root.textContent.includes('36 market outcomes covered · 72 retained price observations'));
 assert.equal(scopedCurrentComparisonCoverage(v.boards,now).current_pairs,36,'signed directions count once');
 assert.equal(scopedCurrentComparisonCoverage(v.boards,now).current_directions,72);
 assert(root.textContent.includes('72 signed comparison directions'));
 for(const family of ['winner','spread','total']) {
  views.draw(v,{view:'odds',filter:'all',family});assert.equal(root.querySelectorAll('.slate-price-row').length,12);
  assert(root.textContent.includes('12 market outcomes covered · 24 retained price observations'));
  root.querySelector('button').onclick();assert.equal(marketFamily(selected.at(-1).q),family);
 }
 views.draw(v,{view:'odds',filter:'all',league:'NBA',family:'total'});assert.equal(root.querySelectorAll('.slate-game').length,1);
 assert(root.textContent.includes('NBA · Starts '));assert(root.textContent.includes('Over 45.5'));assert(root.textContent.includes('Under 45.5'));
 assert(root.textContent.includes('2 market outcomes covered · 4 retained price observations'));
 views.draw(v,{view:'odds',filter:'all',period:'first_half'});assert.equal(root.querySelectorAll('.slate-game').length,0);assert(root.textContent.includes('0 retained price observations'));
 const q=v.boards[3].prices.find(q=>marketFamily(q)==='spread'),detail=new Element('section');
 assert.equal(labelsFor(v.games[3].participants).selection(q,false),'NCAAB Visitors -3.5 spread');
 renderOriginalDetails(q,{evidence:{native_contract:'authored source facts'}},{root:detail,participants:v.games[3].participants,title:v.games[3].title});
 for(const expected of ['NCAAB','Spread · full game','1/4 cents','Current-peer price comparison','Lowest observed price comparison','Original source time'])assert(detail.textContent.includes(expected),expected);
 const other=copy(q);other.selection.signed_line='-4';assert.equal(outcomeDisplayKey(other),outcomeDisplayKey(q),'server canonical equality can group proven scoring equivalence while raw lines remain retained');
 assert.equal(q.selection.signed_line,'-3.5');assert.equal(JSON.stringify(v),before);assert.equal(dispatches,0);
 console.log('PASS six leagues × winner/spread/total, direct original rows, exact outcome/pair/observation counts, local league/family/period filters, native lines and frozen Details; zero requests');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>{Date.now=oldNow;});
