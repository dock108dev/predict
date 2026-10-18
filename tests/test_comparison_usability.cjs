// Authored selection/meaning cases, plus optional authentic retained response replay.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { Element } = require('./ev07_dom.cjs');
document.createTextNode = value => { const n = new Element('span'); n.textContent = value; return n; };
global.fetch = () => { throw Error('Render cannot acquire data'); };
const asset = name => pathToFileURL(path.resolve('app/dashboard/opportunity_static/current', name)).href;
const fixture = JSON.parse(fs.readFileSync('tests/fixtures/ev09-u01-responses.json'));
const copy = value => JSON.parse(JSON.stringify(value));
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

(async () => {
  const { americanDecimal, matchesGameSearch } = await import(asset('board-elements.js'));
  const { createComparisonSlate, crossVenue } = await import(asset('comparison-slate-views.js'));
  for (const [value, expected] of [['2','+100'],['2.3','+130'],['1.75','-133'],['197/87','+126'],['197/110','-126'],['2.005','+101'],['2.004999999999999999999999999999','+100'],['1.8','-125'],['3/2','-200'],['1','Unavailable'],[null,'Unavailable'],['2/0','Unavailable'],['1.99','-101']]) assert.equal(americanDecimal(value),expected,value);
  assert(crossVenue({legs:[{venue:'novig',source:{provider:'shared'}},{venue:'prophetx',source:{provider:'shared'}}]}));
  assert(!crossVenue({legs:[{venue:'novig',source:{provider:'first'}},{venue:'novig',source:{provider:'second'}}]}));
  assert(!crossVenue({legs:[{venue:'novig'},{}]}));
  const content = new Element('section'), selected = [], originals = [];
  const renderer = createComparisonSlate({content,onDetails:(r,b,g)=>selected.push({r,b,g}),onOriginal:(q,b,g)=>originals.push({q,b,g})});
  function slate(view) {
    const b=copy(fixture[view]), g=copy(fixture.catalog.games[0]);
    return authoredAvailability({view,policy:b.policy,games:[g],boards:[b]});
  }
  for (const filter of ['all','positive','hedges']) {
    const v=slate('arbs'), before=JSON.stringify(v);
    renderer.draw(v,{view:'arbs',filter});
    const expected=v.boards[0].rows.filter(crossVenue);
    assert.equal(content.querySelectorAll('.slate-arb').length,14);
    assert.equal(expected.length,14);
    assert(content.querySelector('.slate-summary').textContent.includes('14 cross-venue comparisons'));
    for(const node of content.querySelectorAll('.slate-arb')){
      const row=expected.find(r=>node.dataset.key.endsWith(r.pair_id));assert(row);
      assert(node.textContent.includes('Margin · decisive outcomes only'));
      assert(!node.textContent.includes('Adverse outcomes before buffer:'));
      assert(!node.textContent.includes('Result as-of'));
      assert(!node.textContent.includes('residual'));
      node.querySelector('button').onclick();assert.equal(selected.at(-1).r,row);
    }
    assert.equal(content.querySelector('.same-venue-history').querySelectorAll('button').length,6);
    assert.equal(JSON.stringify(v),before,'immutable server response');
  }
  const same=slate('arbs');same.boards[0].rows=same.boards[0].rows.filter(r=>!crossVenue(r));
  renderer.draw(same,{view:'arbs',filter:'positive'});assert(content.textContent.includes('No current positive result'));assert(content.textContent.includes('0 cross-venue comparisons'));
  const sensitive=slate('arbs');sensitive.boards[0].rows=sensitive.boards[0].rows.filter(crossVenue).slice(0,1);
  sensitive.boards[0].rows[0].classification.positive_rule_sensitive_eligible=true;
  sensitive.boards[0].rows[0].classification.unknown_outcomes=['tie'];
  sensitive.boards[0].rows[0].financial_metrics.buffered_complete_modeled_minimum_usd=null;
  renderer.draw(sensitive,{view:'arbs',filter:'hedges'});
  assert.equal(content.querySelectorAll('.slate-result-note').length,1);assert(content.textContent.includes('settlement'));
  const ev=slate('ev');renderer.draw(ev,{view:'ev',filter:'all'});
  assert.equal(content.querySelectorAll('.slate-comparison-game').length,1);
  assert.equal(content.querySelectorAll('.slate-ev').length,ev.boards[0].rows.length);
  assert(content.querySelectorAll('.slate-instrument').length<ev.boards[0].rows.length,'comparable venue rows share instrument headings');
  const notWin=ev.boards[0].rows.find(r=>r.selection.predicate!=='win');
  if(notWin) assert(content.querySelectorAll('.slate-instrument').some(n=>n.textContent.includes('not win')));
  // Same participant, distinct period/predicate must not collapse.
  const extra=copy(ev.boards[0].rows[0]);extra.quote_id+=':distinct';extra.selection.period_boundary+=':distinct';ev.boards[0].rows.push(extra);
  renderer.draw(ev,{view:'ev',filter:'all'});assert.equal(content.querySelectorAll('.slate-ev').length,ev.boards[0].rows.length);
  const missing=slate('odds');missing.boards[0].prices=[];missing.boards[0].benchmark.fair=[];missing.boards[0].benchmark.originals=[];
  renderer.draw(missing,{view:'odds',filter:'all'});assert(content.textContent.includes('No retained prices for this market scope'));assert.equal(content.querySelectorAll('.slate-price-row').length,0,'an empty observation set cannot invent winner outcomes');
  const searched=slate('odds'),first=searched.games[0];
  Object.assign(first,{title:'CAR Panthers vs PHI Eagles',participants:[{id:'NFL:CAR',name:'Carolina Panthers'},{id:'NFL:PHI',name:'Philadelphia Eagles'}]});
  const second={...copy(first),game_key:first.game_key+':second',title:'Tampa Bay at Carolina'};
  searched.games.push(second);searched.boards.push({...copy(searched.boards[0]),game_key:second.game_key});
  assert(matchesGameSearch(first,' Carolina '));assert(matchesGameSearch(first,'NFL:CAR'));assert(matchesGameSearch(first,'eAGLes'));assert(!matchesGameSearch(first,'Denver'));
  renderer.draw(searched,{view:'odds',filter:'all',search:'Carolina'});
  assert.equal(content.querySelectorAll('.slate-odds').length,2,'full participant names match abbreviated game titles');
  assert(content.querySelector('.slate-summary').textContent.includes('2 games shown'));
  // Financial readiness and optional reference rendering cannot suppress a source fact.
  const observed=slate('odds'),b=observed.boards[0],q=b.prices[0];
  b.rows=[];b.benchmark=null;b.estimate_availability={state:'unavailable',reason_codes:['calculation_failed']};
  q.source_state='available';q.source_health={state:'available',reason:'Original book received'};q.freshness={...q.freshness,status:'current'};
  q.observed_depth={available:true,levels:[{price:'0.43',quantity:'12.5'},{price:'0.44',quantity:'27'}],quantity_units:'contracts',price_units:'usd_per_contract',total_levels:2,truncated:false,source_at:q.times.source_at,received_at:q.times.received_at};
  q.gross_comparison={available:true,value:'0.5',unit:'cents',meaning:'Same predicate and period; higher gross acquisition price'};
  const before=JSON.stringify(observed);renderer.draw(observed,{view:'odds',filter:'all'});
  assert(content.textContent.includes('Estimates unavailable'));
  assert(content.querySelector('.estimate-reasons').textContent.includes('calculation_failed'));
  assert(content.textContent.includes('Current price · Source available'));
  assert(content.textContent.includes('Observed 12.5 contracts at 0.43 usd per contract'));
  assert(content.textContent.includes('Gross difference +0.5 cents'));
  const preserved=content.querySelectorAll('button').find(n=>n.dataset.key===b.game_key+':'+q.quote_id);assert(preserved);preserved.onclick();assert.equal(originals.at(-1).q,q);
  assert.equal(JSON.stringify(observed),before,'observation presentation cannot rewrite source or estimate clocks');
  q.observed_depth=null;q.freshness.status='historical';q.source_health.state='stopped';renderer.draw(observed,{view:'odds',filter:'all'});
  assert(content.textContent.includes('Last-known price · Source stopped'));assert(content.textContent.includes('Observed depth unknown'));
  const evidence=process.env.PREDICT_RETAINED_RESPONSES;
  if(evidence){
    const read=name=>JSON.parse(fs.readFileSync(path.join(evidence,name)));
    const odds=read('codec2-final-odds.json'),before=JSON.stringify(odds);
    renderer.draw(odds,{view:'odds',filter:'all'});
    const us=odds.boards.flatMap(b=>b.prices.filter(q=>q.venue==='polymarket_us').map(q=>({q,b})));
    assert.equal(us.length,6);assert.equal(us.filter(({q})=>q.native_side==='Short').length,3);
    for(const {q,b} of us){
      const button=content.querySelectorAll('.slate-price-cell').flatMap(n=>n.querySelectorAll('button')).find(n=>n.dataset.key===b.game_key+':'+q.quote_id);
      assert(button,'inline '+q.quote_id);assert(button.textContent.includes(q.native_side));assert(button.textContent.includes(q.common_odds.american));button.onclick();
      assert.equal(originals.at(-1).q,q);assert.equal(originals.at(-1).g.game_key,b.game_key);assert(button.title.includes(q.freshness.source_at));
    }
    assert.equal(JSON.stringify(odds),before);
    const arbs=read('final-arbs.json');renderer.draw(arbs,{view:'arbs',filter:'all'});
    assert.equal(content.querySelectorAll('.slate-arb').length,80);assert(content.querySelector('.slate-summary').textContent.includes('80 cross-venue comparisons'));
    assert.equal(content.querySelector('.same-venue-history').querySelectorAll('button').length,62);
    const value=read('final-ev.json');renderer.draw(value,{view:'ev',filter:'all'});
    assert.equal(content.querySelectorAll('.slate-ev').length,value.boards.reduce((n,b)=>n+b.rows.length,0));
    renderer.draw(slate('ev'),{view:'ev',filter:'all'});
  const ordinary=content.querySelectorAll('.slate-result-note').find(n=>n.textContent==='No positive value after costs and buffer');
  assert(ordinary,'ordinary non-positive result uses reader-facing copy');
  assert.equal(ordinary.dataset.caution,'false','routine negative is not a material warning');
  renderer.draw(slate('odds'),{view:'odds',filter:'all'});
  assert.equal(content.querySelectorAll('.native-meaning').length,1,'shared native limitation appears once');
  console.log('PASS authentic retained replay: six exact Long/Short originals, 80 cross-venue + 62 advanced pairs, every EV instrument retained; immutable inputs');
  }
  console.log('PASS independent odds vectors, execution venue scope/counts in all filters, same-provider venues, grouped distinct instruments, exact callbacks, compact risk and missing/empty states');
})().catch(error=>{console.error(error);process.exitCode=1;});
