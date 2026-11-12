// Disposable render and adoption evidence. Run from the repository root.
const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {Element} = require('./ev07_dom.cjs');

global.Node = Element;
global.window = {};
document.querySelector = () => null;
document.createDocumentFragment = () => new Element('fragment');
const append = Element.prototype.append;
Element.prototype.append = function (...children) {
  append.call(this, ...children.map(child => {
    if (child instanceof Element) return child;
    const node = new Element('text');
    node.textContent = child;
    return node;
  }));
};

async function check() {
  const [ev, arbs, latest, details, census] = JSON.parse(execFileSync(process.env.PYTHON || '.venv/bin/python', ['-c',
    'from browser_tests.test_fee_desk import data; import json; print(json.dumps(data()))']));
  await import('../app/dashboard/opportunity_static/current/ui-common.js');
  const {tradeInspection, pairInspection, tradingFeeLabel, tradingFeeSize} =
    await import('../app/dashboard/opportunity_static/current/desk-inspection.js');
  const {pinLatestSelection, selectionIdentity, pinnedInspection} =
    await import('../app/dashboard/opportunity_static/current/desk-evidence.js');
  const {feeCensusLines, mountFeeCensus} =
    await import('../app/dashboard/opportunity_static/current/fee-census-view.js');

  const group = ev.rows.find(g => g.offers.some(o => o.id === 'prophetx-offer'));
  const old = group.offers.find(o => o.id === 'prophetx-offer');
  assert.equal(tradingFeeLabel(old.trade_fee), 'Trading fee $0.01 at fill · Conservative estimate');
  assert.equal(tradingFeeSize(old.trade_fee), '1 $1-payout contract · 1 immediate taker fill');
  const before = tradeInspection(old, group, details[old.id + ':old'], {position:'Fixture'});
  assert.match(before.textContent, /At fill/);
  assert.match(before.textContent, /Modeled size1 \$1-payout contract/);
  assert.match(before.textContent, /exact current Pinnacle match is unavailable/);
  const after = tradeInspection(latest, group, details[latest.id + ':latest'], {position:'Fixture'});
  assert.match(after.textContent, /\$0\.00/);
  assert.match(after.textContent, /8 decimal/);
  assert.match(after.textContent, /Reviewed-fee EV/);
  assert.match(after.textContent, /Conservative EV/);

  // Authority-only changes can keep both saved revisions. They must still
  // invalidate an in-flight adoption and suppress an older reference in detail.
  const withdrawn = {...latest, reference_current:false, trade_fee:{available:false, reason:'conditional_fee_review_expired_or_not_effective'}};
  assert.notEqual(selectionIdentity(latest), selectionIdentity(withdrawn));
  assert.notEqual(selectionIdentity(latest), selectionIdentity({...latest, reference_current:false}));
  assert.notEqual(selectionIdentity(latest), selectionIdentity({...latest, trade_fee:withdrawn.trade_fee}));
  assert.equal(selectionIdentity(latest), selectionIdentity({...latest, confirmed_at:'later'}));
  const pinned = pinnedInspection(withdrawn, details[latest.id + ':latest'].inspection);
  assert.equal(pinned.fair_reference.available, false);
  assert.equal(details[latest.id + ':latest'].inspection.fair_reference.available, true);
  const released = [];
  let active = true, frames;
  const adopt = () => pinLatestSelection({
    read: async () => frames.shift(),
    pin: async offer => ({lease:'new', evidence:details[offer.id + ':latest']}),
    release: lease => released.push(lease),
    isActive: () => active
  });
  frames = [latest, withdrawn];
  assert.deepEqual(await adopt(), {state:'changed'});
  assert.deepEqual(released, ['new']);
  frames = [latest, latest];
  const adopted = await adopt();
  assert.equal(adopted.state, 'ready');
  assert.equal(adopted.offer.trade_fee.trade_fee_usd, '0');
  assert.equal(adopted.evidence.inspection.fair_reference.pair[0].original.value, '8');
  frames = [null];
  assert.deepEqual(await adopt(), {state:'unavailable'});
  assert.deepEqual(released, ['new']);
  active = false;
  frames = [latest];
  assert.deepEqual(await adopt(), {state:'closed'});
  assert.deepEqual(released, ['new']);
  const stale = ev.rows.flatMap(g => g.offers).find(o => o.id === 'expired');
  const expired = tradeInspection(stale, group, details[stale.id + ':stale'], {position:'Fixture'});
  assert.match(expired.textContent, /The fee review does not cover this capture time/);
  assert.doesNotMatch(expired.textContent, /conditional_fee_review_expired_or_not_effective/);
  const commission = ev.rows.flatMap(g => g.offers).find(o => o.id === 'commission');
  assert.match(tradingFeeLabel(commission.trade_fee), /\$0\.02 at settlement if it wins/);
  const settlement = tradeInspection(commission, group, details['commission:commission'], {position:'Fixture'});
  assert.match(settlement.textContent, /Winning settlement/);
  assert.match(settlement.textContent, /Fee if it loses\$0\.00/);
  const aggregateEvidence = structuredClone(details['commission:commission']);
  aggregateEvidence.inspection.source.provider = 'sportsgameodds';
  aggregateEvidence.inspection.starting_fee_terms = {values:[['Formula','venue formula']],scope:'venue scope'};
  aggregateEvidence.inspection.settlement = {scoring:{},outcomes:[],wording:[],fictional:false};
  const aggregate = tradeInspection(commission, group, aggregateEvidence, {position:'Fixture'});
  assert.match(aggregate.textContent, /Illustrative outcomes · contract rules unverified/);
  assert.doesNotMatch(aggregate.textContent, /venue formula/);
  const sgoEvidence = structuredClone(details[latest.id + ':latest']);
  sgoEvidence.inspection.fair_reference = {available:true, venue:'pinnacle', contract:{phase:'live'},
    probability:'1/2', fair_decimal_odds:'2', maximum_age_seconds:15,
    contributors:[{venue:'pinnacle',inputs:[{side:'home',price_american:'-110',source_at:'2026-11-10T20:00:00Z'},
      {side:'away',price_american:'-110',source_at:'2026-11-10T20:00:00Z'}]}]};
  const sgoDrawer = tradeInspection({...latest, reference_current:true}, group, sgoEvidence, {position:'Fixture'});
  assert.match(sgoDrawer.textContent, /Pinnacle pair via SportsGameOdds/i);
  assert.match(sgoDrawer.textContent, /Maximum source age15 seconds/);
  const sportsbook = {book:'fanduel', candidate_books:3, probability:'25/58', return_percent:'100/29',
    prices:[{price_american:'+120', source_at:'2026-11-10T20:00:00Z'},
            {price_american:'-150', source_at:'2026-11-10T20:00:00Z'}]};
  const withBook = tradeInspection({...latest, sportsbook}, group, sgoEvidence, {position:'Fixture'});
  assert.match(withBook.textContent, /Before-fee estimate3\.45%/);
  assert.match(withBook.textContent, /Selected bookFanDuel/);
  assert.match(withBook.textContent, /Opposite odds-150 American/);
  assert.notEqual(selectionIdentity(latest), selectionIdentity({...latest, sportsbook}));

  for (const row of arbs.rows) {
    const drawer = pairInspection(row.pairs[0], new Map(row.offers.map(o => [o.id, o])),
      {group:row, position:() => 'Fixture', inspect:() => {}});
    assert.match(drawer.textContent, /Cent-rounded stake\$44\.44/);
    assert.match(drawer.textContent, /Cent-rounded stake\$55\.56/);
    assert.match(drawer.textContent, /Fee at fill\$0\.93/);
    if (row.pairs[0].retail_payoff.available) assert.match(drawer.textContent, /\$10\.17 net profit/);
    else assert.match(drawer.textContent, /Both leg fees are needed/);
  }
  const lines = Object.fromEntries(feeCensusLines(census));
  assert.match(lines['Trading fees'], /3 of 4/);
  assert.equal(lines['Exact Pinnacle references'], '2');
  assert.match(lines['EV results'], /0 reviewed fees · 1 conservative/);
  assert.match(lines['Source prices'], /8 working prices published · 5 working prices unpublished/);
  assert.match(lines['Fee gaps among current offers'], /fee review does not cover/);
  const requests = [];
  global.fetch = async (path, options) => {
    requests.push([path, options.method || 'GET']);
    return {ok:true, json:async () => census};
  };
  const coverage = new Element('div'), admin = new Element('div'), download = new Element('button');
  await mountFeeCensus(coverage, download)();
  await mountFeeCensus(admin)();
  assert.equal(coverage.textContent, admin.textContent);
  assert.equal(download.disabled, false);
  assert.deepEqual(requests, Array(2).fill(['/api/comparison-current/fee-coverage', 'GET']));
  console.log('PASS F07 DOM fixtures: fee, size, timing, pinned reference withdrawal, arb payoffs and owner counts');
}

check().catch(error => { console.error(error); process.exitCode = 1; });
