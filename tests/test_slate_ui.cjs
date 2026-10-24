// Authored two-occurrence guard/render tests. Financial values are supplied, never calculated by the browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { Element } = require('./ev07_dom.cjs');
document.createTextNode = value => { const node = new Element('span'); node.textContent = value; return node; };
global.fetch = () => { throw Error('A slate renderer cannot acquire data'); };
const {fixture,board:currentBoard,coverage,bounds}=require('./current_board_fixture.cjs');
const copy = value => JSON.parse(JSON.stringify(value));
const asset = name => pathToFileURL(path.resolve('app/dashboard/opportunity_static/current', name)).href;
// Legacy response facts are upgraded only in these authored renderer tests.
function authoredAvailability(v) {
 const states=['numeric_current','numeric_last_known','missing_reference','unsupported_inputs','calculation_failed','not_evaluated'];
 for(const b of v.boards){
  const counts=Object.fromEntries(states.map(s=>[s,0]));
  for(const r of b.rows){
   const numeric_metrics=['buffered_ev_usd','conditional_buffered_ev_usd','buffered_decisive_opposing_margin_usd','buffered_complete_modeled_minimum_usd'].filter(k=>r.financial_metrics?.[k]!=null);
   const state=numeric_metrics.length?'numeric_current':'not_evaluated';counts[state]++;
   r.availability={version:'predict-calculation-availability-1',state,reason_codes:[],numeric_metrics,metrics:Object.fromEntries(numeric_metrics.map(k=>[k,{state,reason_codes:[]}])),current_opportunity_eligible:false};
  }
  b.availability={version:'predict-calculation-availability-1',counts,total_results:b.rows.length,numeric_results:counts.numeric_current,current_results:counts.numeric_current,positive_results:0,outcome:counts.numeric_current?'evaluated_no_positive':'not_evaluated',causes:[]};
 }
 return v;
}

