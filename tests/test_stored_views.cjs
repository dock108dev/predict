// Authored render-only regression: no browser, provider, SQL or owner state.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { Element } = require("./ev07_dom.cjs");

document.createTextNode = (value) => {
  const node = new Element("span");
  node.textContent = value;
  return node;
};
global.fetch = () => {
  throw Error("A renderer cannot acquire data");
};
const fixture = JSON.parse(
  fs.readFileSync("tests/fixtures/ev09-u01-responses.json"),
);
const asset = (name) =>
  pathToFileURL(path.resolve("app/dashboard/opportunity_static/current", name))
    .href;

(async () => {
  const { createBoardViews } = await import(asset("stored-views.js"));
  const { renderSavedDetails, renderOriginalDetails } = await import(asset("stored-details.js"));
  const participants = fixture.catalog.games[0].participants;
  const content = new Element("section"),
    originals = [],
    selected = [];
  const views = createBoardViews({
    content,
    participants,
    onOriginal: (quote, button) => originals.push([quote, button]),
    onDetails: (row, button) => selected.push([row, button]),
  });
  views.draw(fixture.odds, { view: "odds", filter: "all" });
  assert(content.querySelectorAll(".team").length > 0);
  const original = content
    .querySelectorAll("button")
    .find((b) => b.textContent === "Original price");
  original.onclick();
  assert.equal(originals[0][0].quote_id, original.dataset.key);
  assert.equal(originals[0][1], original);
  views.draw(fixture.ev, { view: "ev", filter: "all" });
  assert(content.textContent.includes("Complete EV after costs + buffer"));
  const inspect = content
    .querySelectorAll("button")
    .find((b) => b.textContent === "Details");
  inspect.onclick();
  assert.equal(selected[0][0].quote_id, inspect.dataset.key);
  assert(
    content.textContent.includes("residual"),
    "funding disclosure survives extraction",
  );
  views.draw(fixture.arbs, { view: "arbs", filter: "all" });
  assert(content.textContent.includes("Decisive margin after costs + buffer"));
  assert(content.textContent.includes("Minimum across modeled outcomes"));
  assert(content.querySelectorAll(".leg").length >= 2);
  let showAll = 0;
  views.draw(
    { ...fixture.ev, rows: [] },
    { view: "ev", filter: "positive", onShowAll: () => showAll++ },
  );
  const all = content
    .querySelectorAll("button")
    .find((b) => b.textContent === "Show all comparisons");
  all.onclick();
  assert.equal(showAll, 1);
  const root = new Element("section");
  const nodes = renderSavedDetails(fixture.single, { root, participants });
  assert(root.textContent.includes("One buffer on deployed amount"));
  assert(
    root.textContent.includes(
      "Original contracts, profiles and current calculation evidence",
    ),
  );
  assert.equal(nodes.advanced, root.children[root.children.length - 1]);
  assert.equal(nodes.advanced.parentNode, root);
  renderSavedDetails(fixture.pair, { root, participants });
  assert(root.textContent.includes("Leg 2 quantity"));
  assert(root.textContent.includes("Modeled outcomes"));
  assert(root.textContent.includes("Requested funding"));
  assert(root.textContent.includes("Minimum across modeled outcomes · buffered"));
  assert(root.querySelectorAll('.detail-outcomes').length===1);
  const conditional=JSON.parse(JSON.stringify(fixture.single));
  conditional.quote.calculations.funded_estimate.financial_metrics.buffered_ev_usd=null;
  conditional.quote.calculations.funded_estimate.financial_metrics.conditional_buffered_ev_usd='12.34';
  renderSavedDetails(conditional,{root,participants});
  assert(root.textContent.includes("Conditional EV · buffered"));
  assert(root.textContent.includes("$12.34"));
  assert(root.textContent.includes("Complete modeled EV unavailable"));
  const q=JSON.parse(JSON.stringify(fixture.odds.prices[0]));
  Object.assign(q,{quote_revision:7,observation_revision:'authored-source-frame-7',source_state:'available',source_health:{state:'available',reason:'Book synchronized'},market:{market:'winner',period:'full_game',period_boundary:'Including overtime'},observed_depth:{available:true,levels:[{price:'0.430000000001',quantity:'12.500000001'}],total_levels:9,truncated:true,quantity_units:'contracts',price_units:'usd_per_contract',source_at:'2026-10-17T13:00:00.123456+00:00',received_at:'2026-10-17T13:00:00.456789+00:00'},gross_comparison:{available:false,reason:'occurrence_identity_ambiguous'}});
  q.observed_depth.clock_basis='current_native_book';q.observed_depth.book_revision=11;
  const originalBefore=JSON.stringify(q),inputs={evidence:{original:q.original},estimate_availability:{state:'unavailable',reason_codes:['selected_reference_missing']}};
  renderOriginalDetails(q,inputs,{root,participants,title:'Authored source game'});
  for(const fact of ['Native-side price','authored-source-frame-7','Quote revision: 7','Book synchronized','Observed book depth','0.430000000001','12.500000001','contracts','1 of 9 retained levels shown','2026-10-17T13:00:00.123456+00:00',q.times.received_at,'Estimates unavailable','selected_reference_missing','occurrence identity ambiguous'])assert(root.textContent.includes(fact),fact);
  assert.equal(JSON.stringify(q),originalBefore,'Details retains the selected exact source frame');
  assert(root.textContent.includes('Book clock basis: current native book'));assert(root.textContent.includes('Stored book revision: 11'));
  q.observed_depth={available:false,levels:[],quantity_units:'unknown'};renderOriginalDetails(q,inputs,{root,participants});assert(root.textContent.includes('Observed depth unknown'));
  console.log(
    "PASS pure Odds/EV/Arbs/Details rendering, original/selected callbacks, funding, empty-state action and evidence slots",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
