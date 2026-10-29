import { primaryComparisonMetric } from "./comparison-slate-views.js";
import { financialGap } from "./opportunity-dashboard.js";
import { money, quantity, numeric, percent } from "./board-client.js";
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
  labelsFor,
  price,
  observationStatus,
  depthSummary,
  ageNode,
  comparisonStatusLabel,
  comparisonTakeaway,
  estimateSummary,
  clockedText,
  marketCaption,
  typedGameTitle,
} from "./board-elements.js";

export function renderOriginalDetails(q, inputs, { root, participants, title }) {
  root.replaceChildren(el("h3", typedGameTitle(participants, "Selected game") + " · " + marketCaption(q)));
  root.append(el("p", [q.event?.league || q.event?.sport, q.event?.start_at ? "Scheduled " + time(q.event.start_at) : "Scheduled start unknown"].filter(Boolean).join(" · ")));
  const captured = q.current_comparison?.available ? q.current_comparison : q.gross_comparison;
  const frames = el("div", undefined, "comparison-inputs price-lead");
  // Use only the already captured pair, never a supplementary response's peers.
  const peers = captured?.available ? (captured.inputs || []).filter(i => i.quote_id !== q.quote_id) : [];
  for (const [index, input] of [q, ...peers].entries()) {
    const card = el("section", undefined, "comparison-input");
    card.append(el("h4", (index ? "Captured peer · " : "Original price · ") + venue(input.venue)),
      el("strong", String(input.original?.value ?? "Unknown") + " " + words(input.original?.units), "original-price-value"),
      el("p", labelsFor(participants).selection(input)),
      clockedText("small", now => observationStatus(input, now)));
    const age = el("p"); age.append(ageNode(input.times?.source_at || input.freshness?.source_at, "Source: ")); card.append(age);
    if (input.original?.native_value != null) textLine(card, "Source input", String(input.original.native_value) + " " + words(input.original.native_units));
    frames.append(card);
  }
  root.append(frames, clockedText("p", now => comparisonTakeaway(captured, now), "comparison-takeaway"));
  if (captured?.available) root.append(el("p", "Difference is peer minus selected, before costs. It does not establish net EV or covered arbitrage."));
  root.append(el("small", "Captured prices stay fixed. Close and reopen for updated inputs."));
  const evidence = el("details"); evidence.dataset.key = "captured-price-evidence";
  evidence.append(el("summary", "Source details & observed depth"));
  evidence.append(el("p", "A passed scheduled start does not establish completion or settlement."));
  const body = el("div"); renderOriginalEvidence(q, inputs, {root:body, participants, title});
  evidence.append(body); root.append(evidence);
}

