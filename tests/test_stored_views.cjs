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
  const { renderSavedDetails } = await import(asset("stored-details.js"));
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
      "Original contracts, profiles and exact saved evidence",
    ),
  );
  assert.equal(nodes.history, root.children[root.children.length - 1]);
  assert.equal(nodes.advanced.parentNode, root);
  renderSavedDetails(fixture.pair, { root, participants });
  assert(root.textContent.includes("Leg 2 quantity"));
  assert(root.textContent.includes("Modeled outcomes"));
  console.log(
    "PASS pure Odds/EV/Arbs/Details rendering, original/selected callbacks, funding, empty-state action and evidence slots",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