function slate(view = 'odds') {
  const first = copy(fixture.catalog.games[0]), second = { ...copy(first), game_key: 'synthetic-second-occurrence', title: 'Second synthetic NFL game', start_at: '2026-10-17T00:15:00+00:00' };
  const boards = [first, second].map(game => {
    const board = currentBoard(fixture[view],game.game_key);
    board.game_key = game.game_key;
    for (const q of board.prices) q.inputs_identity.game_key = game.game_key;
    return board;
  });
  return authoredAvailability({ version: 'predict-comparison-slate-2',epoch:'authored-reset-1', read_revision:'authored-read-1',coverage:coverage(2), view, filter: 'all', policy: copy(boards[0].policy), games: [first, second], boards, stopped: false, as_of: '2026-10-14T00:00:00+00:00', bounds:copy(bounds) });
}
(async () => {
  const { defaults, checkSlate, checkDetails } = await import(asset('board-client.js'));
  const { createSlateViews } = await import(asset('stored-views.js'));
  const c = {...defaults, view: 'odds', filter: 'all'};
  checkSlate(slate(), c);
  for (const edit of [v => v.view='ev', v => v.policy.requested_amount_usd='500', v => v.boards[1].policy.buffer_rate='0.01', v => v.boards[1].prices[0].inputs_identity.game_key='crossed', v => v.boards[1].game_key=v.boards[0].game_key, v => v.games[1].game_key=v.games[0].game_key, v => v.boards.pop(), v => v.bounds.maximum_bytes=104857600, v => v.bounds.maximum_games=501]) {
    const v=slate(); edit(v); assert.throws(()=>checkSlate(v,c));
  }
  const shared=slate('ev');shared.sizing_scope='shared_default_selected_details';
  checkSlate(shared,{...c,view:'ev',amount:'500',buffer:'0.02',benchmark_venue:'novig'});
  const sized=copy(fixture.single);sized.selection_context=copy(sized.calculation_context);
  sized.policy={...sized.policy,requested_amount_usd:'500',capital_ceiling_usd:'500',revision:'authored-selected-policy'};
  sized.calculation_context={...sized.calculation_context,context_id:'authored-selected-context',policy_revision:sized.policy.revision};
  const held={context_id:sized.selection_context.context_id,policy_revision:sized.selection_context.policy_revision,quote_id:sized.quote.id};
  checkDetails(sized,{...defaults,game:sized.game_key,amount:'500'},held);
  const crossed=copy(sized);crossed.calculation_context.dependency_revision='crossed';
  assert.throws(()=>checkDetails(crossed,{...defaults,game:sized.game_key,amount:'500'},held));
  const partial=slate(); partial.boards.pop(); partial.errors=[{game_key:partial.games[1].game_key,reason:'saved_prices_unavailable'}]; checkSlate(partial,c);
  partial.errors.push(copy(partial.errors[0])); assert.throws(()=>checkSlate(partial,c));
  const content=new Element('section'), originals=[], details=[];
  const renderer=createSlateViews({content,onOriginal:(q,b,g)=>originals.push({q,b,g}),onDetails:(r,b,g)=>details.push({r,b,g})});
  renderer.draw(slate(),{view:'odds',filter:'all'});
  assert.equal(content.querySelectorAll('.slate-game').length,2,'all games visible by default');
  assert.equal(content.querySelectorAll('.team').length,16,'distinct native periods and complements remain visible outcome rows');
  assert.equal(content.querySelectorAll('.slate-price-cell').flatMap(n=>n.querySelectorAll('button')).length,slate().boards.reduce((count,b)=>count+b.prices.length,0),'every retained original is directly visible');
  assert.equal(content.querySelectorAll('.slate-price-headings').length,1,'venue headings are shared across the full slate');
  assert(content.querySelector('.slate-coverage').textContent.includes('Novig ')); assert(content.querySelector('.slate-coverage').textContent.includes('ProphetX ')); assert(content.textContent.includes('2/2 matching games with observations')); assert(content.textContent.includes('Polymarket US'));
  const secondOriginal=content.querySelectorAll('button').find(b=>b.dataset.key.startsWith('synthetic-second-occurrence:')); secondOriginal.onclick();
  assert.equal(originals[0].g.game_key,'synthetic-second-occurrence'); assert.equal(originals[0].q.quote_id,secondOriginal.dataset.key.split('synthetic-second-occurrence:')[1]);
  assert(secondOriginal.title.includes(originals[0].q.original.units.replaceAll('_',' ')));
  assert(secondOriginal.title.includes(originals[0].q.freshness.source_at),'exact original source clock remains accessible');
  assert(secondOriginal.title.includes(originals[0].q.freshness.received_at),'exact receipt clock remains accessible');
  renderer.draw(slate(),{view:'odds',filter:'all',search:'second'}); assert.equal(content.querySelectorAll('.slate-game').length,1);
  renderer.draw(slate(),{view:'odds',filter:'all',game:fixture.odds.game_key}); assert.equal(content.querySelectorAll('.slate-game').length,1);
  renderer.draw(slate(),{view:'odds',filter:'all',search:'missing-team'}); assert(content.textContent.includes('No games match this filter'));
  const ev=slate('ev'); ev.boards[0].rows=ev.boards[0].rows.slice(0,1);ev.boards[1].rows=ev.boards[1].rows.slice(0,1);
  ev.boards[0].rows[0].financial_metrics.buffered_return_percent='-20'; ev.boards[1].rows[0].financial_metrics.buffered_return_percent='10';
  checkSlate(ev,{...c,view:'ev'}); renderer.draw(ev,{view:'ev',filter:'all'});
  assert.equal(content.querySelectorAll('.slate-comparison-game')[0].dataset.key,'synthetic-second-occurrence','global sort uses supplied exact return percentages');
  content.querySelectorAll('button')[0].onclick();assert.equal(details[0].g.game_key,'synthetic-second-occurrence');assert.equal(details[0].r.details.context_id,ev.boards[1].calculation_context.context_id);
  renderer.draw(ev,{view:'ev',filter:'all',sort:'start'});assert.equal(content.querySelectorAll('.slate-comparison-game')[0].dataset.key,fixture.catalog.games[0].game_key);
  renderer.draw(slate('arbs'),{view:'arbs',filter:'all'});assert.equal(content.querySelectorAll('.slate-result').length,28);assert(!content.textContent.includes('Complete EV unknown'));assert(!content.textContent.includes('Modeled minimum · buffered'));assert(content.textContent.includes('Margin · decisive outcomes only'));
  const pending=slate();pending.storage={state:'unavailable',error:'current_database_storage_cap'};pending.boards.forEach(b=>b.delivery_state='pending');renderer.draw(pending,{view:'odds',filter:'all'});
  assert(content.textContent.includes('Current updates paused'));assert(!content.textContent.includes('Calculation pending'));
  let all=0;const empty=slate('arbs');empty.boards.forEach(b=>b.rows=[]);renderer.draw(empty,{view:'arbs',filter:'positive',onShowAll:()=>all++});content.querySelectorAll('button')[0].onclick();assert.equal(all,1);assert(content.textContent.includes('Inspect signed and conditional results in All comparisons.'));
  const firstUse=slate();firstUse.games=[];firstUse.boards=[];
  renderer.draw(firstUse,{view:'odds',filter:'all'});
  assert(content.textContent.includes('No current games yet'));
  assert.equal(content.querySelectorAll('.slate-overview').length,0,'first use leads with setup rather than zero-count disclosures');
  console.log('PASS slate exact settings/game/board guards, default all-game rendering, venue coverage, local filters, cross-game Details, global supplied-metric sort and paused/empty states');
})().catch(error=>{console.error(error);process.exitCode=1;});
