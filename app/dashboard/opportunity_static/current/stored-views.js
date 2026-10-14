import { numeric, money, percent, quantity } from "./board-client.js";
import {
  el,
  side,
  unit,
  venue,
  words,
  time,
  residual,
  textLine,
  metric,
  freshness,
  price,
  benchmark,
  labelsFor,
} from "./board-elements.js";

export function createBoardViews({
  content,
  participants,
  onDetails,
  onOriginal,
}) {
  const { selection, outcome } = labelsFor(participants);
  function detailButton(root, row) {
    const b = el("button", "Details");
    b.dataset.key = row.quote_id || row.pair_id;
    b.onclick = () => onDetails(row, b);
    root.append(b);
  }
  function odds(v) {
    const board = el("div", undefined, "odds-board");
    content.append(board);
    const prices = v.prices,
      teams =
        participants ||
        [...new Set(prices.map((q) => q.selection.participant))].map((id) => ({
          id,
          name: id,
        }));
    for (const team of teams) {
      const section = el("article", undefined, "team");
      section.append(el("h2", team.name));
      const grid = el("div", undefined, "quotes");
      for (const book of ["novig", "prophetx", "kalshi", "polymarket_us"]) {
        const box = el("div", undefined, "quote");
        box.append(el("small", venue(book)));
        const qs = prices.filter(
          (q) =>
            q.selection.participant === team.id &&
            q.venue === book &&
            q.selection.predicate === "win" &&
            !["no", "short"].includes(q.native_side.toLowerCase()),
        );
        if (!qs.length)
          box.append(el("strong", "—"), el("small", "Price unavailable"));
        for (const q of qs) {
          box.append(
            el("strong", price(q)),
            el(
              "small",
              q.native_side === "bookmaker_outcome"
                ? "Winner price"
                : side(q.native_side) +
                    " · " +
                    quantity(q.original.value) +
                    " " +
                    words(q.original.units),
            ),
          );
          freshness(box, q.freshness);
          const b = el("button", "Original price");
          b.dataset.key = q.quote_id;
          b.onclick = () => onOriginal(q, b);
          box.append(b);
        }
        grid.append(box);
      }
      const fair = el("div", undefined, "quote fair");
      benchmark(fair, v.benchmark, team.id);
      grid.append(fair);
      section.append(grid);
      board.append(section);
    }
    const alternatives = prices.filter(
      (q) =>
        q.selection.predicate !== "win" ||
        ["no", "short"].includes(q.native_side.toLowerCase()),
    );
    if (alternatives.length) {
      const d = el("details", undefined, "native-alternatives");
      d.dataset.key = "alternatives";
      d.append(
        el(
          "summary",
          "Native alternatives · " +
            alternatives.length +
            " original instruments",
        ),
      );
      for (const q of alternatives) {
        const p = el("article", undefined, "card");
        p.append(
          el("h3", selection(q)),
          el("p", venue(q.venue) + " · " + price(q)),
        );
        textLine(
          p,
          "Native price",
          quantity(q.original.value) + " " + words(q.original.units),
        );
        freshness(p, q.freshness);
        const b = el("button", "Original contract");
        b.dataset.key = q.quote_id;
        b.onclick = () => onOriginal(q, b);
        p.append(b);
        d.append(p);
      }
      content.append(d);
    }
  }
  function adverse(root, c) {
    const items = Object.entries(c?.adverse_outcomes || {});
    if (items.length || c?.unknown_outcomes?.length) {
      const p = el("div", undefined, "warning");
      p.append(el("strong", "Adverse outcomes before buffer"));
      for (const [state, value] of items)
        p.append(el("p", outcome(state) + ": " + money(value)));
      for (const state of c?.unknown_outcomes || [])
        p.append(el("p", outcome(state) + ": Unknown"));
      root.append(p);
    }
  }
  function ev(v) {
    const cards = el("div", undefined, "cards");
    for (const row of v.rows) {
      const root = el("article", undefined, "card"),
        identity = el("div", undefined, "ev-identity");
      identity.append(
        el("h3", selection(row)),
        el("p", venue(row.venue) + " · " + price(row)),
      );
      root.append(identity);
      const fair = el("div", undefined, "fair quote");
      benchmark(fair, v.benchmark, row.selection.participant);
      root.append(fair);
      const m = row.financial_metrics || {},
        metrics = el("div", undefined, "metrics");
      metric(metrics, "Complete EV after costs + buffer", m.buffered_ev_usd);
      metric(
        metrics,
        "Return on deployed amount",
        m.buffered_return_percent,
        percent,
      );
      root.append(metrics);
      if (row.selection.predicate !== "win")
        root.append(
          el(
            "small",
            "The reference describes a decisive team win. " +
              side(row.native_side) +
              " / " +
              words(row.selection.predicate) +
              " retains its own modeled payouts.",
            "warning",
          ),
        );
      if (m.buffered_ev_usd == null && m.conditional_buffered_ev_usd != null) {
        const note = el("div", undefined, "warning");
        note.append(
          el("strong", "Conditional decisive EV · complete EV unknown"),
          el(
            "p",
            money(m.conditional_buffered_ev_usd) +
              " · " +
              percent(m.conditional_buffered_return_percent),
          ),
          el(
            "small",
            words(row.classification?.condition || m.reconciliation_condition),
          ),
        );
        root.append(note);
      }
      const meta = el("div", undefined, "ev-meta");
      textLine(
        meta,
        "Deployed / residual",
        money(row.funding?.deployed_usd) +
          " / " +
          residual(row.funding?.residual_usd),
      );
      freshness(meta, row.freshness);
      const reason = row.classification?.reason || row.reasons?.join(" · ");
      if (reason && reason !== "buffered value is zero or negative")
        meta.append(el("small", words(reason)));
      root.append(meta);
      detailButton(root, row);
      cards.append(root);
    }
    content.append(cards);
  }
  function arbs(v) {
    for (const row of v.rows) {
      const root = el("article", undefined, "card arbs-card");
      root.append(
        el(
          "h2",
          row.classification?.positive_rule_sensitive_eligible
            ? "Rule-sensitive hedge"
            : row.classification?.main_positive_eligible
              ? "Complete modeled opportunity"
              : "Opposing comparison",
        ),
      );
      const legs = el("div", undefined, "legs");
      for (const [i, leg] of row.legs.entries()) {
        const p = el("div", undefined, "leg");
        p.append(
          el("strong", selection(leg)),
          el("p", venue(leg.venue) + " · " + price(leg)),
        );
        textLine(
          p,
          "Quantity",
          quantity(leg.native_quantity) + " " + unit(leg.native_unit?.unit),
        );
        textLine(
          p,
          "Allocation",
          money(row.funding?.legs?.[i]?.deployed_capital_usd),
        );
        textLine(
          p,
          "Acquisition / upfront fees",
          money(leg.acquisition_usd) + " / " + money(leg.upfront_fee_usd),
        );
        legs.append(p);
      }
      root.append(legs);
      const m = row.financial_metrics || {},
        metrics = el("div", undefined, "metrics");
      metric(
        metrics,
        "Decisive margin after costs + buffer",
        m.buffered_decisive_opposing_margin_usd,
      );
      metric(
        metrics,
        "Decisive return",
        m.buffered_decisive_return_percent,
        percent,
      );
      metric(
        metrics,
        "Minimum across modeled outcomes",
        m.buffered_complete_modeled_minimum_usd,
      );
      metric(
        metrics,
        "All-outcome return",
        m.buffered_complete_minimum_return_percent,
        percent,
      );
      root.insertBefore(metrics, legs);
      textLine(
        root,
        "Combined deployed / residual",
        money(row.funding?.deployed_usd) +
          " / " +
          residual(row.funding?.residual_usd),
      );
      textLine(root, "One opportunity buffer", money(m.buffer_usd));
      if (m.buffered_ev_usd == null)
        root.append(
          el(
            "small",
            "Complete EV unknown" +
              (m.conditional_buffered_ev_usd != null
                ? " · Conditional decisive EV " +
                  money(m.conditional_buffered_ev_usd)
                : ""),
          ),
        );
      adverse(root, row.classification);
      freshness(root, row.freshness);
      root.append(el("small", words(row.classification?.reason)));
      detailButton(root, row);
      content.append(root);
    }
  }
  function draw(v, { view, filter, onShowAll }) {
    content.replaceChildren();
    if (!v.rows.length) {
      const empty = el("div", undefined, "empty");
      empty.append(
        el(
          "h2",
          v.empty_reason ||
            (view === "odds"
              ? "No available prices"
              : "No eligible comparisons"),
        ),
        el(
          "p",
          v.delivery_state === "pending"
            ? "Your settings are being calculated. Original prices remain available below."
            : view === "odds"
              ? "Prices will appear when a source supplies them. Check source status in Admin."
              : filter === "positive"
                ? "There are no eligible positive results for this game and these settings."
                : "No calculations are available for this selection. Check source status in Admin.",
        ),
      );
      if (
        view !== "odds" &&
        filter !== "all" &&
        v.delivery_state !== "pending"
      ) {
        const show = el("button", "Show all comparisons");
        show.onclick = onShowAll;
        empty.append(show);
      }
      content.append(empty);
    }
    if (view === "odds") odds(v);
    else if (view === "ev") ev(v);
    else arbs(v);
    if (v.delivery_state === "pending" && view !== "odds") {
      const d = el("details");
      d.dataset.key = "pending-prices";
      d.append(el("summary", "Original prices while calculations are pending"));
      for (const q of v.prices)
        d.append(
          el("p", selection(q) + " · " + venue(q.venue) + " " + price(q)),
        );
      content.append(d);
    }
  }
  return { draw };
}

