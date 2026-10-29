import { numeric, percent } from "./board-client.js";
import { el, venue, words, price, labelsFor, matchesGameSearch, matchesMarketFilter, typedGameTitle, marketCaption } from "./board-elements.js";

export function financialGap(reason) {
  return ({
    exact_pinnacle_opposition_unavailable: "No complete Pinnacle pair for this exact event, outcome and line in the retained inputs.",
    exact_native_reference_pair_absent: "No complete Pinnacle pair for this native outcome and exact line in the matched event.",
    reference_scoring_scope_conflict: "Native and reference scoring rules are not yet verified to agree, including overtime or shootout treatment.",
    gross_exact_native_score_identity_unsupported: "The native score condition or scoring rules are not sufficiently supported for this comparison.",
    gross_decisive_winner_identity_unsupported: "The full-game winner identity or overtime rules remain unsupported.",
    explicit_two_way_benchmark_required: "A complete, occurrence-matched two-way reference is missing.",
    estimate_source_clock_unknown: "The source has not supplied a usable price timestamp.",
    conditional_fee_review_expired_or_not_effective: "The captured fee review is outside its applicability interval. Earlier values remain last-known.",
    prophetx_account_fee_model_and_rate_unbound: "ProphetX sets the fee model and rate per account; its public API cannot supply that rate. Gross comparison remains available.",
    kalshi_instrument_fee_schedule_unbound: "The effective Kalshi fee schedule and multiplier are not bound to this instrument. Gross comparison remains available.",
  })[reason] || words(reason);
}

