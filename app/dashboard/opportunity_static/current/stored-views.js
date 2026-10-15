import { createComparisonSlate } from "./comparison-slate-views.js";
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
            q.selection.predicate === "win",
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
        q.selection.predicate !== "win",
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
    for (const row of v.rows.filter(row => row.legs?.length === 2 && row.legs[0].venue !== row.legs[1].venue)) {
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

// Ordinary all-games presenter; legacy per-board readers remain compatible.
export function createSlateViews(options) {
  return createComparisonSlate(options);
}