function renderOriginalEvidence(q, inputs, { root, participants, title }) {
  root.replaceChildren(el("h3", labelsFor(participants).selection(q)), el("p", (title ? title + " · " : "") + venue(q.venue) + " · " + price(q)));
  root.append(clockedText("p", now => comparisonTakeaway(q.current_comparison?.available ? q.current_comparison : q.gross_comparison, now), "comparison-takeaway"));
  const captured = q.current_comparison?.available ? q.current_comparison : q.gross_comparison;
  root.append(el("small", "Captured comparison status" + (captured?.read_at ? " assessed " + time(captured.read_at) : "") + ". This opened frame keeps its original inputs and source-health assessment; ages continue to advance. Close and reopen for a new frame.", "muted"));
  textLine(root, "Game / league / start", [q.event?.title || title, q.event?.league || q.event?.sport, q.event?.start_at ? time(q.event.start_at) : null].filter(Boolean).join(" · "));
  textLine(root, "Market", marketCaption(q));
  if (q.native_contract_summary?.wording) {
    const wording = el("details"); wording.dataset.key = "captured-native-wording";
    wording.append(el("summary", "Captured native contract wording"));
    for (const [label,text] of Object.entries(q.native_contract_summary.wording)) textLine(wording, words(label), typeof text === "string" ? text : JSON.stringify(text));
    root.append(wording);
  }
  textLine(root, "Native-side price", String(q.original.value) + " " + words(q.original.units) + " · " + side(q.native_side));
  if (q.original.native_value != null) textLine(root, "Original source input", String(q.original.native_value) + " " + words(q.original.native_units) + (q.original.transformation ? " · " + words(q.original.transformation) : ""));
  root.append(clockedText("p", now => "Observation: " + observationStatus(q, now)));
  if (q.observation_display?.read_at) textLine(root, "Source health assessed", time(q.observation_display.read_at));
  if (q.source_health?.reason) textLine(root, "Source status reason", q.source_health.reason);
  if (q.observation_display?.publication_reason_codes?.length) textLine(root, "Publication status", "Updating stored observations; source clock is shown separately.");
  const statusCodes = q.observation_display?.reason_codes || q.freshness?.reasons || [];
  if (statusCodes.length) {
    const reasons = el("details"); reasons.dataset.key = "price-status-reasons";
    reasons.append(el("summary", "Price status reasons"));
    for (const code of statusCodes) reasons.append(el("p", words(code) + " · " + code));
    root.append(reasons);
  }
  textLine(root, "Original source clock", String(q.times?.source_at || q.freshness?.source_at || "Unknown"));
  const age = el("p"); age.append(ageNode(q.times?.source_at || q.freshness?.source_at, "Original source age: ")); root.append(age);
  textLine(root, "Original receipt clock", String(q.times?.received_at || q.freshness?.received_at || "Unknown"));
  textLine(root, "Source clock meaning", words(q.times?.source_time_kind));
  if (q.provider_clocks) {
    textLine(root, "Provider book / market clocks", String(q.provider_clocks.book || "Unknown") + " / " + String(q.provider_clocks.market || "Unknown"));
    textLine(root, "Provider selected clock basis", words(q.provider_clocks.selected_basis));
  }
  if (q.book_confirmation) {
    textLine(root, "Book confirmation / receipt", String(q.book_confirmation.confirmed_at || "Unknown") + " / " + String(q.book_confirmation.received_at || "Unknown"));
    root.append(el("small", "Book confirmation is separate evidence; the original price source clock remains unchanged."));
  }
  const depth = q.observed_depth || inputs.evidence?.observed_depth;
  const book = el("section", undefined, "observed-depth");
  book.append(el("h3", "Observed book depth"), el("p", depthSummary(q)));
  textLine(book, "Book source / receipt", String(depth?.source_at || "Unknown") + " / " + String(depth?.received_at || "Unknown"));
  if (depth?.clock_basis) textLine(book, "Book clock basis", words(depth.clock_basis));
  if (depth?.book_revision != null) textLine(book, "Stored book revision", String(depth.book_revision));
  if (depth?.available && depth.levels?.length) {
    const table = el("table"), header = el("tr");
    header.append(el("th", "Price · " + words(depth.price_units)), el("th", "Quantity · " + words(depth.quantity_units)));
    table.append(header);
    for (const level of depth.levels) {
      const row = el("tr"); row.append(el("td", String(level.price)), el("td", String(level.quantity))); table.append(row);
    }
    book.append(table, el("small", depth.levels.length + " of " + depth.total_levels + " retained levels shown" + (depth.truncated ? " · bounded preview" : "") + ". Observed size does not establish fills or maximum capacity."));
  }
  for (const [kind, comparison] of [["current", q.current_comparison], ["lowest", q.gross_comparison]]) {
    if (!comparison) continue;
    const panel = el("section", undefined, "original-comparison");
    panel.append(el("h3", kind === "current" ? "Current-peer price comparison" : "Lowest observed price comparison"));
    if (comparison.available) {
      const amount = (numeric(comparison.value) > 0 ? "+" : "") + quantity(comparison.value) + " " + words(comparison.unit);
      panel.append(clockedText("p", now => "Difference: " + amount + " · " + comparisonStatusLabel(comparison, now)));
      if (comparison.exact) textLine(panel, "Exact difference", comparison.exact.numerator + "/" + comparison.exact.denominator + " cents");
    } else textLine(panel, "Difference", "Unavailable · " + words(comparison.reason));
    if (comparison.missing_fields?.length) textLine(panel, "Missing matching fields", comparison.missing_fields.join(", "));
    if (comparison.available) {
      panel.append(el("p", (kind === "current" ? "Lowest compatible current other-venue price" : "Lowest compatible other-venue price, including historical quotes") + " − selected price, in cents. Native prices are converted to their normal-payout dollar prices before subtraction. Positive means the selected price is lower; negative means it is higher; zero means equal prices."));
      const frames = el("div", undefined, "comparison-inputs");
      for (const [index, input] of (comparison.inputs || []).entries()) {
        const card = el("section", undefined, "comparison-input");
        card.append(el("h4", (index === 0 ? "Selected · " : "Comparator · ") + venue(input.venue)));
        textLine(card, "Outcome", labelsFor(participants).selection(input));
        textLine(card, "Market / period", marketCaption(input));
        const contract = input.native_contract_summary || input.native_contract;
        if (contract?.wording) for (const [label, text] of Object.entries(contract.wording)) textLine(card, "Native " + words(label), typeof text === "string" ? text : JSON.stringify(text));
        const facts = contract?.same_outcome;
        if (facts?.predicate) textLine(card, "Exact scoring condition", [facts.predicate.domain, facts.predicate.operator, facts.predicate.threshold].map(words).join(" · "));
        if (facts?.equality) textLine(card, "Equality treatment", words(facts.equality.treatment) + " · fee refund: " + words(facts.equality.refund_fees));
        if (facts?.scoring) textLine(card, "Scoring scope", Object.entries(facts.scoring).map(([k,v]) => words(k) + ": " + words(v)).join(" · "));
        if (input.same_outcome) textLine(card, "Same-outcome identity", input.same_outcome.supported ? "Supported exact predicate and scoring scope" : words(input.same_outcome.reason));
        textLine(card, "Native side", side(input.native_side) || "Unknown");
        if (input.source) {
          textLine(card, "Native market / outcome", input.source.native_market_id + " / " + input.source.native_outcome_id);
          textLine(card, "Native event", input.source.native_event_id);
        }
        textLine(card, "Original price", String(input.original?.value ?? "Unknown") + " " + words(input.original?.units));
        if (input.original?.native_value != null) textLine(card, "Original source input", String(input.original.native_value) + " " + words(input.original.native_units));
        card.append(clockedText("p", now => "Observation: " + observationStatus(input, now)));
        if (input.source_health?.reason) textLine(card, "Source status reason", input.source_health.reason);
        textLine(card, "Original source time", input.times?.source_at || "Unknown");
        const sourceAge = el("p"); sourceAge.append(ageNode(input.times?.source_at, "Source age: ")); card.append(sourceAge);
        textLine(card, "Original receipt time", input.times?.received_at || "Unknown");
        const receiptAge = el("p"); receiptAge.append(ageNode(input.times?.received_at, "Receipt age: ")); card.append(receiptAge);
        textLine(card, "Source clock meaning", words(input.times?.source_time_kind));
        if (input.observation_display?.publication_reason_codes?.length) card.append(el("p", "Updating stored observations; the original source clock has not changed."));
        frames.append(card);
      }
      panel.append(frames);
      textLine(panel, "Source-time separation", comparison.source_time_skew_seconds == null ? "Unknown" : quantity(String(comparison.source_time_skew_seconds)) + " seconds between original source times");
      if (comparison.read_at) textLine(panel, "Comparison status assessed", time(comparison.read_at));
      if (comparison.reason_codes?.length) {
        const reasons = el("details"); reasons.dataset.key = kind + "-comparison-reasons";
        reasons.append(el("summary", "Comparison status reasons"));
        for (const code of comparison.reason_codes) reasons.append(el("p", words(code) + " · " + code));
        panel.append(reasons);
      }
    }
    panel.append(el("small", "Gross price difference excludes costs, modeled net returns and EV."));
    root.append(panel);
  }
  root.append(book);
  const estimate = q.estimate_availability || inputs.estimate_availability || inputs.evidence?.estimate_availability;
  estimateSummary(root, estimate, "original-estimate-reasons");
  const identity = el("details", undefined, "observation-identity"); identity.dataset.key = "observation-identity";
  identity.append(el("summary", "Exact observation identity & comparison inputs"));
  for (const [label, value] of [["Local quote", q.quote_id], ["Quote revision", q.quote_revision], ["Observation revision", q.observation_revision], ["Native event", q.source?.native_event_id], ["Native market", q.source?.native_market_id], ["Native outcome", q.source?.native_outcome_id], ["Market / period", (q.market?.market || "Unknown") + " / " + (q.market?.period || "Unknown")], ["Period meaning", q.market?.period_boundary || q.selection?.period_boundary], ["Signed source line", q.selection?.signed_line ?? q.market?.line], ["Matching limitation", q.same_outcome?.supported ? "Supported" : q.same_outcome?.reason], ["Occurrence match", q.occurrence_match?.status], ["Current frame", q.inputs_identity?.context_id]]) textLine(identity, label, String(value ?? "Unknown"));
  for (const comparison of [q.current_comparison, q.gross_comparison]) if (comparison?.inputs) identity.append(el("pre", JSON.stringify(comparison.inputs, null, 2)));
  root.append(identity);
  const evidence = el("details"); evidence.dataset.key = "source-evidence";
  evidence.append(el("summary", "Original contract and source evidence"), el("pre", JSON.stringify(inputs.evidence, null, 2)));
  root.append(evidence);
}