// The slate formats server-owned values. Details retains each row's own game,
// result and snapshot rather than borrowing the optional screen filter.
export function createSlateViews({ content, onDetails, onOriginal }) {
  function action(root, label, key, callback) {
    const b = el("button", label, "slate-action");
    b.dataset.key = key;
    b.onclick = () => callback(b);
    root.append(b);
    return b;
  }
  function shortClock(value) {
    if (!value) return "Unknown";
    return new Date(value).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).replace(",", "").replace(" AM", "a").replace(" PM", "p");
  }
  function fullClock(value) {
    return time(value) + (value ? " [" + value + "]" : "");
  }
  function gameHeading(root, g, b, paused) {
    const heading = el("div", undefined, "slate-game-heading");
    heading.append(el("h2", g.title), el("small", "Kickoff " + shortClock(g.start_at)));
    heading.title = "Kickoff " + fullClock(g.start_at);
    root.append(heading);
    if (b.delivery_state === "pending")
      root.append(el("small", paused ? "Saved updates paused · prices retained" : b.result_id ? "Calculation pending · prior saved result" : "Calculation pending · prices available", "pending-label"));
    if (b.delivery_state === "stopped") root.append(el("small", "Collection stopped · saved inputs", "pending-label"));
  }
  function odds(g, b, paused) {
    const root = el("article", undefined, "slate-game slate-odds");
    root.dataset.key = g.game_key;
    gameHeading(root, g, b, paused);
    const table = el("div", undefined, "slate-prices");
    const books = ["novig", "prophetx", "kalshi", "polymarket_us"];
    for (const team of g.participants) {
      const row = el("div", undefined, "slate-price-row team");
      row.append(el("strong", team.name, "slate-team-name"));
      for (const book of books) {
        const cell = el("div", undefined, "slate-price-cell");
        cell.append(el("small", venue(book), "mobile-price-label"));
        const quotes = b.prices.filter(q => q.selection.participant === team.id && q.venue === book && q.selection.predicate === "win" && !["no", "short"].includes(q.native_side.toLowerCase()));
        if (!quotes.length) {
          const absent = el("span", "—", "unavailable-price");
          absent.title = venue(book) + " price unavailable for " + team.name + " in this game";
          absent.setAttribute("aria-label", absent.title);
          cell.append(absent);
        }
        for (const q of quotes) {
          const button = action(cell, price(q), g.game_key + ":" + q.quote_id, button => onOriginal(q, button, g));
          const meaning = team.name + " · " + venue(book) + " · " + side(q.native_side) + " · " + words(q.selection.predicate) + " · original " + String(q.original.value ?? "Unknown") + " " + words(q.original.units) + " · " + (q.freshness?.status === "current" ? "Current inputs" : "As-of inputs") + " · Source " + fullClock(q.freshness?.source_at) + " · Received " + fullClock(q.freshness?.received_at) + (q.freshness?.reasons?.length ? " · " + q.freshness.reasons.map(words).join(" · ") : "") + " · Open original price";
          button.title = meaning;
          button.setAttribute("aria-label", meaning);
          const clock = el("small", (q.freshness?.status === "current" ? "" : "As-of ") + shortClock(q.freshness?.source_at) + (q.native_side === "bookmaker_outcome" ? "" : " · " + side(q.native_side)), "compact-source-clock");
          clock.title = meaning;
          cell.append(clock);
        }
        row.append(cell);
      }
      const fair = el("div", undefined, "slate-price-cell slate-fair");
      const reference = b.benchmark.fair.find(f => f.participant === team.id);
      fair.append(el("small", venue(b.benchmark.venue) + " fair", "mobile-price-label"));
      if (reference) fair.append(el("strong", numeric(reference.fair_decimal_odds).toFixed(3)), el("small", (b.benchmark.freshness === "current" ? "" : "As-of ") + percent(String(numeric(reference.decisive_probability) * 100)) + " decisive"));
      else fair.append(el("strong", "—"), el("small", "Benchmark missing"));
      fair.title = venue(b.benchmark.venue) + " fair benchmark · " + (reference ? b.benchmark.freshness === "current" ? "Current benchmark" : "As-of benchmark" : words(b.benchmark.reason)) + " · " + words(b.benchmark.conditioning) + " · " + (b.benchmark.originals || []).map(original => String(original.decimal_odds ?? "Unknown") + " original decimal odds · Source " + fullClock(original.book_at || original.market_at) + " · Received " + fullClock(original.received_at)).join("; ");
      fair.setAttribute("aria-label", fair.title);
      row.append(fair);
      table.append(row);
    }
    root.append(table);
    const alternatives = b.prices.filter(q => q.selection.predicate !== "win" || ["no", "short"].includes(q.native_side.toLowerCase()));
    if (alternatives.length) {
      const { selection } = labelsFor(g.participants), d = el("details", undefined, "slate-alternatives");
      d.dataset.key = g.game_key + ":alternatives";
      d.append(el("summary", "Native alternatives · " + alternatives.length));
      for (const q of alternatives) {
        const item = el("div", undefined, "slate-alternative");
        item.append(el("span", selection(q) + " · " + venue(q.venue)));
        action(item, price(q) + " · Original", g.game_key + ":" + q.quote_id, button => onOriginal(q, button, g));
        freshness(item, q.freshness);
        d.append(item);
      }
      root.append(d);
    }
    content.append(root);
  }
  function financial(g, b, row, view, paused) {
    const root = el("article", undefined, "slate-result " + (view === "arbs" ? "slate-arb" : "slate-ev")), identity = el("div", undefined, "slate-result-identity"), { selection } = labelsFor(g.participants);
    root.dataset.key = g.game_key + ":" + (row.quote_id || row.pair_id);
    identity.append(el("h2", g.title), el("small", time(g.start_at)));
    if (view === "ev") identity.append(el("h3", selection(row)), el("p", venue(row.venue) + " · " + price(row)));
    else for (const [i, leg] of row.legs.entries()) {
      const line = el("p", undefined, "slate-leg");
      line.append(el("strong", selection(leg)), el("span", venue(leg.venue) + " " + price(leg) + " · " + money(row.funding?.legs?.[i]?.deployed_capital_usd)));
      identity.append(line);
    }
    root.append(identity);
    const m = row.financial_metrics || {}, values = el("div", undefined, "slate-result-values");
    if (view === "ev") {
      metric(values, "Complete EV after buffer", m.buffered_ev_usd);
      metric(values, "Return on deployed", m.buffered_return_percent, percent);
      if (m.buffered_ev_usd == null && m.conditional_buffered_ev_usd != null) values.append(el("small", "Conditional decisive EV " + money(m.conditional_buffered_ev_usd) + " · " + percent(m.conditional_buffered_return_percent), "conditional-label"));
      const fair = el("div", undefined, "slate-result-benchmark");
      benchmark(fair, b.benchmark, row.selection.participant);
      values.append(fair);
    } else {
      metric(values, "Minimum across modeled outcomes", m.buffered_complete_modeled_minimum_usd);
      metric(values, "Decisive margin after buffer", m.buffered_decisive_opposing_margin_usd);
      values.append(el("small", "Decisive return " + percent(m.buffered_decisive_return_percent) + " · all-outcome return " + percent(m.buffered_complete_minimum_return_percent)));
      if (row.classification?.positive_rule_sensitive_eligible) values.append(el("strong", "Rule-sensitive hedge", "conditional-label"));
      if (m.buffered_ev_usd == null) values.append(el("small", "Complete EV unknown" + (m.conditional_buffered_ev_usd != null ? " · conditional decisive EV " + money(m.conditional_buffered_ev_usd) : "")));
      const adverse = Object.entries(row.classification?.adverse_outcomes || {});
      if (adverse.length || row.classification?.unknown_outcomes?.length) {
        const { outcome } = labelsFor(g.participants);
        values.append(el("small", "Adverse outcomes before buffer: " + [...adverse.map(([name, value]) => outcome(name) + " " + money(value)), ...(row.classification.unknown_outcomes || []).map(name => outcome(name) + " Unknown")].join(" · "), "conditional-label"));
      }
    }
    root.append(values);
    const meta = el("div", undefined, "slate-result-meta");
    meta.append(el("small", "Deployed " + money(row.funding?.deployed_usd) + " · residual " + residual(row.funding?.residual_usd)));
    meta.append(el("small", "Result as-of " + time(b.result_as_of)));
    freshness(meta, row.freshness);
    if (b.delivery_state === "pending") meta.append(el("small", paused ? "Saved updates paused · prior saved result" : "Calculation pending · prior saved result", "pending-label"));
    if (b.delivery_state === "stopped") meta.append(el("small", "Collection stopped"));
    if (row.classification?.reason) meta.append(el("small", words(row.classification.reason)));
    root.append(meta);
    action(root, "Details", root.dataset.key, button => onDetails(row, button, g));
    content.append(root);
  }
  function draw(v, { view, filter, game = "", search = "", sort = "best", onShowAll }) {
    content.replaceChildren();
    content.classList.toggle("compact-odds", view === "odds");
    const visible = new Map(v.games.filter(g => (!game || g.game_key === game) && g.title.toLowerCase().includes(search.toLowerCase())).map(g => [g.game_key, g]));
    const boards = v.boards.filter(b => visible.has(b.game_key));
    const errors = (v.errors || []).filter(e => visible.has(e.game_key)), paused = v.storage?.state === "unavailable";
    const summary = el("div", undefined, "slate-summary");
    summary.append(el("strong", visible.size + " of " + v.games.length + " games"));
    if (view !== "odds") summary.append(el("span", boards.reduce((n, b) => n + b.rows.length, 0) + " comparisons · " + (filter === "all" ? "all saved results" : filter === "hedges" ? "positive rule-sensitive hedges" : "eligible positive results")));
    content.append(summary);
    const coverage = el("div", undefined, "slate-coverage");
    coverage.append(el("small", "Saved venue coverage across all games"));
    for (const book of ["novig", "prophetx", "kalshi", "polymarket_us", "pinnacle"]) {
      const count = v.boards.filter(b => b.prices.some(q => q.venue === book) || (b.benchmark.venue === book && b.benchmark.available)).length;
      coverage.append(el("span", venue(book) + " " + count + "/" + v.games.length));
    }
    content.append(coverage);
    if (!visible.size) {
      const empty = el("div", undefined, "empty");
      empty.append(el("h2", v.games.length ? "No games match this filter" : "No saved games yet"), el("p", v.games.length ? "Clear the team search or choose All games." : "Open Admin to check your source setup. Observed NFL winner games will appear here as prices are saved."));
      if (!v.games.length) { const a = el("a", "Check sources in Admin"); a.href = "/admin"; empty.append(a); }
      content.append(empty);
      return;
    }
    if (view === "odds") {
      const headings = el("div", undefined, "slate-price-headings slate-shared-headings");
      headings.append(el("span", "Game / team"), ...["novig", "prophetx", "kalshi", "polymarket_us"].map(book => el("span", venue(book))), el("span", venue(v.policy.benchmark_venue) + " fair"));
      content.append(headings);
      for (const g of visible.values()) {
        const b = boards.find(b => b.game_key === g.game_key);
        if (b) odds(g, b, paused);
        else { const root = el("article", undefined, "slate-game"), error = errors.find(e => e.game_key === g.game_key); root.append(el("h2", g.title), el("p", "Saved prices unavailable · " + words(error?.reason))); content.append(root); }
      }
      return;
    }
    const rows = boards.flatMap(b => b.rows.map(row => ({ g: visible.get(b.game_key), b, row })));
    const score = row => {
      const m = row.financial_metrics || {};
      return numeric(view === "ev" ? m.buffered_ev_usd ?? m.conditional_buffered_ev_usd : m.buffered_complete_modeled_minimum_usd ?? m.buffered_decisive_opposing_margin_usd);
    };
    rows.sort((a, b) => sort === "start" ? (a.g.start_at || "").localeCompare(b.g.start_at || "") || (score(b.row) ?? -Infinity) - (score(a.row) ?? -Infinity) : (score(b.row) ?? -Infinity) - (score(a.row) ?? -Infinity) || (a.g.start_at || "").localeCompare(b.g.start_at || ""));
    if (!rows.length) {
      const empty = el("div", undefined, "empty");
      empty.append(el("h2", filter === "all" ? "No saved calculations available" : filter === "hedges" ? "No positive rule-sensitive hedges" : view === "arbs" ? "No eligible positive arbs" : "No eligible positive EV"), el("p", filter === "all" ? "Prices remain available in Odds. Check source status or wait for a pending calculation." : "This applies across all visible games and your settings. Losing, conditional and historical results remain available under All comparisons."));
      if (filter !== "all") { const b = el("button", "Show all comparisons"); b.onclick = onShowAll; empty.append(b); }
      content.append(empty);
    }
    for (const entry of rows) financial(entry.g, entry.b, entry.row, view, paused);
    const unavailable = boards.filter(b => !b.rows.length && (b.delivery_state === "pending" || filter === "all"));
    if (unavailable.length || errors.length) {
      const note = el("details", undefined, "slate-pending");
      note.dataset.key = "pending-games";
      note.append(el("summary", unavailable.length + errors.length + " games with no saved calculations"));
      for (const b of unavailable) note.append(el("p", visible.get(b.game_key).title + " · " + (paused ? "Saved updates paused" : b.delivery_state === "pending" ? "Calculation pending" : b.empty_reason || "No eligible comparisons") + " · " + b.prices.length + " original prices in Odds"));
      for (const e of errors) note.append(el("p", visible.get(e.game_key).title + " · Saved view unavailable · " + words(e.reason)));
      content.append(note);
    }
  }
  return { draw };
}
