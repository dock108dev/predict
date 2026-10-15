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
function slate(view = 'odds') {
  const first = copy(fixture.catalog.games[0]), second = { ...copy(first), game_key: 'synthetic-second-occurrence', title: 'Second synthetic NFL game', start_at: '2026-10-17T00:15:00+00:00' };
  const boards = [first, second].map(game => {
    const board = currentBoard(fixture[view],game.game_key);
    board.game_key = game.game_key;
    for (const q of board.prices) q.inputs_identity.game_key = game.game_key;
    return board;
  });
  return { version: 'predict-comparison-slate-2',epoch:'authored-reset-1', read_revision:'authored-read-1',coverage:coverage(2), view, filter: 'all', policy: copy(boards[0].policy), games: [first, second], boards, stopped: false, as_of: '2026-10-14T00:00:00+00:00', bounds:copy(bounds) };
}
(async () => {
  const { defaults, checkSlate } = await import(asset('board-client.js'));
  const { createSlateViews } = await import(asset('stored-views.js'));
  const c = {...defaults, view: 'odds', filter: 'all'};
  checkSlate(slate(), c);
  for (const edit of [v => v.view='ev', v => v.policy.requested_amount_usd='500', v => v.boards[1].policy.buffer_rate='0.01', v => v.boards[1].prices[0].inputs_identity.game_key='crossed', v => v.boards[1].game_key=v.boards[0].game_key, v => v.games[1].game_key=v.games[0].game_key, v => v.boards.pop(), v => v.bounds.maximum_bytes=104857600, v => v.bounds.maximum_games=501]) {
    const v=slate(); edit(v); assert.throws(()=>checkSlate(v,c));
  }
  const partial=slate(); partial.boards.pop(); partial.errors=[{game_key:partial.games[1].game_key,reason:'saved_prices_unavailable'}]; checkSlate(partial,c);
  partial.errors.push(copy(partial.errors[0])); assert.throws(()=>checkSlate(partial,c));
  const content=new Element('section'), originals=[], details=[];
  const renderer=createSlateViews({content,onOriginal:(q,b,g)=>originals.push({q,b,g}),onDetails:(r,b,g)=>details.push({r,b,g})});
  renderer.draw(slate(),{view:'odds',filter:'all'});
  assert.equal(content.querySelectorAll('.slate-game').length,2,'all games visible by default');
  assert.equal(content.querySelectorAll('.team').length,4);
  assert.equal(content.querySelectorAll('.slate-price-headings').length,1,'venue headings are shared across the full slate');
  assert(content.textContent.includes('Novig 2/2')); assert(content.textContent.includes('ProphetX 2/2')); assert(content.textContent.includes('Polymarket US'));
  const secondOriginal=content.querySelectorAll('button').find(b=>b.dataset.key.startsWith('synthetic-second-occurrence:')); secondOriginal.onclick();
  assert.equal(originals[0].g.game_key,'synthetic-second-occurrence'); assert.equal(originals[0].q.quote_id,secondOriginal.dataset.key.split('synthetic-second-occurrence:')[1]);
  assert(secondOriginal.title.includes(originals[0].q.original.units.replaceAll('_',' ')));
  assert(secondOriginal.title.includes(originals[0].q.freshness.source_at),'exact original source clock remains accessible');
  assert(secondOriginal.title.includes(originals[0].q.freshness.received_at),'exact receipt clock remains accessible');
  renderer.draw(slate(),{view:'odds',filter:'all',search:'second'}); assert.equal(content.querySelectorAll('.slate-game').length,1);
  renderer.draw(slate(),{view:'odds',filter:'all',game:fixture.odds.game_key}); assert.equal(content.querySelectorAll('.slate-game').length,1);
  renderer.draw(slate(),{view:'odds',filter:'all',search:'missing-team'}); assert(content.textContent.includes('No games match this filter'));
  const ev=slate('ev'); ev.boards[0].rows=ev.boards[0].rows.slice(0,1);ev.boards[1].rows=ev.boards[1].rows.slice(0,1);
  ev.boards[0].rows[0].financial_metrics.buffered_ev_usd='-20'; ev.boards[1].rows[0].financial_metrics.buffered_ev_usd='10';
  checkSlate(ev,{...c,view:'ev'}); renderer.draw(ev,{view:'ev',filter:'all'});
  assert(content.querySelectorAll('.slate-comparison-game')[0].textContent.includes('Second synthetic NFL game'),'global sort uses supplied dollar metrics');
  content.querySelectorAll('button')[0].onclick();assert.equal(details[0].g.game_key,'synthetic-second-occurrence');assert.equal(details[0].r.details.context_id,ev.boards[1].calculation_context.context_id);
  renderer.draw(ev,{view:'ev',filter:'all',sort:'start'});assert(content.querySelectorAll('.slate-comparison-game')[0].textContent.includes(fixture.catalog.games[0].title));
  renderer.draw(slate('arbs'),{view:'arbs',filter:'all'});assert.equal(content.querySelectorAll('.slate-result').length,28);assert(content.textContent.includes('Complete EV unknown'));assert(content.textContent.includes('Modeled minimum · buffered'));
  const pending=slate();pending.storage={state:'unavailable',error:'current_database_storage_cap'};pending.boards.forEach(b=>b.delivery_state='pending');renderer.draw(pending,{view:'odds',filter:'all'});
  assert(content.textContent.includes('Current updates paused'));assert(!content.textContent.includes('Calculation pending'));
  let all=0;const empty=slate('arbs');empty.boards.forEach(b=>b.rows=[]);renderer.draw(empty,{view:'arbs',filter:'positive',onShowAll:()=>all++});content.querySelectorAll('button')[0].onclick();assert.equal(all,1);assert(content.textContent.includes('See signed and conditional results in All comparisons.'));
  console.log('PASS slate exact settings/game/board guards, default all-game rendering, venue coverage, local filters, cross-game Details, global supplied-metric sort and paused/empty states');
})().catch(error=>{console.error(error);process.exitCode=1;});
