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
(async () => {
  const { americanDecimal } = await import(asset('board-elements.js'));
  const { createComparisonSlate, crossVenue } = await import(asset('comparison-slate-views.js'));
  for (const [value, expected] of [['2','+100'],['2.3','+130'],['1.75','-133'],['197/87','+126'],['197/110','-126'],['2.005','+101'],['2.004999999999999999999999999999','+100'],['1.8','-125'],['3/2','-200'],['1','Unavailable'],[null,'Unavailable'],['2/0','Unavailable'],['1.99','-101']]) assert.equal(americanDecimal(value),expected,value);
  assert(crossVenue({legs:[{venue:'novig',source:{provider:'shared'}},{venue:'prophetx',source:{provider:'shared'}}]}));
  assert(!crossVenue({legs:[{venue:'novig',source:{provider:'first'}},{venue:'novig',source:{provider:'second'}}]}));
  assert(!crossVenue({legs:[{venue:'novig'},{}]}));
  const content = new Element('section'), selected = [], originals = [];
  const renderer = createComparisonSlate({content,onDetails:(r,b,g)=>selected.push({r,b,g}),onOriginal:(q,b,g)=>originals.push({q,b,g})});
  function slate(view) {
    const b=copy(fixture[view]), g=copy(fixture.catalog.games[0]);
    return {view,policy:b.policy,games:[g],boards:[b]};
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
      assert(node.textContent.includes('Decisive margin · buffered'));
      assert(!node.textContent.includes('Adverse outcomes before buffer:'));
      assert(!node.textContent.includes('Result as-of'));
      assert(!node.textContent.includes('residual'));
      node.querySelector('button').onclick();assert.equal(selected.at(-1).r,row);
    }
    assert.equal(content.querySelector('.same-venue-history').querySelectorAll('button').length,6);
    assert.equal(JSON.stringify(v),before,'immutable server response');
  }
  const same=slate('arbs');same.boards[0].rows=same.boards[0].rows.filter(r=>!crossVenue(r));
  renderer.draw(same,{view:'arbs',filter:'positive'});assert(content.textContent.includes('No estimated arbitrage found'));assert(content.textContent.includes('0 cross-venue comparisons'));
  const sensitive=slate('arbs');sensitive.boards[0].rows=sensitive.boards[0].rows.filter(crossVenue).slice(0,1);
  sensitive.boards[0].rows[0].classification.positive_rule_sensitive_eligible=true;
  sensitive.boards[0].rows[0].classification.unknown_outcomes=['tie'];
  sensitive.boards[0].rows[0].financial_metrics.buffered_complete_modeled_minimum_usd=null;
  renderer.draw(sensitive,{view:'arbs',filter:'hedges'});
  assert(content.textContent.includes('Rule-sensitive hedge'));assert(content.textContent.includes('Unknown outcome payouts'));assert(content.textContent.includes('Adverse outcome'));
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
  renderer.draw(missing,{view:'odds',filter:'all'});assert(content.textContent.includes('Fair unavailable'));assert.equal(content.querySelectorAll('.unavailable-price').length,8);
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
    console.log('PASS authentic retained replay: six exact Long/Short originals, 80 cross-venue + 62 advanced pairs, every EV instrument retained; immutable inputs');
  }
  console.log('PASS independent odds vectors, execution venue scope/counts in all filters, same-provider venues, grouped distinct instruments, exact callbacks, compact risk and missing/empty states');
})().catch(error=>{console.error(error);process.exitCode=1;});
