// Captured authored pairs; rendering and age text perform zero dispatches.
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {Element} = require('./ev07_dom.cjs');
const {fixture, board} = require('./current_board_fixture.cjs');
document.createTextNode = value => {const n = new Element('span'); n.textContent = value; return n;};
global.fetch = () => {throw Error('Display cannot request providers or new data');};
const asset = name => pathToFileURL(path.resolve('app/dashboard/opportunity_static/current',name)).href;
const copy = value => JSON.parse(JSON.stringify(value));
(async()=>{
  const {comparisonTakeaway, observationSummary, updateRelativeAges} = await import(asset('board-elements.js'));
  const {renderOriginalDetails} = await import(asset('stored-details.js'));
  const {checkBoard, defaults} = await import(asset('board-client.js'));
  const b = board(fixture.odds, fixture.odds.game_key), q = b.prices[0], p = copy(q);
  const at = Date.parse('2026-10-17T16:00:00Z'), originalNow = Date.now; Date.now = () => at;
  const status = {state:'current',read_at:new Date(at).toISOString(),reason_codes:[],source_reason_codes:[],publication_reason_codes:[],source_age_seconds:1,received_age_seconds:0,current_until:new Date(at+15000).toISOString()};
  q.observation_display=copy(status);q.times={source_at:new Date(at-1000).toISOString(),received_at:new Date(at).toISOString()};
  p.quote_id='authored-other';p.venue='kalshi';if(q.venue==='kalshi')p.venue='novig';
  p.observation_display=copy(status);p.times=copy(q.times);
  const input = v => copy({quote_id:v.quote_id,quote_revision:v.quote_revision,venue:v.venue,native_side:v.native_side,selection:v.selection,original:v.original,times:v.times,source_state:'available',source_health:{state:'available'},observation_display:v.observation_display});
  q.current_comparison={available:true,metric:'lowest_current',value:'-0.021739130434',unit:'cents',exact:{numerator:'-1',denominator:'46'},comparison_quote_id:p.quote_id,comparison_venue:p.venue,inputs:[input(q),input(p)],display_status:'current',read_at:new Date(at).toISOString(),reason_codes:[],source_time_skew_seconds:0,selection_valid_until:new Date(at+15000).toISOString()};
  q.gross_comparison=copy(q.current_comparison);q.gross_comparison.metric='lowest_observed';
  q.gross_comparison.inputs[1].times.source_at='2026-10-15T16:00:00Z';q.gross_comparison.inputs[1].observation_display.state='last_known';q.gross_comparison.display_status='last_known';
  assert(comparisonTakeaway(q.current_comparison,at).includes('about 0.02¢ higher than'));
  const lower=copy(q.current_comparison);lower.exact.numerator='1';lower.value='0.021739130434';
  assert(comparisonTakeaway(lower,at).includes('about 0.02¢ lower than'));
  const equal=copy(lower);equal.exact.numerator='0';equal.value='0';assert(comparisonTakeaway(equal,at).includes('Selected price equals'));
  assert(comparisonTakeaway(q.gross_comparison,at).includes('2d 0h old; Last-known comparison'));
  const root=new Element('section');renderOriginalDetails(q,{evidence:{}},{root,participants:fixture.catalog.games[0].participants});
  assert(root.querySelector('.comparison-takeaway').textContent.includes('Current comparison'));
  assert(root.children.indexOf(root.querySelector('.price-lead')) < root.children.indexOf(root.querySelector('.comparison-takeaway')),'original prices lead the comparison interpretation');
  for(const text of ['Current-peer price comparison','Lowest observed price comparison','-1/46 cents','Original source time'])assert(root.textContent.includes(text),text);
  const captured=JSON.stringify(q.current_comparison);p.original.value='0.9999';
  updateRelativeAges(root,at+20000);
  assert(root.querySelector('.comparison-takeaway').textContent.includes('Last-known comparison'));
  assert.equal(JSON.stringify(q.current_comparison),captured);
  const compact=new Element('section');observationSummary(compact,q);assert(compact.textContent.includes('Current-peer difference'));
  q.same_outcome={supported:true,key:['authored-market-condition',b.game_key,'winner','full_game'],reason:null,missing_fields:[]};
  for(const comparison of [q.current_comparison,q.gross_comparison]) for(const input of comparison.inputs) input.same_outcome=copy(q.same_outcome);
  checkBoard(b,{...defaults,view:'odds',filter:'all',game:b.game_key});
  for(const edit of [v=>v.current_comparison.inputs.pop(),v=>v.current_comparison.inputs[0].times.source_at='crossed',v=>v.current_comparison.exact.denominator='0',v=>v.current_comparison.selection_valid_until='bad',v=>v.same_outcome.supported='yes',v=>v.current_comparison.inputs[1].same_outcome.key=['different-occurrence']]) {
    const crossed=copy(b);edit(crossed.prices[0]);assert.throws(()=>checkBoard(crossed,{...defaults,view:'odds',filter:'all',game:b.game_key}));
  }
  const indexed=copy(b);
  indexed.rows=indexed.prices.map(input=>({quote_id:input.quote_id,quote_revision:input.quote_revision,price_ref:input.quote_id,venue:input.venue,selection:Object.fromEntries(['participant','predicate','signed_line','result_interpretation'].map(key=>[key,input.selection[key]??null])),market:{market:input.market?.market??null,period:input.market?.period??null}}));
  checkBoard(indexed,{...defaults,view:'odds',filter:'all',game:indexed.game_key});
  for(const edit of [v=>v.rows.pop(),v=>v.rows[0].price_ref='different-frame',v=>v.rows[0].quote_revision='changed',v=>v.rows[0].selection.predicate='not_win']) {
    const crossed=copy(indexed);edit(crossed);assert.throws(()=>checkBoard(crossed,{...defaults,view:'odds',filter:'all',game:crossed.game_key}));
  }
  const encoded=copy(b),selectedFrame=copy(q),peerFrame={...copy(p),...copy(q.current_comparison.inputs[1])};
  delete selectedFrame.gross_comparison;delete peerFrame.gross_comparison;delete peerFrame.current_comparison;
  peerFrame.inputs_identity={...copy(q.inputs_identity),quote_id:peerFrame.quote_id};
  encoded.prices=[selectedFrame,peerFrame];encoded.rows=[];
  encoded.comparison_input_encoding='same-board-price-refs-1';encoded.native_wordings=['Full retained wording — including overtime.'];
  for(const input of encoded.prices)input.native_contract_summary={wording_refs:[['description',0]]};
  selectedFrame.current_comparison.input_refs=selectedFrame.current_comparison.inputs.map(input=>({quote_id:input.quote_id,quote_revision:input.quote_revision}));
  selectedFrame.current_comparison.inputs=[];
  checkBoard(encoded,{...defaults,view:'odds',filter:'all',game:encoded.game_key});
  assert.equal(selectedFrame.current_comparison.inputs.length,2);
  assert.equal(selectedFrame.current_comparison.inputs[1].native_contract_summary.wording.description,encoded.native_wordings[0]);
  const snapshot=JSON.stringify(selectedFrame.current_comparison.inputs);encoded.native_wordings[0]='Newer description';
  assert.equal(JSON.stringify(selectedFrame.current_comparison.inputs),snapshot,'decoded frozen wording and source inputs stay detached from the pooled wire frame');
  const held=copy(encoded);held.prices[1].original.value='0.99';
  const heldInputs=JSON.stringify(held.prices[0].current_comparison.inputs);
  checkBoard(held,{...defaults,view:'odds',filter:'all',game:held.game_key});
  assert.equal(JSON.stringify(held.prices[0].current_comparison.inputs),heldInputs,'repeated validation never rebinds decoded peer inputs to a changed price row');
  const crossedRef=copy(encoded);crossedRef.prices[0].current_comparison.input_refs[1].quote_revision='different';
  assert.throws(()=>checkBoard(crossedRef,{...defaults,view:'odds',filter:'all',game:encoded.game_key}));
  const financial=copy(fixture.ev);
  for(const row of financial.rows) {
    row.price_ref=row.quote_id;
    for(const key of ['original','times','source','selection','native_side','common_odds'])delete row[key];
  }
  checkBoard(financial,{...defaults,view:'ev',filter:'all',game:financial.game_key});
  for(const row of financial.rows)assert.deepEqual(row.original,financial.prices.find(input=>input.quote_id===row.quote_id).original);
  const crossedFinancial=copy(financial);crossedFinancial.rows[0].price_ref='unknown-frame';
  assert.throws(()=>checkBoard(crossedFinancial,{...defaults,view:'ev',filter:'all',game:financial.game_key}));
  const boundary=copy(q.current_comparison);boundary.selection_valid_until=new Date(at+2000).toISOString();
  assert(comparisonTakeaway(boundary,at+3000).includes('pending publication'));
  Date.now=originalNow;
  console.log('PASS current/historical sections, exact signed cent takeaway, comparator age/status, frozen pair, boundary aging and current-field client guards; zero dispatches');
})().catch(error=>{console.error(error);process.exitCode=1;});
