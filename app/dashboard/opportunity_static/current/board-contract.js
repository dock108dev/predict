// Validate and expand exact server wire identities before presentation.
import { numeric, decimalEqual } from "./board-values.js";

export function checkPolicy(policy, context) {
  if (
    policy?.version !== "predict-estimate-policy-3" ||
    !policy.revision ||
    !decimalEqual(policy.requested_amount_usd, context.amount) ||
    !decimalEqual(policy.capital_ceiling_usd, context.amount) ||
    !decimalEqual(policy.buffer_rate, context.buffer) ||
    policy.benchmark_venue !== context.benchmark_venue ||
    policy.benchmark_method !== context.benchmark_method ||
    policy.sizing_mode !== "requested_trade"
  )
    throw Error("Settings identity crossed; response withheld.");
}
export const availabilityStates = ["numeric_current", "numeric_last_known", "missing_reference", "unsupported_inputs", "missing_inputs", "calculation_failed", "not_evaluated"];
const observationStates = ["current", "pending", "last_known", "unknown"];
const validTime = value => typeof value === "string" && Number.isFinite(Date.parse(value));
const reasonList = value => Array.isArray(value) && value.every(code => typeof code === "string" && code.length > 0);
function checkObservationDisplay(value) {
  if (value === undefined) return;
  if (!value || !observationStates.includes(value.state) || !validTime(value.read_at) ||
      !["reason_codes", "source_reason_codes", "publication_reason_codes"].every(key => reasonList(value[key])) ||
      !["source_age_seconds", "received_age_seconds"].every(key => value[key] === null || typeof value[key] === "number" && Number.isFinite(value[key])) ||
      !(value.current_until === null || validTime(value.current_until)))
    throw Error("Observation display status crossed; response withheld.");
}
function checkSameOutcome(value) {
  if (value === undefined) return;
  if (!value || typeof value.supported !== "boolean" || !reasonList(value.missing_fields) ||
      (value.supported ? !Array.isArray(value.key) || value.reason !== null : value.key !== null || typeof value.reason !== "string" || !value.reason) ||
      JSON.stringify(value).length > 16384)
    throw Error("Same-outcome identity crossed; response withheld.");
}
function checkObservationComparison(q) {
  checkSameOutcome(q.same_outcome);
  checkObservationDisplay(q.observation_display);
  for (const gross of [q.gross_comparison, q.current_comparison]) checkCapturedComparison(q, gross);
}
function checkCapturedComparison(q, gross) {
  // Older compatible source frames have no additive display metadata.
  if (!gross || gross.display_status === undefined) return;
  if (typeof gross.available !== "boolean" || ![...observationStates, "unavailable"].includes(gross.display_status) ||
      gross.available === (gross.display_status === "unavailable") || !validTime(gross.read_at) || !reasonList(gross.reason_codes) ||
      !(gross.source_time_skew_seconds === null || typeof gross.source_time_skew_seconds === "number" && Number.isFinite(gross.source_time_skew_seconds) && gross.source_time_skew_seconds >= 0) || !Array.isArray(gross.inputs))
    throw Error("Gross comparison display status crossed; response withheld.");
  if (gross.selection_valid_until !== undefined && gross.selection_valid_until !== null && !validTime(gross.selection_valid_until))
    throw Error("Current comparison selection boundary crossed; response withheld.");
  if (!gross.available) return;
  if (gross.inputs.length !== 2 || numeric(gross.value) === null || gross.unit !== "cents")
    throw Error("Gross comparison inputs crossed; response withheld.");
  if (typeof gross.exact?.numerator !== "string" || !/^-?\d+$/.test(gross.exact.numerator) ||
      typeof gross.exact?.denominator !== "string" || !/^[1-9]\d*$/.test(gross.exact.denominator))
    throw Error("Gross comparison exact value missing; response withheld.");
  const [selected, peer] = gross.inputs;
  for (const input of gross.inputs) {
    if (!input || !input.quote_id || !input.venue || !input.native_side || !input.original || !input.times || !input.selection)
      throw Error("Gross comparison original inputs missing; response withheld.");
    checkObservationDisplay(input.observation_display);
    checkSameOutcome(input.same_outcome);
    if (!["source_at", "received_at"].every(key => input.times[key] === null || validTime(input.times[key])))
      throw Error("Gross comparison original clocks crossed; response withheld.");
  }
  if (q.same_outcome && gross.inputs.every(input => input.same_outcome) &&
      (!q.same_outcome.supported || gross.inputs.some(input => !input.same_outcome.supported || JSON.stringify(input.same_outcome.key) !== JSON.stringify(q.same_outcome.key))))
    throw Error("Captured comparison same-outcome identity crossed; response withheld.");
  if (selected.quote_id !== q.quote_id || selected.quote_revision !== q.quote_revision || selected.venue !== q.venue || selected.native_side !== q.native_side ||
      JSON.stringify(selected.selection) !== JSON.stringify(q.selection) ||
      JSON.stringify(selected.original) !== JSON.stringify(q.original) || JSON.stringify(selected.times) !== JSON.stringify(q.times) ||
      peer.quote_id !== gross.comparison_quote_id || peer.venue !== gross.comparison_venue || peer.venue === selected.venue ||
      (gross.display_status === "current" && gross.inputs.some(input => input.observation_display?.state !== "current")))
    throw Error("Gross comparison selected frame crossed; response withheld.");
}
export function checkAvailability(value, summary = false) {
  if (!value || value.version !== "predict-calculation-availability-1") throw Error("Calculation availability missing; response withheld.");
  if (summary) {
    if (!availabilityStates.every(s => Number.isSafeInteger((value.counts?.[s] ?? (s === "missing_inputs" ? 0 : undefined))) && (value.counts[s] ?? 0) >= 0) ||
        Object.values(value.counts).reduce((a, b) => a + b, 0) !== value.total_results ||
        value.numeric_results !== value.counts.numeric_current + value.counts.numeric_last_known ||
        value.current_results !== value.counts.numeric_current ||
        !Number.isSafeInteger(value.positive_results) || value.positive_results < 0 ||
        !Array.isArray(value.causes) || !["not_evaluated", "unavailable", "partial", "last_known_only", "evaluated_no_positive", "positive"].includes(value.outcome))
      throw Error("Calculation availability counts crossed; response withheld.");
  } else if (!availabilityStates.includes(value.state) || !Array.isArray(value.reason_codes) ||
             !Array.isArray(value.numeric_metrics) || !value.metrics ||
             Object.values(value.metrics).some(m => !availabilityStates.includes(m.state) || !Array.isArray(m.reason_codes)) ||
             (value.state.startsWith("numeric_") !== (value.numeric_metrics.length > 0)) ||
             (value.current_opportunity_eligible && value.state !== "numeric_current") ||
             typeof value.current_opportunity_eligible !== "boolean")
    throw Error("Calculation availability state crossed; response withheld.");
  return value;
}
function inflateCapturedInputs(v) {
  if (v.shared_fields !== undefined) {
    const tree=v.shared_fields, nodes=tree.nodes, sizes=[], depths=[];
    if (tree.encoding !== "shared-json-1" || !Array.isArray(nodes) || nodes.length>1000000) throw Error("Invalid shared input frame");
    for (let i=0;i<nodes.length;i++) {
      const [kind,body]=nodes[i], refs=kind==="a"?body:kind==="o"?body.map(x=>x[1]):[];
      if (refs.some(r=>!Number.isSafeInteger(r)||r<0||r>=i)) throw Error("Invalid shared input reference");
      if (!["a","o","v"].includes(kind) || kind==="v" && body!==null && typeof body==="object") throw Error("Invalid shared input value");
      if (kind==="o" && (body.some(([k])=>typeof k!=="string"||["__proto__","constructor","prototype"].includes(k)) || new Set(body.map(x=>x[0])).size!==body.length)) throw Error("Invalid shared input keys");
      const size=kind==="v"?JSON.stringify(body).length*4:2+refs.reduce((n,r)=>n+sizes[r]+1,0)+(kind==="o"?body.reduce((n,[k])=>n+JSON.stringify(k).length*4+1,0):0);
      const depth=kind==="v"?0:1+Math.max(0,...refs.map(r=>depths[r]));
      if(size>96*1024*1024||depth>96)throw Error("Shared input expansion capacity");
      sizes.push(size);depths.push(depth);
    }
    if(!Number.isSafeInteger(tree.root)||tree.root<0||tree.root>=nodes.length)throw Error("Invalid shared input root");
    const restore=i=>{const [kind,body]=nodes[i];return kind==="o"?Object.fromEntries(body.map(([k,r])=>[k,restore(r)])):kind==="a"?body.map(restore):body;};
    const fields=restore(tree.root);
    if(Object.keys(fields).some(k=>!["prices","rows","price_field_pool","financial_field_pool","native_wordings"].includes(k)))throw Error("Invalid shared board fields");
    delete v.shared_fields;Object.assign(v,fields);
  }
  if (v.financial_field_pool !== undefined) {
    if (!Array.isArray(v.financial_field_pool)) throw Error("Captured financial field pool missing");
    for (const row of v.rows) {
      const refs = row.financial_field_refs ?? {};
      if (!refs || typeof refs !== "object" || Array.isArray(refs)) throw Error("Captured financial field references invalid");
      for (const [key,index] of Object.entries(refs)) {
        if (Object.hasOwn(row,key) || ["__proto__","constructor","prototype"].includes(key) || !Number.isSafeInteger(index) || index < 0 || index >= v.financial_field_pool.length) throw Error("Captured financial field reference crossed");
        row[key] = JSON.parse(JSON.stringify(v.financial_field_pool[index]));
      }
      delete row.financial_field_refs;
    }
    delete v.financial_field_pool;
  }
  if (v.price_key_pool !== undefined) {
    const names = v.price_key_pool;
    if (!Array.isArray(names) || names.some(k => typeof k !== "string" || ["__proto__","constructor","prototype"].includes(k)) || new Set(names).size !== names.length) throw Error("Captured field names invalid");
    const decode = k => {
      if (!/^(0|[1-9][0-9]*)$/.test(k) || !Number.isSafeInteger(Number(k)) || Number(k) >= names.length) throw Error("Captured field name crossed");
      return names[Number(k)];
    };
    v.prices = v.prices.map(q => {
      const restored = {};
      for (const [k,value] of Object.entries(q)) {
        const key = ["quote_id","quote_revision","field_refs"].includes(k) ? k : decode(k);
        if (Object.hasOwn(restored,key)) throw Error("Captured field name crossed");
        restored[key] = k === "field_refs" ? Object.fromEntries(Object.entries(value).map(([n,r]) => [decode(n),r])) : value;
      }
      return restored;
    });
    delete v.price_key_pool;
  }
  if (v.price_field_pool !== undefined) {
    if (!Array.isArray(v.price_field_pool)) throw Error("Captured field pool missing");
    for (const q of v.prices) {
      for (const [key,index] of Object.entries(q.field_refs || {})) {
        if (Object.hasOwn(q,key) || ["__proto__","constructor","prototype"].includes(key) || !Number.isSafeInteger(index) || index < 0 || index >= v.price_field_pool.length) throw Error("Captured field reference crossed");
        q[key] = JSON.parse(JSON.stringify(v.price_field_pool[index]));
      }
      delete q.field_refs;
    }
    delete v.price_field_pool;
  }
  if (v.price_object_keys !== undefined) {
    const names = v.price_object_keys;
    if (!Array.isArray(names) || names.some(k => typeof k !== "string" || ["__proto__","constructor","prototype"].includes(k)) || new Set(names).size !== names.length) throw Error("Captured object names invalid");
    for (const row of v.prices) {
      for (const [field,value] of Object.entries(row)) {
        if (!value || typeof value !== "object" || Array.isArray(value)) continue;
        const restored = {};
        for (const [key,item] of Object.entries(value)) {
          if (!/^(0|[1-9][0-9]*)$/.test(key) || !Number.isSafeInteger(Number(key)) || Number(key) >= names.length) throw Error("Captured object name crossed");
          restored[names[Number(key)]] = item;
        }
        row[field] = restored;
      }
    }
    delete v.price_object_keys;
  }
  if (v.comparison_input_encoding === undefined) return;
  if (v.comparison_input_encoding !== "same-board-price-refs-1") throw Error("Unknown comparison input encoding");
  const prices = new Map(v.prices.map(q => [q.quote_id,q]));
  const fields = ["quote_id","quote_revision","venue","native_side","selection","original","times","source","native_contract_id","native_contract_summary","same_outcome","market","source_state","source_health","captured_source_state","captured_source_health","freshness_policy","event","freshness","observation_display"];
  for (const q of v.prices) {
    q.captured_source_health ??= JSON.parse(JSON.stringify(q.source_health || {}));
    const summary = q.native_contract_summary;
    if (summary?.wording_refs) {
      if (!Array.isArray(v.native_wordings)) throw Error("Captured native wording pool missing");
      summary.wording ??= Object.fromEntries(summary.wording_refs.map(([label,index]) => {
        if (typeof label !== "string" || !Number.isSafeInteger(index) || index < 0 || index >= v.native_wordings.length) throw Error("Captured native wording reference crossed");
        return [label,JSON.parse(JSON.stringify(v.native_wordings[index]))];
      }));
    }
  }
  for (const q of v.prices) for (const value of [q.gross_comparison,q.current_comparison]) {
    if (!value?.available) continue;
    if (!value.input_refs && value.inputs?.length === 2) continue;
    if (!Array.isArray(value.input_refs) || value.input_refs.length !== 2) throw Error("Captured price reference coverage crossed");
    if (value.inputs?.length) {
      if (value.inputs.length !== 2 || value.input_refs.some((ref,index) => ref.quote_id !== value.inputs[index].quote_id || ref.quote_revision !== value.inputs[index].quote_revision)) throw Error("Captured expanded price reference crossed");
      continue;
    }
    value.inputs = value.input_refs.map(ref => {
      const original = prices.get(ref.quote_id);
      if (!original || ref.quote_revision !== original.quote_revision) throw Error("Captured price reference crossed");
      return JSON.parse(JSON.stringify(Object.fromEntries(fields.filter(key => original[key] !== undefined).map(key => [key,original[key]]))));
    });
  }
}
function inflateFinancialPrices(v) {
  if (v.view === "odds" || !Array.isArray(v.rows)) return;
  const prices = new Map(v.prices.map(q => [q.quote_id,q]));
  for (const row of v.rows) for (const item of row.legs || [row]) {
    if (item.price_ref === undefined) continue;
    const q = prices.get(item.price_ref);
    if (!q || q.quote_id !== item.quote_id || q.quote_revision !== item.quote_revision || q.venue !== item.venue) throw Error("Financial original price reference crossed");
    const original = JSON.parse(JSON.stringify(q));
    const saved = {...item}; Object.assign(item, original, saved);
  }
}
export function checkBoard(v, c) {
  if (Array.isArray(v.prices)) { inflateCapturedInputs(v); inflateFinancialPrices(v); }
  checkPolicy(v.policy, c);
  if (v.availability !== undefined) checkAvailability(v.availability, true);
  if (
    v.version !== "predict-comparison-board-2" ||
    v.game_key !== c.game ||
    v.view !== c.view ||
    v.filter !== c.filter ||
    !v.input_version ||
    !Array.isArray(v.prices) ||
    !Array.isArray(v.rows) ||
    v.benchmark?.venue !== c.benchmark_venue
  )
    throw Error("Game or view identity crossed; response withheld.");
  const observationContext = (v.view === "odds" || !v.rows.length) && v.calculation_context?.policy_revision === undefined &&
    v.prices.every(q => typeof q.observation_revision === "string" && q.observation_revision.length > 0);
  checkCalculationContext(v.calculation_context, observationContext ? undefined : v.policy.revision);
  if (v.calculation_context.dependency_revision !== v.input_version)
    throw Error("Current dependency identity crossed; response withheld.");
  if (v.result_id != null || v.snapshot_id != null)
    throw Error("Legacy saved identity is unavailable; reopen the current view.");
  for (const q of v.prices) {
    checkObservationComparison(q);
    if (
      !q.quote_id ||
      !q.original ||
      !q.original.units ||
      q.inputs_identity?.quote_id !== q.quote_id ||
      q.inputs_identity?.game_key !== v.game_key ||
      q.inputs_identity?.input_version !== v.input_version ||
      q.inputs_identity?.context_id !== v.calculation_context.context_id
    )
      throw Error("Original price identity crossed; response withheld.");
  }
  if (c.view === "odds" && v.rows.some(row => row.price_ref !== undefined)) {
    const originals = new Map(v.prices.map(q => [q.quote_id,q])), seen = new Set();
    for (const row of v.rows) {
      const q = originals.get(row.price_ref);
      if (!q || seen.has(row.price_ref) || row.quote_id !== q.quote_id || row.quote_revision !== q.quote_revision || row.venue !== q.venue ||
          !["participant","predicate","signed_line","result_interpretation"].every(key => (row.selection?.[key] ?? null) === (q.selection?.[key] ?? null)) ||
          !["market","period"].every(key => (row.market?.[key] ?? null) === (q.market?.[key] ?? null)))
        throw Error("Odds row reference crossed; response withheld.");
      seen.add(row.price_ref);
    }
    if (seen.size !== originals.size) throw Error("Odds row reference coverage crossed; response withheld.");
  }
  for (const row of v.rows) {
    if (c.view === "odds") continue;
    if (row.availability !== undefined) {
      checkAvailability(row.availability);
      for (const key of row.availability.numeric_metrics) if (numeric(row.financial_metrics?.[key]) === null)
        throw Error("Numeric availability crossed; response withheld.");
      if (row.availability.state === "numeric_last_known" && (row.ranking_eligible || row.classification?.main_positive_eligible || row.classification?.positive_rule_sensitive_eligible))
        throw Error("Last-known result cannot be a current opportunity.");
    }
    if (
      c.filter !== "all" &&
      (row.freshness?.status !== "current" ||
        !row.classification?.[
          c.filter === "positive"
            ? "main_positive_eligible"
            : "positive_rule_sensitive_eligible"
        ])
    )
      throw Error(
        "Positive result freshness or classification crossed; response withheld.",
      );
    if (
      row.model_available &&
      (!row.financial_metrics ||
        !row.funding?.legs?.length ||
        row.funding.legs.some(
          (l) => !l.native_unit?.unit || l.native_quantity == null,
        ))
    )
      throw Error("Funded quantity or units missing; response withheld.");
    const d = row.details;
    if (
      d?.context_id !== v.calculation_context.context_id ||
      d.result_id != null || d.snapshot_id != null ||
      d.policy_revision !== v.policy.revision ||
      !!d.quote_id === !!d.pair_id ||
      (c.view === "ev"
        ? d.quote_id !== row.quote_id
        : d.pair_id !== row.pair_id)
    )
      throw Error("Selection identity crossed; response withheld.");
  }
  return v;
}
export function checkSlate(v, c) {
  if (v.read_at !== undefined && !validTime(v.read_at)) throw Error("Slate read time crossed; response withheld.");
  if (v.read_token !== undefined && (typeof v.read_token !== "string" || !/^[A-Za-z0-9_-]{16,256}$/.test(v.read_token) ||
      !validTime(v.read_at) || !validTime(v.read_expires_at) || Date.parse(v.read_expires_at) <= Date.parse(v.read_at)))
    throw Error("Slate captured-read identity crossed; response withheld.");
  const shared = v.sizing_scope === "shared_default_selected_details";
  const boardContext = shared ? { ...c, amount: v.policy?.requested_amount_usd,
    buffer: v.policy?.buffer_rate, benchmark_venue: v.policy?.benchmark_venue,
    benchmark_method: v.policy?.benchmark_method, sizing_mode: v.policy?.sizing_mode } : c;
  checkPolicy(v.policy, boardContext);
  if (v.availability !== undefined) checkAvailability(v.availability, true);
  if (
    v.version !== "predict-comparison-slate-2" ||
    v.view !== c.view ||
    v.filter !== c.filter ||
    !Array.isArray(v.games) ||
    !Array.isArray(v.boards) ||
    v.boards.length > 50 ||
    (!Number.isSafeInteger(v.bounds?.maximum_games) || v.bounds.maximum_games < v.games.length) ||
    v.bounds?.maximum_page_games !== 50 ||
    typeof v.read_revision !== "string" || !v.read_revision ||
    typeof v.epoch !== "string" || !v.epoch ||
    v.bounds?.maximum_bytes !== 8388608 ||
    (v.errors !== undefined && !Array.isArray(v.errors)) ||
    typeof v.stopped !== "boolean"
  )
    throw Error("Slate or view identity crossed; response withheld.");
  const catalog = new Map();
  for (const g of v.games) {
    if (!g.game_key || !g.title || !Array.isArray(g.participants) || catalog.has(g.game_key))
      throw Error("Slate occurrence identity crossed; response withheld.");
    catalog.set(g.game_key, g);
  }
  const coverage = v.coverage;
  if (!coverage || coverage.total_games !== v.games.length ||
      !Number.isSafeInteger(coverage.offset) || coverage.offset < 0 || coverage.offset > v.games.length ||
      !Number.isSafeInteger(coverage.limit) || coverage.limit < 1 || coverage.limit > 50 ||
      !Number.isSafeInteger(coverage.returned_games) ||
      coverage.returned_games < (v.games.length === 0 ? 0 : 1) ||
      coverage.returned_games > Math.min(coverage.limit, v.games.length - coverage.offset) ||
      coverage.next_offset !== (coverage.offset + coverage.returned_games < v.games.length ? coverage.offset + coverage.returned_games : null) ||
      coverage.complete !== (coverage.next_offset === null))
    throw Error("Current slate page coverage crossed; response withheld.");
  const expected = new Set(v.games.slice(coverage.offset, coverage.offset + coverage.returned_games).map(g => g.game_key));
  const seen = new Set();
  for (const b of v.boards) {
    if (!expected.has(b.game_key) || seen.has(b.game_key) || b.policy?.revision !== v.policy.revision)
      throw Error("Slate board occurrence crossed; response withheld.");
    checkBoard(b, { ...boardContext, game: b.game_key });
    if (b.calculation_context.epoch !== v.epoch)
      throw Error("Current reset identity crossed; response withheld.");
    seen.add(b.game_key);
  }
  for (const error of v.errors || []) {
    if (error.availability !== undefined) checkAvailability(error.availability);
    if (!expected.has(error.game_key) || seen.has(error.game_key) || typeof error.reason !== "string")
      throw Error("Slate unavailable occurrence crossed; response withheld.");
    seen.add(error.game_key);
  }
  if (seen.size !== expected.size)
    throw Error("Slate occurrence board absent; response withheld.");
  return v;
}
export function checkCalculationContext(value, policyRevision) {
  if (!value || !["context_id", "epoch", "dependency_revision", "engine_binding"].every(k => typeof value[k] === "string" && value[k].length > 0 && value[k].length <= 256) || value.policy_revision !== policyRevision)
    throw Error("Current calculation identity unavailable; response withheld.");
  return value;
}
export function checkDetails(v, c, d) {
  checkPolicy(v.policy, c);
  const selection = v.selection_context || v.calculation_context;
  checkCalculationContext(selection, d.policy_revision);
  checkCalculationContext(v.calculation_context, v.policy.revision);
  if (
    v.version !== "predict-board-details-2" ||
    v.game_key !== c.game ||
    v.original_inputs_identity?.game_key !== c.game ||
    v.original_inputs_identity?.context_id !== d.context_id ||
    v.original_inputs_identity?.policy_revision !== d.policy_revision ||
    selection.context_id !== d.context_id ||
    v.calculation_context.epoch !== selection.epoch ||
    v.calculation_context.dependency_revision !== selection.dependency_revision ||
    v.calculation_context.engine_binding !== selection.engine_binding ||
    v.result_id != null || v.snapshot_id != null ||
    (d.quote_id
      ? v.quote?.id !== d.quote_id || v.pair != null
      : v.pair?.id !== d.pair_id || v.quote != null)
  )
    throw Error("Details identity crossed; response withheld.");
  const result = v.pair || v.quote?.calculations?.funded_estimate;
  if (result?.availability !== undefined) checkAvailability(result.availability);
  return v;
}
export function checkInputs(v, c, identity) {
  const observationContext = v.calculation_context?.policy_revision === undefined &&
    typeof identity.observation_revision === "string" && identity.observation_revision.length > 0;
  checkCalculationContext(v.calculation_context, observationContext ? undefined : identity.policy_revision);
  if (v.version !== "predict-board-inputs-2" || v.game_key !== c.game ||
      v.calculation_context.context_id !== identity.context_id || v.quote_id !== identity.quote_id ||
      (identity.observation_revision !== undefined && v.observation_revision !== identity.observation_revision) ||
      (identity.quote_revision !== undefined && v.quote_revision !== identity.quote_revision) ||
      !v.evidence || typeof v.evidence !== "object" || Array.isArray(v.evidence))
    throw Error("Original price changed; reopen its current identity.");
  return v;
}
// A complete browser view uses byte-bounded pages, each advancing at least one
// game (at most 500 pages), within the unchanged 80 MiB total. Separately bounded
// wire pages. It has its own identity and byte disclosure; it is never a wire
// slate claiming that 500 boards fit within one 8 MiB response.
