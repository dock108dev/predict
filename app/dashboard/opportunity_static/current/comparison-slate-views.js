import { numeric, money, percent } from "./board-client.js";
import { el, side, venue, words, time, price, metric, benchmark, labelsFor } from "./board-elements.js";

// Pure selection/presentation. Every callback keeps the original row and game;
// grouping never combines instrument identities, financial values or clocks.
export function crossVenue(row) {
  return row.legs?.length === 2 && row.legs.every(l => typeof l.venue === "string" && l.venue.length) && row.legs[0].venue !== row.legs[1].venue;
}
export function createComparisonSlate({ content, onDetails, onOriginal }) {
  function action(root, label, key, callback) {
    const button = el("button", label, "slate-action");
    button.dataset.key = key;
    button.onclick = () => callback(button);
    root.append(button);
    return button;
  }
  function heading(root, g) {
    const h = el("div", undefined, "slate-game-heading");
    h.append(el("h2", g.title), el("small", "Kickoff " + time(g.start_at)));
    root.append(h);
  }
  function delivery(b, paused) {
    return b.delivery_state === "pending" ? paused ? "Current updates paused" : "Calculation pending · prices available" : b.delivery_state === "stopped" ? "Collection stopped" : "";
  }
  function referenceEvidence(root, g, b) {
    const d = el("details", undefined, "reference-evidence");
    d.dataset.key = g.game_key + ":reference";
    d.append(el("summary", venue(b.benchmark.venue) + " reference · originals & method"));
    const { participant } = labelsFor(g.participants);
    d.append(el("p", words(b.benchmark.method) + " · " + words(b.benchmark.conditioning) + " · " + (b.benchmark.freshness === "current" ? "Current benchmark inputs" : "As-of benchmark")));
    for (const f of b.benchmark.fair || []) d.append(el("p", participant(f.participant) + " · fair decimal " + f.fair_decimal_odds + " · decisive probability " + f.decisive_probability));
    for (const o of b.benchmark.originals || []) d.append(el("p", participant(o.selection?.participant_id) + " · offered decimal " + o.decimal_odds + " · Source " + (o.book_at || o.market_at || "Unknown") + " · Received " + (o.received_at || "Unknown")));
    if (!b.benchmark.available) d.append(el("p", "Selected benchmark unavailable · " + words(b.benchmark.reason)));
    root.append(d);
  }
  function sourceClock(value) {
    return value ? new Date(value).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "Unknown";
  }
  function odds(g, b, paused) {
    const root = el("article", undefined, "slate-game slate-odds");
    root.dataset.key = g.game_key;
    heading(root, g);
    if (delivery(b, paused)) root.append(el("small", delivery(b, paused), "pending-label"));
    const table = el("div", undefined, "slate-prices");
    const books = ["novig", "prophetx", "kalshi", "polymarket_us"];
    for (const team of g.participants) {
      const row = el("div", undefined, "slate-price-row team");
      row.append(el("strong", team.name, "slate-team-name"));
      for (const book of books) {
        const cell = el("div", undefined, "slate-price-cell");
        cell.append(el("small", venue(book), "mobile-price-label"));
        // Use the supplied participant/predicate. Short is NOT opponent YES.
        const quotes = b.prices.filter(q => q.selection.participant === team.id && q.venue === book && q.selection.predicate === "win");
        if (!quotes.length) {
          const absent = el("span", "—", "unavailable-price");
          absent.title = venue(book) + " price unavailable for " + team.name;
          absent.setAttribute("aria-label", absent.title);
          cell.append(absent);
        }
        for (const q of quotes) {
          const native = q.native_side.toLowerCase() !== "bookmaker_outcome";
          const label = price(q) + (native ? " · " + side(q.native_side) : "");
          const button = action(cell, label, g.game_key + ":" + q.quote_id, button => onOriginal(q, button, g));
          const meaning = labelsFor(g.participants).selection(q) + " · " + venue(book) + " · original " + q.original.value + " " + words(q.original.units) + " · " + (q.freshness?.status === "current" ? "Current inputs" : "As-of inputs") + " · Source " + (q.freshness?.source_at || "Unknown") + " · Received " + (q.freshness?.received_at || "Unknown");
          button.title = meaning;
          button.setAttribute("aria-label", meaning + " · Open original price");
          const age = el("small", (q.freshness?.status === "current" ? "Source " : "As-of ") + sourceClock(q.freshness?.source_at), "compact-source-clock");
          age.title = meaning;
          cell.append(age);
        }
        row.append(cell);
      }
      const fair = el("div", undefined, "slate-price-cell slate-fair");
      benchmark(fair, b.benchmark, team.id);
      row.append(fair);
      table.append(row);
    }
    root.append(table);
    if (b.prices.some(q => q.native_side.toLowerCase() !== "bookmaker_outcome")) root.append(el("small", "Native sides retain their own tie/refund payouts · inspect Original for terms.", "native-meaning"));
    const alternatives = b.prices.filter(q => q.selection.predicate !== "win" || !g.participants.some(p => p.id === q.selection.participant));
    if (alternatives.length) {
      const d = el("details", undefined, "slate-alternatives");
      d.dataset.key = g.game_key + ":alternatives";
      d.append(el("summary", "Other native instruments · " + alternatives.length));
      for (const q of alternatives) action(d, labelsFor(g.participants).selection(q) + " · " + venue(q.venue) + " " + price(q), g.game_key + ":" + q.quote_id, button => onOriginal(q, button, g));
      root.append(d);
    }
    referenceEvidence(root, g, b);
    content.append(root);
  }
  function risk(row, b, view, paused) {
    const m = row.financial_metrics || {}, c = row.classification || {}, notes = [];
    if (row.freshness?.status !== "current") notes.push("As-of inputs");
    if (delivery(b, paused)) notes.push(delivery(b, paused));
    if (view === "ev" && row.benchmark_identity?.revision && row.benchmark_identity.revision !== b.benchmark.revision) notes.push("Reference changed · current basis in Details");
    if (view === "ev" && m.buffered_ev_usd == null) notes.push(m.conditional_buffered_ev_usd == null ? "EV unavailable" : "Conditional decisive EV · complete EV unknown");
    if (view === "arbs") {
      if (c.positive_rule_sensitive_eligible) notes.push("Rule-sensitive hedge");
      if (m.buffered_ev_usd == null) notes.push("Complete EV unknown");
      const adverse = Object.values(c.adverse_outcomes || {}).map(numeric).filter(v => v !== null);
      if (adverse.length) notes.push("Adverse outcome " + money(String(Math.min(...adverse))) + " before buffer");
      if (c.unknown_outcomes?.length || m.buffered_complete_modeled_minimum_usd == null) notes.push("Unknown outcome payouts");
    }
    if (numeric(row.funding?.residual_usd) >= 0.01) notes.push("Deployed " + money(row.funding.deployed_usd) + " · size limited");
    if (!notes.length) notes.push(c.main_positive_eligible ? "Modeled estimate · fills/fees unconfirmed" : words(c.reason || "Modeled comparison"));
    return notes.join(" · ");
  }
  const signedMoney = v => (numeric(v) > 0 ? "+" : "") + money(v);
  const signedPercent = v => (numeric(v) > 0 ? "+" : "") + percent(v);
  function financial(root, g, b, row, view, paused, rank) {
    const item = el("div", undefined, "slate-result " + (view === "arbs" ? "slate-arb" : "slate-ev"));
    item.dataset.key = g.game_key + ":" + (row.quote_id || row.pair_id);
    item.setAttribute("aria-label", g.title + " · rank " + rank);
    const identity = el("div", undefined, "slate-result-identity"), { selection } = labelsFor(g.participants);
    identity.append(el("small", "#" + rank, "comparison-rank"));
    if (view === "ev") identity.append(el("strong", venue(row.venue) + " " + price(row)));
    else for (const [i, leg] of row.legs.entries()) {
      const line = el("p", undefined, "slate-leg");
      line.append(el("strong", selection(leg)), el("span", venue(leg.venue) + " " + price(leg) + " · " + money(row.funding?.legs?.[i]?.deployed_capital_usd)));
      identity.append(line);
    }
    item.append(identity);
    const m = row.financial_metrics || {}, values = el("div", undefined, "slate-result-values");
    if (view === "ev") {
      const conditional = m.buffered_ev_usd == null;
      metric(values, conditional ? "Conditional EV · buffered" : "Complete EV · buffered", conditional ? m.conditional_buffered_ev_usd : m.buffered_ev_usd, signedMoney);
      metric(values, "Return on deployed", conditional ? m.conditional_buffered_return_percent : m.buffered_return_percent, signedPercent);
    } else {
      metric(values, "Decisive margin · buffered", m.buffered_decisive_opposing_margin_usd, signedMoney);
      metric(values, "Decisive return", m.buffered_decisive_return_percent, signedPercent);
      values.append(el("small", "Modeled minimum · buffered " + money(m.buffered_complete_modeled_minimum_usd) + " · " + percent(m.buffered_complete_minimum_return_percent), "modeled-minimum"));
      values.append(el("small", "Combined deployment " + money(row.funding?.deployed_usd)));
    }
    item.append(values);
    const note = el("small", risk(row, b, view, paused), "slate-result-note");
    note.title = "Calculation as-of " + b.result_as_of + " · " + words(row.classification?.reason) + " · " + (row.freshness?.reasons || []).map(words).join(" · ");
    item.append(note);
    action(item, "Details", item.dataset.key, button => onDetails(row, button, g));
    root.append(item);
  }
  function score(row, view) {
    const m = row.financial_metrics || {};
    return numeric(view === "ev" ? m.buffered_ev_usd ?? m.conditional_buffered_ev_usd : m.buffered_complete_modeled_minimum_usd ?? m.buffered_decisive_opposing_margin_usd) ?? -Infinity;
  }
  function advancedHistory(boards, visible) {
    const saved = boards.flatMap(b => b.rows.filter(r => r.legs?.length === 2 && r.legs[0].venue === r.legs[1].venue).map(row => ({ b, row, g: visible.get(b.game_key) })));
    const d = el("details", undefined, "same-venue-history");
    d.dataset.key = "advanced-same-venue";
    d.append(el("summary", "Advanced current portfolios · same venue"));
    d.append(el("p", "Outside ordinary cross-venue Arbs. Original calculations remain unchanged. Use All comparisons to inspect all available current portfolios here."));
    for (const { row, g } of saved) action(d, g.title + " · " + row.legs.map(l => labelsFor(g.participants).selection(l) + " / " + venue(l.venue)).join(" + ") + " · Details", g.game_key + ":" + row.pair_id, button => onDetails(row, button, g));
    content.append(d);
  }
  function draw(v, { view, filter, game = "", search = "", sort = "best", onShowAll }) {
    content.replaceChildren();
    content.classList.toggle("compact-odds", view === "odds");
    content.classList.toggle("compact-comparisons", view !== "odds");
    const visible = new Map(v.games.filter(g => (!game || g.game_key === game) && g.title.toLowerCase().includes(search.toLowerCase())).map(g => [g.game_key, g]));
    const boards = v.boards.filter(b => visible.has(b.game_key)), paused = v.storage?.state === "unavailable";
    const rows = boards.flatMap(b => b.rows.filter(row => view !== "arbs" || crossVenue(row)).map(row => ({ g: visible.get(b.game_key), b, row })));
    rows.sort((a, b) => score(b.row, view) - score(a.row, view) || (a.g.start_at || "").localeCompare(b.g.start_at || ""));
    rows.forEach((entry, i) => entry.rank = i + 1);
    const summary = el("div", undefined, "slate-summary");
    summary.append(el("strong", visible.size + " of " + v.games.length + " games"));
    if (view !== "odds") summary.append(el("span", rows.length + (view === "arbs" ? " cross-venue comparisons" : " comparisons") + " · " + (filter === "all" ? "all current results" : filter === "hedges" ? "positive rule-sensitive hedges" : "eligible positive results")));
    content.append(summary);
    const coverage = el("div", undefined, "slate-coverage");
    coverage.append(el("small", "Current coverage"));
    for (const book of ["novig", "prophetx", "kalshi", "polymarket_us", "pinnacle"]) coverage.append(el("span", venue(book) + " " + v.boards.filter(b => b.prices.some(q => q.venue === book) || (b.benchmark.venue === book && b.benchmark.available)).length + "/" + v.games.length));
    content.append(coverage);
    if (!visible.size) {
      const empty = el("div", undefined, "empty");
      empty.append(el("h2", v.games.length ? "No games match this filter" : "No current games yet"), el("p", v.games.length ? "Clear the team search or choose All games." : "Open Admin to check your source setup."));
      if (!v.games.length) { const a = el("a", "Check sources in Admin"); a.href = "/admin"; empty.append(a); }
      content.append(empty);
      return;
    }
    if (view === "odds") {
      const h = el("div", undefined, "slate-price-headings slate-shared-headings");
      h.append(el("span", "Game / team"), ...["novig", "prophetx", "kalshi", "polymarket_us"].map(book => el("span", venue(book))), el("span", venue(v.policy.benchmark_venue) + " reference"));
      content.append(h);
      for (const g of visible.values()) {
        const b = boards.find(b => b.game_key === g.game_key);
        if (b) odds(g, b, paused);
        else content.append(el("p", g.title + " · Current prices unavailable"));
      }
      return;
    }
    if (!rows.length) {
      const empty = el("div", undefined, "empty");
      empty.append(el("h2", filter === "all" ? "No current comparisons available" : filter === "hedges" ? "No positive rule-sensitive hedges" : view === "arbs" ? "No estimated arbitrage found" : "No positive EV found"), el("p", "This applies across all visible games and your settings. " + (filter === "all" ? "Prices remain available in Odds." : "Signed and conditional comparisons remain under All comparisons.")));
      if (filter !== "all") { const button = el("button", "Show all comparisons"); button.onclick = onShowAll; empty.append(button); }
      content.append(empty);
    }
    const groups = new Map();
    for (const entry of rows) {
      if (!groups.has(entry.g.game_key)) groups.set(entry.g.game_key, []);
      groups.get(entry.g.game_key).push(entry);
    }
    const ordered = [...groups.values()];
    if (sort === "start") ordered.sort((a, b) => (a[0].g.start_at || "").localeCompare(b[0].g.start_at || ""));
    if (rows.length) content.append(el("small", sort === "start" ? "Games ordered by kickoff · # shows rank across games" : "Games ordered by best buffered value · # shows rank across games", "ranking-help"));
    for (const entries of ordered) {
      const { g, b } = entries[0], root = el("article", undefined, "slate-comparison-game");
      root.dataset.key = g.game_key;
      heading(root, g);
      if (view === "ev") {
        const instruments = new Map();
        for (const entry of entries) {
          // All economically identifying fields are retained, including native
          // side, period and outcome ID; no values are aggregated.
          const key = JSON.stringify([Object.entries(entry.row.selection).sort(([a], [b]) => a.localeCompare(b)), entry.row.native_side]);
          if (!instruments.has(key)) instruments.set(key, []);
          instruments.get(key).push(entry);
        }
        for (const instrument of instruments.values()) {
          const section = el("section", undefined, "slate-instrument"), row = instrument[0].row;
          section.append(el("h3", labelsFor(g.participants).selection(row)));
          const reference = el("div", undefined, "instrument-reference");
          benchmark(reference, b.benchmark, row.selection.participant);
          section.append(reference);
          for (const e of instrument) financial(section, g, b, e.row, view, paused, e.rank);
          root.append(section);
        }
        referenceEvidence(root, g, b);
      } else for (const e of entries) financial(root, g, b, e.row, view, paused, e.rank);
      content.append(root);
    }
    const missing = boards.filter(b => !b.rows.length && (b.delivery_state === "pending" || filter === "all"));
    const errors = (v.errors || []).filter(e => visible.has(e.game_key));
    if (missing.length || errors.length) {
      const d = el("details", undefined, "slate-pending");
      d.dataset.key = "pending-games";
      d.append(el("summary", missing.length + errors.length + " games with no current calculations"));
      for (const b of missing) d.append(el("p", visible.get(b.game_key).title + " · " + (delivery(b, paused) || words(b.empty_reason)) + " · Original prices in Odds"));
      for (const e of errors) d.append(el("p", visible.get(e.game_key).title + " · " + words(e.reason)));
      content.append(d);
    }
    if (view === "arbs") advancedHistory(boards, visible);
  }
  return { draw };
}