export function renderSavedDetails(v, { root, participants }) {
  const { participant, outcome } = labelsFor(participants);
  const selected = v.pair || v.quote.calculations.funded_estimate,
    m = selected.financial_metrics || {},
    f = selected.funding || {},
    quotes = v.pair ? v.leg_quotes : [v.quote];
  root.replaceChildren();
  root.append(
    el(
      "h3",
      quotes
        .map(
          (q) => labelsFor(participants).selection({selection:q.binding.selection,native_side:q.source.native_side}) + " · " + venue(q.venue),
        )
        .join(" + "),
    ),
  );
  for (const q of quotes)
    textLine(
      root,
      venue(q.venue) + " original price",
      String(q.original.value) +
        " " +
        words(q.original.units) +
        " · " +
        side(q.source.native_side),
    );
  root.append(clockedText("p", now => quotes.map(q => observationStatus(q, now)).join(" · ")));
  for (const q of quotes) root.append(el("p", venue(q.venue) + " source " + time(q.times.source_at) + " · Received " + time(q.times.received_at)));
  const primary = primaryComparisonMetric(selected, v.pair ? "arbs" : "ev");
  if (primary) {
    const headline = el("div", undefined, "metrics selected-primary");
    metric(headline, (primary.state === "numeric_last_known" ? "Last-known · " : "") + primary.label, primary.value, x => (numeric(x) > 0 ? "+" : "") + percent(x));
    root.append(headline);
  }
  const gross = selected.gross_decisive_benchmark;
  if (gross?.available === false && gross.reason) textLine(root,"Gross comparison unavailable",financialGap(gross.reason));
  if (gross?.available && numeric(gross.return_percent) !== null) {
    const companion = el("section", undefined, "gross-benchmark-companion");
    companion.append(el("h3", "Gross decisive benchmark"));
    metric(companion, (gross.state === "numeric_last_known" ? "Last-known · " : "") + "Return on normal acquisition", gross.return_percent, x => (numeric(x) > 0 ? "+" : "") + percent(x));
    companion.append(el("p", "Per $1 normal claim, before fees and exceptional settlement. No executable quantity, complete net EV or covered arbitrage is established."));
    companion.append(el("p", "Exact outcome and line, conditional on a decisive result. Ties, pushes and exceptional settlement are excluded."));
    const predicate = gross.selected_predicate;
    const operators = {gt:">",ge:"≥",lt:"<",le:"≤"};
    const domain = value => ({home_margin:"Home score margin",combined_score:"Combined score"}[value] || words(value));
    if (predicate) {
      textLine(companion, "Selected native condition", domain(predicate.domain) + " " + operators[predicate.operator] + " " + predicate.threshold);
      textLine(companion, "Reference conditioning", "Score unequal to " + predicate.threshold + "; equality and exceptional settlement excluded");
      if (gross.selected_equality) textLine(companion, "Native equality treatment", words(gross.selected_equality.treatment || "See original contract"));
    }
    if (gross.currentness_reasons?.length) textLine(companion, "Last-known reasons", gross.currentness_reasons.map(words).join(", "));
    for (const ref of gross.reference_originals || []) {
      const s = ref.selection || {}, line = s.signed_line;
      const name = s.label || s.native?.original_wording || participant(s.participant || s.participant_id) || "Reference outcome";
      const label = name + (line == null ? "" : " " + (numeric(line) > 0 ? "+" : "") + line) + " · " + words(s.family || ref.market_identity?.family) + " · " + words(s.scope?.period || ref.market_identity?.period);
      if (typeof s.predicate === "string") textLine(companion, "Reference condition", words(s.predicate));
      else if (s.predicate?.domain && operators[s.predicate.operator] && s.predicate.threshold != null)
        textLine(companion, "Reference condition", domain(s.predicate.domain) + " " + operators[s.predicate.operator] + " " + s.predicate.threshold);
      textLine(companion, "Pinnacle · " + label, String(ref.decimal_odds) + " decimal odds");
      companion.append(el("small", "Source " + time(ref.source_at || ref.market_at || ref.book_at) + " · Received " + time(ref.received_at)));
    }
    textLine(companion, "Selected decisive probability", String(gross.selected_decisive_probability) + " (" + percent(numeric(gross.selected_decisive_probability) * 100) + ")");
    textLine(companion, "Cost per $1 normal claim", String(gross.acquisition_usd_per_normal_claim) + " USD");
    companion.append(el("p", "Gross return = 100 × (decisive probability ÷ claim cost − 1). Pinnacle weights use proportional no-vig normalization."));
    root.append(companion);
  }
  const conditional = selected.conditional_trade_benchmark;
  if (conditional?.available === false && conditional.reason) textLine(root,"Fee scenario unavailable",financialGap(conditional.reason));
  if (conditional?.available) {
    const section = el("section", undefined, "conditional-trade-benchmark");
    section.append(el("h3", "Conditional trade-fee benchmark"));
    metric(section, (conditional.state === "numeric_last_known" ? "Last-known · " : "") + "Conditional return", conditional.return_percent, percent);
    textLine(section, "Scenario", conditional.normalization_label || "per $1 modeled risk");
    textLine(section, "Modeled risk including trade fee", String(conditional.normalization_risk_usd) + " USD");
    textLine(section, "Trade fee in modeled scenario", money(conditional.trade_fee_usd));
    section.append(el("p", conditional.condition));
    section.append(el("p", conditional.formula));
    section.append(el("p", "Excluded: " + conditional.exclusions.join(", ") + "."));
    section.append(el("p", conditional.meaning));
    section.append(el("small", "Fee evidence reviewed " + time(conditional.evidence.reviewed_at) + "; withdraw at " + time(conditional.evidence.review_before) + "."));
    root.append(section);
  }
  if (selected.modeled_basis) {
    const basis = selected.modeled_basis;
    const disclosure = el("details", undefined, "modeled-product-basis");
    disclosure.append(el("summary", "Model, scenarios & sensitivity"));
    for (const key of ["product", "quantity", "charges", "probability", "exceptional_model", "rules", "historical_context", "sensitivity_scope", "review_horizon", "missing"])
      disclosure.append(el("p", basis[key]));
    if (selected.modeled_expected_void_receipt_usd != null) disclosure.append(el("p", "Assumed expected void receipt at this amount: " + money(selected.modeled_expected_void_receipt_usd) + ". Actual void receipt and guaranteed minimum remain unknown."));
    const sensitivity = basis.sensitivity;
    if (sensitivity) {
      disclosure.append(el("h4", "Full EV sensitivity · hypothetical parameters"));
      disclosure.append(el("p", "After one buffer: " + money(sensitivity.buffered_ev_low_usd) + " to " + money(sensitivity.buffered_ev_high_usd) + ". " + (sensitivity.sign_changes ? "Assumptions reverse the sign." : "No sign reversal within this hypothetical range.") + " This is not a confidence interval or guaranteed minimum."));
      disclosure.append(el("p", sensitivity.threshold_condition));
      disclosure.append(el("p", "Break-even expected void receipt per $1 face: " + money(sensitivity.break_even_expected_void_receipt_per_face) + (sensitivity.break_even_receipt_feasible ? ". Higher expected receipt gives positive buffered EV." : " (outside the feasible $0-$1 interval).")));
      if (sensitivity.break_even_void_probability_zero_receipt != null) disclosure.append(el("p", "Break-even void rate with zero void receipt: " + percent(100 * numeric(sensitivity.break_even_void_probability_zero_receipt)) + (sensitivity.break_even_void_feasible ? "." : " (outside the feasible probability interval).")));
      disclosure.append(el("p", sensitivity.formula));
    }
    root.append(disclosure);
  }
  const metrics = el("div", undefined, "metrics");
  metric(
    metrics,
    v.pair ? "Buffered decisive margin" : selected.modeled_basis?.scenario_parameters?.refund_given_void === "1" ? "Hypothetical refund scenario · buffered" : m.buffered_ev_usd == null ? "Conditional EV · buffered" : "Complete buffered EV",
    v.pair ? m.buffered_decisive_opposing_margin_usd : m.buffered_ev_usd ?? m.conditional_buffered_ev_usd,
  );
  if (v.pair) {
    metric(metrics,"Minimum across modeled outcomes · buffered",m.buffered_complete_modeled_minimum_usd);
    if (m.buffered_complete_modeled_minimum_usd == null) metrics.append(el("small","Complete modeled minimum unknown; the decisive margin does not cover every outcome.","conditional-label"));
  }
  root.append(metrics);
  if (selected.modeled_basis) {
    metric(metrics, "Conditional net EV · decisive outcomes · buffered", m.conditional_buffered_ev_usd);
    root.append(el("p", "Conditional EV assumes a decisive winner. The full-EV scenario uses hypothetical tie and void assumptions; neither is a guaranteed return."));
  }
  if (!v.pair && m.buffered_ev_usd == null) metrics.append(el("small", "Complete modeled EV unavailable", "conditional-label"));
  const main = root;
  const sizing = el("details"); sizing.dataset.key = "selected-sizing-evidence";
  sizing.append(el("summary", "Selected amount, fees, buffer & reconciliation"));
  main.append(sizing); root = sizing;
  const age = el("div");
  age.id = "detail-freshness";
  freshness(age, selected.freshness);
  root.append(age);
  root.append(el("small", "Inputs captured " + time(v.as_of)));
  const frame = selected.evaluation_frame;
  if (frame) root.append(el("small", "Evaluated " + time(frame.evaluated_at) + (frame.mixed_source_times ? " · Last-known prices from different times; no simultaneous historical trade is established." : " · Original price clocks retained.")));
  const funding = el("div", undefined, "detail-funding");
  for (const [label, value] of [["Requested funding",money(f.requested_usd)],["Deployed",money(f.deployed_usd)],["Residual",residual(f.residual_usd)]]) {
    const item=el("div");item.append(el("small",label),el("strong",value));funding.append(item);
  }
  root.append(funding);
  for (const [i, leg] of (f.legs || []).entries())
    textLine(
      root,
      "Leg " + (i + 1) + " quantity",
      quantity(leg.native_quantity) +
        " " +
        unit(leg.native_unit?.unit) +
        " · acquisition " +
        money(leg.acquisition_usd) +
        " · upfront fees " +
        money(leg.upfront_fee_usd ?? leg.net_upfront_fee_usd),
    );
  root.append(
    el(
      "h3",
      m.net_modeled_ev_usd == null
        ? "Conditional reconciliation · complete EV unknown"
        : "Estimated value reconciliation",
    ),
  );
  const dl = el("dl", undefined, "detail-reconciliation");
  for (const [name, value] of [
    ["Gross benchmark estimate at requested size", m.gross_benchmark_ev_usd],
    ["Rule effects", m.rule_adjustment_usd],
    ["Upfront fees", m.net_upfront_fee_usd],
    ["Expected settlement fees", m.reconciliation_expected_settlement_fee_usd],
    [
      "Net estimate before buffer",
      m.net_modeled_ev_usd ?? m.conditional_net_ev_usd,
    ],
    ["One buffer on deployed amount", m.buffer_usd],
    [
      "Estimate after buffer",
      m.buffered_ev_usd ?? m.conditional_buffered_ev_usd,
    ],
  ])
    dl.append(el("dt", name), el("dd", money(value)));
  root.append(dl);
  root.append(
    el(
      "small",
      "Basis: " +
        words(m.reconciliation_condition) +
        ". Settlement fees are expected charges, not maximum charges.",
    ),
  );
  textLine(
    root,
    "Funding support",
    words(f.size_status) +
      " · " +
      (f.residual_reason || "Unknown residual reason"),
  );
  root = main;
  const outcomes=el("details",undefined,"detail-outcomes");
  outcomes.dataset.key="outcomes";
  outcomes.append(el("summary", "Modeled outcomes"));
  const t = el("table"),
    head = el("tr");
  ["Outcome", "Net before buffer", "After buffer"].forEach((x) =>
    head.append(el("th", x)),
  );
  t.append(head);
  for (const [name, state] of Object.entries(selected.states || {})) {
    const tr = el("tr");
    tr.append(
      el("td", outcome(name)),
      el("td", money(state.profit_usd)),
      el(
        "td",
        state.buffered_profit_usd == null
          ? "See one buffer above"
          : money(state.buffered_profit_usd),
      ),
    );
    t.append(tr);
  }
  outcomes.append(t);root.append(outcomes);
  if (selected.assumptions?.length) {
    const assumptions = el("details");
    assumptions.dataset.key = "assumptions";
    assumptions.append(el("summary", "Model assumptions"));
    for (const assumption of selected.assumptions)
      assumptions.append(
        el(
          "p",
          typeof assumption === "string"
            ? assumption
            : JSON.stringify(assumption),
          "muted",
        ),
      );
    root.append(assumptions);
  }
  const advanced = el("details");
  advanced.dataset.key = "originals";
  advanced.append(
    el("summary", "Original contracts, profiles and current calculation evidence"),
    el("pre", JSON.stringify(v, null, 2)),
  );
  root.append(advanced);
  return { advanced };
}