// Compare supplied exact values before formatting. This is ordering, not finance.
export function compareExactPercent(a, b) {
  function rational(value) {
    const s = String(value), fraction = /^(-?\d+)\/(\d+)$/.exec(s);
    if (fraction && BigInt(fraction[2])) return [BigInt(fraction[1]), BigInt(fraction[2])];
    const decimal = /^([+-]?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/.exec(s);
    if (!decimal || Math.abs(Number(decimal[4] || 0)) > 1000) return null;
    const scale=(decimal[3] || "").length-Number(decimal[4] || 0), numerator=BigInt((decimal[1] || "")+decimal[2]+(decimal[3] || ""));
    return scale >= 0 ? [numerator,10n ** BigInt(scale)] : [numerator*10n ** BigInt(-scale),1n];
  }
  const x = rational(a), y = rational(b);
  if (!x || !y) return Number(!x) - Number(!y);
  const delta = y[0] * x[1] - x[0] * y[1];
  return delta > 0n ? 1 : delta < 0n ? -1 : 0;
}
const dashboardMetrics = {
  ev: ["buffered_ev_usd", "buffered_return_percent", "Net expected return"],
  arbs: ["buffered_complete_modeled_minimum_usd", "buffered_complete_minimum_return_percent", "Covered modeled minimum"],
  conditional: ["conditional_buffered_ev_usd", "conditional_buffered_return_percent", "Conditional net EV · decisive outcomes"],
  decisive: ["buffered_decisive_opposing_margin_usd", "buffered_decisive_return_percent", "Decisive hedge margin"],
  known: ["buffered_conditional_known_state_minimum_usd", "buffered_conditional_known_state_minimum_return_percent", "Listed known outcomes margin"],
};
export function dashboardMetric(row, kind) {
  if (kind === "trade") {
    const m = row.conditional_trade_benchmark;
    return m?.available && numeric(m.return_percent) !== null ? {value:m.return_percent,state:m.state,label:"Conditional trade-fee benchmark · " + (m.normalization_label || "per $1 modeled risk")} : null;
  }
  if (kind === "gross") {
    const g = row.gross_decisive_benchmark;
    return g?.available && numeric(g.return_percent) !== null ? {value:g.return_percent, state:g.state, label:"Gross decisive benchmark"} : null;
  }
  const [field, percentage, label] = dashboardMetrics[kind], state = row.availability?.metrics?.[field]?.state;
  return row.availability?.numeric_metrics?.includes(field) && ["numeric_current", "numeric_last_known"].includes(state) && numeric(row.financial_metrics?.[percentage]) !== null
    ? {value:row.financial_metrics[percentage], state, label: kind === "ev" && row.modeled_basis ? (row.modeled_basis.scenario_parameters?.refund_given_void === "1" ? "Hypothetical refund scenario · uncalibrated" : "Modeled return · uncalibrated assumptions") : label} : null;
}
function dashboardTie(a, b) {
  return (a.g.start_at || "").localeCompare(b.g.start_at || "") || a.g.game_key.localeCompare(b.g.game_key) || String(a.row.quote_id || a.row.pair_id).localeCompare(String(b.row.quote_id || b.row.pair_id));
}
export function dashboardScope(slate, kind, filters = {}) {
  const {game="", search="", league="", family="", period="", source=""} = filters;
  const games = new Map((slate?.games || []).filter(g => (!game || game === g.game_key) && (!league || (g.league || g.scope?.split("/")[0]) === league) && matchesGameSearch(g, search)).map(g => [g.game_key,g]));
  const match = row => row.legs ? (!source || row.legs.some(l => l.venue === source)) && row.legs.every(l => matchesMarketFilter(l,family,period)) : (!source || row.venue === source) && matchesMarketFilter(row,family,period);
  const boards = (slate?.boards || []).filter(b => games.has(b.game_key));
  const rows = boards.flatMap(b => b.rows.filter(match).filter(r => kind !== "arbs" || r.legs?.length === 2 && r.legs[0].venue !== r.legs[1].venue).map(row => ({row,g:games.get(b.game_key),b})));
  const errors = (slate?.errors || []).filter(e => games.has(e.game_key));
  const positive = rows.filter(e => {
    const m = dashboardMetric(e.row,kind);
    return m?.state === "numeric_current" && compareExactPercent(m.value,"0") < 0 && e.row.freshness?.status === "current" && e.row.classification?.main_positive_eligible && e.row.availability?.current_opportunity_eligible && !slate.stopped && !slate.dashboard_error;
  });
  const sort = entries => entries.sort((a,b) => compareExactPercent(dashboardMetric(a.row,kind)?.value,dashboardMetric(b.row,kind)?.value) || dashboardTie(a,b));
  sort(positive);
  const relevant = boards.filter(b => b.prices.some(match) || b.rows.some(match));
  const field = dashboardMetrics[kind][0];
  const reasons = [...new Set(rows.flatMap(e => e.row.availability?.metrics?.[field]?.reason_codes || e.row.availability?.reason_codes || []).concat(relevant.flatMap(b => (b.availability?.causes || []).map(c => c.code))))];
  const pending = relevant.some(b => b.delivery_state === "pending" || b.availability?.outcome === "not_evaluated") || rows.some(e => e.row.availability?.metrics?.[field]?.state === "not_evaluated");
  const unknown = rows.some(e => !dashboardMetric(e.row,kind));
  const current = rows.filter(e => dashboardMetric(e.row,kind)?.state === "numeric_current");
  const lastKnown = rows.some(e => dashboardMetric(e.row,kind)?.state === "numeric_last_known");
  // Board completeness includes refused candidates not materialized as rows.
  const complete = rows.length > 0 && relevant.length > 0 && relevant.every(b => b.availability?.evaluation_complete === true) && !pending && !errors.length && !unknown && !lastKnown && !slate.stopped && !slate.dashboard_error;
  const failed = !!slate?.dashboard_error || errors.length > 0 || rows.some(e => e.row.availability?.metrics?.[field]?.state === "calculation_failed") || reasons.some(r => /calculation.*failed/.test(r));
  const state = !slate ? "loading" : slate?.dashboard_error ? "failed" : !errors.length && (!games.size || (family || period || source) && boards.length && !relevant.length && !boards.some(b => b.delivery_state === "pending")) ? "no_matches" : positive.length ? complete ? "positive" : "partial" : complete ? "evaluated_no_positive" : current.length ? "partial" : lastKnown ? "last_known" : failed && (!relevant.length || rows.length > 0 && rows.every(e => e.row.availability?.metrics?.[field]?.state === "calculation_failed")) ? "failed" : !rows.length && !reasons.length || pending && !reasons.length ? "pending" : "unavailable";
  return {rows,positive,state: errors.length && boards.length && !slate?.dashboard_error ? "partial" : state,reasons,pending,failed,complete,errors,games};
}
export function dashboardMessage(scope, kind) {
  if (scope.state === "loading") return "Loading saved results. Prices remain available while this list loads.";
  if (scope.state === "no_matches") return "No retained games or markets match these filters. Clear or change the filters to browse available results.";
  if (scope.state === "positive") return "Current positive results, highest return first.";
  if (scope.state === "evaluated_no_positive") return "No positive results in the evaluated scope. Zero and negative comparisons are below.";
  if (scope.state === "partial") return "Partially evaluated. Available results are shown; other results remain unknown.";
  if (scope.state === "last_known") return "Last-known estimates only. Older inputs are shown separately for research.";
  if (scope.state === "failed") return "Results could not be fully evaluated. Browse prices or retry the read.";
  if (scope.state === "pending") return "Calculations pending. You can browse prices while they update.";
  return kind === "ev" ? "Net EV unavailable. Required cost, sizing, settlement or probability inputs are missing, unsupported or expired." : "Covered arbitrage unavailable. Required cost, sizing or settlement inputs are missing, unsupported or expired.";
}
function dashboardReasons(codes) {
  const labels = new Set();
  for (const code of codes) {
    if (/fee|cost|charge/.test(code)) labels.add("Applicable fees and charges");
    if (/quant|size|grid|depth|execution/.test(code)) labels.add("Executable quantities and sizing");
    if (/payout|settle|rule|cashflow/.test(code)) labels.add("Complete settlement terms");
    if (/probab|model|distribution/.test(code)) labels.add("Applicable probability and financial models");
    if (/reference|source.*expir|fresh/.test(code)) labels.add("Current source and reference inputs");
  }
  return [...labels];
}
export function drawOpportunityDashboard(content, slates, filters, onDetails, kinds = ["arbs", "ev"]) {
  content.replaceChildren();
  content.classList.add("opportunity-dashboard");
  const grid = el("div",undefined,"opportunity-sections");
  const scopes = {};
  function renderRow(root, e, kind) {
    const {row,g} = e, m = dashboardMetric(row,kind), item = el("article",undefined,"opportunity-row slate-result");
    item.dataset.key = kind + ":" + g.game_key + ":" + (row.quote_id || row.pair_id);
    const identity=el("div"), when=g.start_at ? new Date(g.start_at).toLocaleString("en-US",{timeZone:"America/New_York",month:"short",day:"numeric",hour:"numeric",minute:"2-digit"}) + " ET" : "Start unknown";
    identity.append(el("strong",kinds.length === 1 ? typedGameTitle(g.participants,g.title) : g.title),el("small",[g.league,when].filter(Boolean).join(" · ")));
    for (const leg of row.legs || [row]) identity.append(el("p",labelsFor(g.participants).selection(leg) + " · " + venue(leg.venue) + " " + price(leg)));
    if (kinds.length === 1) identity.append(el("small", marketCaption(row)));
    const value=el("div",undefined,"opportunity-value");
    value.append(el("strong",(numeric(m.value)>0?"+":"")+percent(m.value)),el("small",m.label),el("small",m.state === "numeric_current" && !slates[row.pair_id?"arbs":"ev"]?.dashboard_error ? "Current inputs" : slates[row.pair_id?"arbs":"ev"]?.dashboard_error ? "Freshness unverified after failed read" : "Last-known inputs"));
    const button=el("button","Details"); button.dataset.key=item.dataset.key; button.onclick=()=>onDetails(row,button,g);
    item.append(identity,value,button);root.append(item);
  }
  for (const kind of kinds) {
    const scope=scopes[kind]=dashboardScope(slates[kind],kind,filters), section=el("section",undefined,"opportunity-section");
    section.dataset.state=scope.state;
    section.setAttribute("aria-label",kind === "ev" ? "Positive expected value" : "Positive arbitrage");
    section.append(el("h2",kind === "ev" ? "Positive expected value" : "Positive arbitrage"),el("p",dashboardMessage(scope,kind),"opportunity-status"));
    if (scope.positive.length) {
      const best=scope.positive[0], lead=el("p",undefined,"opportunity-lead");
      lead.append(el("strong","+"+percent(dashboardMetric(best.row,kind).value)+" · "+best.g.title));
      const jump=el("a","View "+scope.positive.length+" positive results");jump.href="#positive-"+kind;
      section.append(lead,jump);
    }
    if (scope.reasons.length || scope.pending || scope.failed) {
      const d=el("details",undefined,"opportunity-reasons");d.dataset.key=kind+":reasons";d.append(el("summary","What’s needed"));
      const labels=dashboardReasons(scope.reasons);
      for (const label of labels) d.append(el("p",label));
      if(scope.pending)d.append(el("p","Some local calculations are pending."));
      if(scope.failed)d.append(el("p","A calculation or local read failed; use Reload results or inspect Admin."));
      const technical=el("details");technical.dataset.key=kind+":codes";technical.append(el("summary","Detailed reasons"));
      for(const code of scope.reasons)technical.append(el("p",words(code)));
      if(slates[kind]?.dashboard_error)technical.append(el("p",slates[kind].dashboard_error));
      d.append(technical);section.append(d);
    }
    if (scope.errors.length) {
      const failures = el("details"); failures.dataset.key = kind + ":failed-games";
      failures.append(el("summary", scope.errors.length + " games failed · other returned games remain inspectable"));
      for (const error of scope.errors) failures.append(el("p", (scope.games.get(error.game_key)?.title || error.game_key) + " · " + words(error.reason)));
      section.append(failures);
    }
    grid.append(section);
  }
  content.append(grid);
  const prices=el("section",undefined,"opportunity-prices");
  const link=el("a","Browse available prices →");
  const query=new URLSearchParams(Object.fromEntries(Object.entries({sport:filters.league || "",venue:filters.source || "",family:filters.family === "winner" ? "moneyline" : filters.family || "",period:filters.period || "",search:filters.search || ""}).filter(([,v])=>v)));
  link.href="/odds"+(query.size?"?"+query:"");
  prices.append(link,el("p","Inspect source prices and their original inputs. Gross comparisons exclude fees and exceptional settlement."));
  if (kinds.length > 1 && !kinds.some(kind => scopes[kind].positive.length)) content.replaceChildren(prices,grid);
  else content.append(prices);
  const results=el("div",undefined,"opportunity-sections");
  for (const kind of kinds) if(scopes[kind].positive.length) {
    const section=el("section",undefined,"opportunity-section");section.id="positive-"+kind;
    section.append(el("h2",kind === "ev" ? "Net EV results" : "Covered arbitrage results"));
    for(const entry of scopes[kind].positive)renderRow(section,entry,kind);
    results.append(section);
  }
  content.append(results);
  const research=el("div",undefined,"opportunity-research");
  for (const [kind,source,title] of [["ev","ev","Net EV · zero and negative"],["arbs","arbs","Covered minimum · zero and negative"],["conditional","ev","Conditional EV"],["trade","ev","Conditional trade-fee benchmarks"],["decisive","arbs","Decisive hedges"],["known","arbs","Listed known outcome hedges"],["gross","ev","Gross comparisons · before fees and exceptional settlement"]]) {
    if (!scopes[source]) continue;
    const entries=scopes[source].rows.filter(e => {
      const m=dashboardMetric(e.row,kind);
      return m && (!["ev","arbs"].includes(kind) || compareExactPercent(m.value,"0") >= 0 || m.state === "numeric_last_known" || slates[source]?.dashboard_error);
    });
    if(!entries.length)continue;
    const groups = [entries.filter(e=>dashboardMetric(e.row,kind).state === "numeric_current"),entries.filter(e=>dashboardMetric(e.row,kind).state !== "numeric_current")];
    for (const group of groups) {
      if(!group.length)continue;
      group.sort((a,b)=>compareExactPercent(dashboardMetric(a.row,kind).value,dashboardMetric(b.row,kind).value)||dashboardTie(a,b));
      const old=!!slates[source]?.dashboard_error || group.every(e=>dashboardMetric(e.row,kind).state !== "numeric_current");
      const d=el("details",undefined,"opportunity-group");d.dataset.key="research:"+kind+":"+old;
      d.append(el("summary",(old?"Last-known · ":"")+(old && kind === "ev" ? "Net EV research" : old && kind === "arbs" ? "Covered minimum research" : title)+" ("+group.length+")"));
      if(kind === "trade")d.append(el("p","Pregame conditional trade-fee scenarios. Each row states its modeled risk or contract basis. Excludes ties, pushes, voids and exceptional settlement. Not calibrated full net EV or executable sizing."));
      else if(kind === "gross")d.append(el("p","Exact two-way outcome and line, conditional on a decisive result. Before fees, ties, pushes and exceptional settlement; no executable quantity or net-EV claim."));
      else d.append(el("p","Highest percentage first. Funding, assumptions and quantities are in Details."));
      for(const e of group)renderRow(d,e,kind);
      research.append(d);
    }
  }
  content.append(research);
  if (scopes.ev) {
    const counts = new Map();
    for (const {row} of scopes.ev.rows) {
      for (const metric of [row.gross_decisive_benchmark,row.conditional_trade_benchmark]) {
        if (metric?.available === false && metric.reason) counts.set(metric.reason,(counts.get(metric.reason) || 0)+1);
      }
    }
    if (counts.size) {
      const gaps=el("details",undefined,"financial-gaps");gaps.dataset.key="financial-gaps";
      gaps.append(el("summary","Why stronger results are unavailable"),el("p","These are result-row limitations, not missing-offering counts. Full net EV also needs supported settlement cashflows and full-outcome probabilities; unknowns are never zero."));
      for (const [reason,count] of [...counts].sort((a,b)=>b[1]-a[1])) gaps.append(el("p",count+" rows · "+financialGap(reason)));
      content.append(gaps);
    }
  }
  if (kinds.length === 1) {
    const slate = slates.ev, scope = scopes.ev, details = el("details"); details.dataset.key = "ev-scope-evidence";
    details.append(el("summary", "Calculation coverage & evidence"));
    details.append(el("p", scope.games.size + " selected catalog games · " + scope.rows.length + " returned candidates. Counts are not proof of complete evaluation."));
    details.append(el("p", "Publication: " + (slate?.as_of || "Unknown") + ". Page retrieval does not renew original price or financial input clocks."));
    for (const b of slate?.boards || []) if (scope.games.has(b.game_key) && !b.rows.length)
      details.append(el("p", scope.games.get(b.game_key).title + " · " + words(b.empty_reason || b.availability?.outcome || "not_evaluated")));
    content.append(details);
  }
}
