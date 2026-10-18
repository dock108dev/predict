// Authored late transport completions, independent readers and frozen display.
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {Element} = require('./ev07_dom.cjs');
const {fixture} = require('./current_board_fixture.cjs');
const asset = name => pathToFileURL(path.resolve('app/dashboard/opportunity_static/current',name)).href;
const copy = value => JSON.parse(JSON.stringify(value));
(async()=>{
  const {LatestRead,checkInputs,SavedReadPoller} = await import(asset('board-client.js'));
  const {renderOriginalDetails} = await import(asset('stored-details.js'));
  document.createTextNode=value=>{const n=new Element('span');n.textContent=value;return n;};
  const q=copy(fixture.odds.prices[0]);q.observation_revision='authored-observation';
  const frozen=JSON.stringify(q), context={game:fixture.odds.game_key};
  const identity={...q.inputs_identity,quote_revision:q.quote_revision,observation_revision:q.observation_revision,policy_revision:fixture.odds.policy.revision};
  const inputs={version:'predict-board-inputs-2',game_key:context.game,quote_id:q.quote_id,
    quote_revision:q.quote_revision,observation_revision:q.observation_revision,calculation_context:copy(fixture.odds.calculation_context),
    evidence:{original:copy(q.original),times:copy(q.times)}};
  const root=new Element('section');
  renderOriginalDetails(q,{evidence:{status:'Loading exact-frame contract and source evidence'}},{root,participants:fixture.catalog.games[0].participants});
  assert(root.textContent.includes('Native-side price') && root.textContent.includes(String(q.original.value)),'captured price renders before any read completes');
  const delivered=[],reader=new LatestRead(()=>new Promise(resolve=>delivered.push(resolve)));
  const validate=value=>checkInputs(value,context,identity);
  const first=reader.read('/inputs/old',validate);reader.cancel();
  const reopen=reader.read('/inputs/reopen',validate);
  const changed=reader.read('/inputs/different-selection',validate);
  delivered[1](new Response(JSON.stringify(inputs)));assert.equal(await reopen,null);
  delivered[0](new Response(JSON.stringify(inputs)));assert.equal(await first,null);
  delivered[2](new Response(JSON.stringify(inputs)));assert.deepEqual(await changed,inputs);
  assert.equal(JSON.stringify(q),frozen,'late supplementary inputs never rewrite captured price or clocks');
  const peer=new LatestRead(async()=>new Response(JSON.stringify(inputs)));
  const abandoned=reader.read('/inputs/abandoned',validate);reader.cancel();
  assert.deepEqual(await peer.read('/inputs/independent-tab',validate),inputs);
  delivered[3](new Response(JSON.stringify(inputs)));assert.equal(await abandoned,null);
  const crossed=copy(inputs);crossed.calculation_context.context_id='changed-context';
  await assert.rejects(new LatestRead(async()=>new Response(JSON.stringify(crossed))).read('/inputs/crossed',validate));
  const timeout=new LatestRead(async()=>new Response(JSON.stringify({error:'current_read_timeout',reason:'current_read_timeout'}),{status:504}));
  await assert.rejects(timeout.read('/inputs/timeout',validate),e=>e.code==='current_read_timeout');
  let open=true,reads=0;const timers=[];
  const poller=new SavedReadPoller({onRead:()=>reads++,canRead:()=>!open,setTimer:fn=>{timers.push(fn);return timers.length;},clearTimer:()=>{}});
  poller.schedule();assert.equal(timers.length,0);
  open=false;poller.schedule();assert.equal(timers.length,1);timers[0]();assert.equal(reads,1,'closing Details resumes normal polling independently of an abandoned selected read');
  console.log('PASS immediate frozen price, close/reopen/change supersession, crossed response refusal, independent tabs, bounded timeout and resumed polling; zero providers');
})().catch(error=>{console.error(error);process.exitCode=1;});
