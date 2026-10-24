const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {Element} = require('./ev07_dom.cjs');
const fixture = JSON.parse(execFileSync(process.env.PYTHON || '.venv/bin/python', ['-m','tests.shared_current_client_fixture'], {encoding:'utf8',maxBuffer:8*1024*1024}));
document.createTextNode = text => {const node=new Element('span');node.textContent=text;return node;};
let requests = 0;global.fetch = () => {requests++;throw Error('Retained rendering cannot dispatch');};
const asset = name => pathToFileURL(path.resolve('app/dashboard/opportunity_static/current',name)).href;
(async()=>{
 const {comparisonState,observationSummary}=await import(asset('board-elements.js'));
 const {createComparisonSlate}=await import(asset('comparison-slate-views.js'));
 const root=new Element('section');let current=0,prices=0;const scopes=new Set();
 for (const b of fixture.boards) {
  const original=JSON.stringify(b);const game=fixture.games.find(g=>g.game_key===b.game_key);
  const renderer=createComparisonSlate({content:root,onOriginal:q=>{const detail=new Element('section');observationSummary(detail,q);assert(detail.textContent.includes('Current-peer difference'));},onDetails:()=>{}});
  renderer.draw({view:'odds',filter:'all',boards:[b],games:[game],errors:[],coverage:{},bounds:{},read_at:fixture.at,policy:b.policy},{view:'odds',filter:'all'});
  const selected=b.prices.find(q=>q.current_comparison?.available);
  const button=root.querySelectorAll('button').find(n=>n.dataset.key===b.game_key+':'+selected.quote_id);
  assert(button,'original price remains directly inspectable');button.onclick();
  assert.equal(comparisonState(selected.current_comparison,Date.parse(fixture.at)+30000),'current');
  assert.equal(comparisonState(selected.current_comparison,Date.parse(fixture.at)+30001),'last_known');
  prices+=b.prices.length;
  for(const q of b.prices){if(q.current_comparison?.available && q.current_comparison.display_status==='current'){current++;scopes.add([game.league,q.venue,q.market.market].join('|'));}}
  assert.equal(JSON.stringify(b),original,'Rendering preserves original captures');
 }
 assert.equal(prices,72);assert.equal(current,60);assert.equal(scopes.size,36);assert.equal(requests,0);
 console.log('PASS authored all six leagues × both natives × winner/spread/total: 72 displayed prices, 60 current directions, 36 positive source/type cells; zero dispatches and immutable originals');
})().catch(e=>{console.error(e);process.exitCode=1;});
