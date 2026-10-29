import { drawOpportunityDashboard } from "./opportunity-dashboard.js";
import {
  defaults,
  numeric,
  money,
  percent,
  quantity,
  settings,
  readSlate,
  checkDetails,
  checkInputs,
  LatestRead,
  SavedReadPoller,
  followGame,
} from "./board-client.js";
import {
  $,
  el,
  venue,
  words,
  time,
  textLine,
  freshness,
  price,
  labelsFor,
  typedGameTitle,
  priceResearch,
  matchesGameSearch,
  marketFamily,
  updateRelativeAges,
  preserveDisclosures,
} from "./board-elements.js";
import { createSlateViews } from "./stored-views.js";
import { renderSavedDetails, renderOriginalDetails } from "./stored-details.js";

const setStatus = (message, state = "ready") => {
  if ($("status").textContent !== message) $("status").textContent = message;
  $("status").dataset.state = state;
};
const dashboard = location.pathname === "/";
const dashboardSlates = {ev:null,arbs:null};
const view =
  dashboard || location.pathname === "/ev"
    ? "ev"
    : location.pathname === "/arbs"
      ? "arbs"
      : "odds";
const read = new LatestRead(),
  detailRead = new LatestRead(),
  originalRead = new LatestRead();
let pullGeneration = 0;
let oddsGroups = "";
const priceGroups = v => v.boards.map(b => b.prices.map(q => priceResearch(q) ? "r" : "c").join("")).join("|");
let previousSelection = null;
let applied = { ...defaults },
  games = [],
  game = "",
  filter = dashboard || view === "odds" || view === "ev" ? "all" : "positive",
  current = null,
  stopped = false,
  stopRequested = false,
  detail = null,
  opener = null,
  failures = 0,
  unloading = false;
const polling = new SavedReadPoller({
  onRead: pull,
  canRead: () => !unloading && failures < 4 && !read.pending && (!$("details").open || detail?.kind === "result"),
});
try {
  const saved = JSON.parse(sessionStorage.getItem("predict-board-settings"));
  if (saved)
    applied = settings(
      saved.amount,
      String(numeric(saved.buffer) * 100),
      saved.benchmark_venue,
    );
  game = sessionStorage.getItem("predict-board-slate-game") || "";
  previousSelection = JSON.parse(
    sessionStorage.getItem("predict-board-selection") || "null",
  );
  $("search").value = sessionStorage.getItem("predict-board-slate-search") || "";
  for (const key of ["league", "family", "period", "venue"]) if ($(key)) $(key).dataset.saved = sessionStorage.getItem("predict-board-slate-" + key) || "";
} catch {}
if (dashboard) {
  game = ""; $("search").value = "";
  for (const key of ["league", "family", "period", "venue"]) $(key).dataset.saved = sessionStorage.getItem("predict-dashboard-" + key) || "";
}
// Coverage links select a local display scope. They do not change collection,
// the captured slate request, or a frozen Details frame.
const incomingScope = new URLSearchParams(location.search || "");
if (["league", "family", "period", "venue"].some(key => incomingScope.has(key))) {
  game = "";
  $("search").value = "";
  for (const key of ["league", "family", "period", "venue"]) if ($(key)) $(key).dataset.saved = incomingScope.get(key) || "";
}
function form() {
  $("amount").value = applied.amount;
  $("buffer").value = String(numeric(applied.buffer) * 100);
  $("benchmark").value = applied.benchmark_venue;
}
function context() {
  return { ...applied, game, view, filter };
}
function query(c) {
  const qs = new URLSearchParams({
    amount: c.amount,
    buffer: c.buffer,
    benchmark_venue: c.benchmark_venue,
    benchmark_method: c.benchmark_method,
    sizing_mode: c.sizing_mode,
  });
  if (c.game) qs.set("game", c.game);
  return qs;
}
function persist() {
  const selected = games.find((g) => g.game_key === game);
  if (selected) {
    previousSelection = selected;
    sessionStorage.setItem("predict-board-selection", JSON.stringify(selected));
  }
  sessionStorage.setItem("predict-board-settings", JSON.stringify(applied));
  sessionStorage.setItem("predict-board-slate-game", game);
  sessionStorage.setItem("predict-board-slate-search", $("search").value);
  for (const key of ["league", "family", "period", "venue"]) if ($(key)) sessionStorage.setItem("predict-board-slate-" + key, $(key).value);
  if (dashboard) for (const key of ["league", "family", "period", "venue"]) sessionStorage.setItem("predict-dashboard-" + key, $(key).value);
}
function preserveContent(draw) {
  const active = document.activeElement,
    key = active?.dataset.key || active?.closest?.("details")?.dataset.key,
    focusedSummary = active?.tagName === "SUMMARY",
    anchor = [...$("content").querySelectorAll(".slate-result, .slate-game")].find(n => n.getBoundingClientRect().bottom > 100),
    anchorKey = anchor?.dataset.key, anchorTop = anchor?.getBoundingClientRect().top,
    disclosures = [...$("content").querySelectorAll("details[open]")].map(
      (d) => d.dataset.key,
    );
  draw();
  for (const d of $("content").querySelectorAll("details"))
    if (disclosures.includes(d.dataset.key)) d.open = true;
  if (anchorKey) {
    const replacement = [...$("content").querySelectorAll("[data-key]")].find(n => n.dataset.key === anchorKey && n.className === anchor.className);
    if (replacement) window.scrollBy(0, replacement.getBoundingClientRect().top - anchorTop);
  }
  if (key) {
    const target = focusedSummary
      ? [...$("content").querySelectorAll("details")].find(d => d.dataset.key === key)?.querySelector("summary")
      : [...$("content").querySelectorAll("button[data-key]")].find(b => b.dataset.key === key);
    (target || $("content")).focus({preventScroll:true});
  }
}
function draw(v) {
  if (view === "odds") oddsGroups = priceGroups(v);
  if (dashboard) {
    current = v;
    $("applied").textContent = money(applied.amount) + " · " + percent(String(numeric(applied.buffer)*100)) + " buffer · " + venue(applied.benchmark_venue);
    preserveContent(() => drawOpportunityDashboard($("content"),dashboardSlates,{game,search:$("search").value,league:$("league").value,family:$("family").value,period:$("period").value,source:$("venue").value},openDetails));
    return;
  }
  const renderers = createSlateViews({
    content: $("content"),
    onDetails: openDetails,
    onOriginal: openOriginal,
  });
  if ((stopRequested || failures) && view !== "odds" && filter !== "all")
    v = {
      ...v,
      boards: v.boards.map(b => ({ ...b, rows: [] })),
    };
  current = v;
  const settingsLabel = (amount, buffer, benchmark) => money(amount) + " · " +
    percent(String(numeric(buffer) * 100)) + " buffer · " + venue(benchmark);
  const sharedLabel = settingsLabel(v.policy.requested_amount_usd, v.policy.buffer_rate, v.policy.benchmark_venue);
  const detailsLabel = settingsLabel(applied.amount, applied.buffer, applied.benchmark_venue);
  $("applied").textContent = detailsLabel === sharedLabel ? detailsLabel :
    "Details " + detailsLabel + ". Shared comparisons " + sharedLabel;
  const pending = v.boards.filter(b => b.delivery_state === "pending").length;
  const firstPending = v.boards.filter(b => b.delivery_state === "pending" && !b.calculated_at).length;
  const refreshing = pending - firstPending;
  const calculationNote = [firstPending ? firstPending + " games awaiting first calculation" : "", refreshing ? "Refreshing captured results for " + refreshing + " games" : ""].filter(Boolean).join("; ");
  const unavailable = v.storage?.state === "unavailable",
    storageLimit = String(v.storage?.error || "").includes("storage_cap") || (v.storage?.sql_bytes != null && v.storage?.sql_bytes >= v.storage?.sql_byte_cap);
  const storageNote = unavailable ? (storageLimit ? "Saving paused — storage limit reached. Open Admin to review storage." : "Saving updates paused. Source status is in Admin.") : v.storage?.state === "catching_up" ? "Saving new inputs…" : "";
  setStatus(storageNote || (stopped ? "Collection stopped. Existing observations remain available." : pending ? view === "odds" ? "Updating stored observations for " + pending + " games. Original source clocks remain visible." : calculationNote + ". Prices remain available." : ""), unavailable ? "error" : pending ? "busy" : "ready");
  if (failures) setStatus("Current reads unavailable. Prior values have unverified freshness.", "error");
  if (view === "ev") {
    preserveContent(() => drawOpportunityDashboard($("content"), {ev:{...v, stopped:stopped || v.stopped, ...(failures ? {dashboard_error:$("read-error").textContent || "Current read failed"} : {})}},
      {game,search:$("search").value,league:$("league").value,family:$("family").value,period:$("period").value,source:$("venue").value}, openDetails, ["ev"]));
    return;
  }
  preserveContent(() =>
    renderers.draw(v, {
      view,
      filter,
      game,
      search: $("search").value,
      league: $("league").value, family: $("family").value, period: $("period").value,
      source: $("venue")?.value || "",
      sort: $("sort").value,
      onShowAll: () => { const all = $("filters").querySelector("[data-filter=all]"); all.click(); all.focus({ preventScroll: true }); },
    }),
  );
}
function catalogOptions() {
  const options = {
    league:[...new Set([...(dashboard ? ["NFL","NCAAF","NBA","NCAAB","MLB","NHL"] : []), ...games.map(g => g.league || g.scope?.split("/")[0]).filter(Boolean)])].sort(),
    family:[...new Set([...(dashboard ? ["winner","spread","total"] : []), ...(current?.boards || []).flatMap(b => b.prices.map(marketFamily))])].sort(),
    period:[...new Set((current?.boards || []).flatMap(b => b.prices.map(q => q.market?.period || "full_game")))].sort(),
    venue:[...new Set(["kalshi", "polymarket_us", "novig", "prophetx", "pinnacle", ...(current?.boards || []).flatMap(b => b.prices.map(q => q.venue))])].sort(),
  };
  for (const [key, values] of Object.entries(options)) {
    const target = $(key);
    if (!target) continue;
    const selected = target.dataset.saved || target.value;
    // Keep a linked empty/unsupported scope visible instead of silently showing
    // a broader collection when that cell currently has no retained prices.
    if (selected && !values.includes(selected)) values.push(selected);
    const signature = JSON.stringify(values);
    if (target.dataset.signature !== signature) {
      target.dataset.signature = signature;
      target.replaceChildren(...["",...values].map(value => { const o = el("option", value ? (key === "family" && value === "winner" ? "Winner / moneyline" : key === "venue" ? venue(value) : words(value)) : "All " + ({league:"leagues", family:"markets", period:"periods", venue:"sources"}[key])); o.value = value; return o; }));
    }
    target.value = values.includes(selected) ? selected : "";
    delete target.dataset.saved;
  }
  const search = $("search").value.toLowerCase(),
    visible = games.filter(
      (g) => ((!$("league").value || (g.league || g.scope?.split("/")[0]) === $("league").value) && matchesGameSearch(g, search)) || g.game_key === game,
    );
  const signature = JSON.stringify(visible.map((g) => [g.game_key, g.title]));
  if ($("game").dataset.signature === signature) { $("game").value = game; return; }
  $("game").dataset.signature = signature;
  $("game").replaceChildren(
    (() => { const o = el("option", "All games"); o.value = ""; return o; })(),
    ...visible.map((g) => {
      const o = el(
        "option",
        [g.league || g.sport, typedGameTitle(g.participants, g.title), time(g.start_at)].filter(Boolean).join(" · ") +
          (g.matches?.some((m) => m.status === "conflict")
            ? " · Unmatched source"
            : ""),
      );
      o.value = g.game_key;
      return o;
    }),
  );
  $("game").value = game;
}
function retainDisplayed() {
  const tokens = new Set((dashboard ? Object.values(dashboardSlates) : [current]).map(v => v?.read_token).filter(Boolean));
  for (const token of tokens) fetch('/api/boards/read-lease?read_token=' + encodeURIComponent(token)).catch(() => {});
}
const displayedTimer = setInterval(() => { if (!unloading) retainDisplayed(); }, 10000);
window.addEventListener('pagehide', () => clearInterval(displayedTimer));
async function pullDashboard() {
  polling.cancel();
  if (failures >= 4) return;
  const generation = ++pullGeneration;
  let succeeded = 0, requiresReload = false;
  for (const kind of ["arbs","ev"]) {
    try {
      const value = await readSlate(read,{...context(),view:kind,filter:"all"},{isCurrent:()=>generation === pullGeneration && !unloading});
      if (!value || generation !== pullGeneration) return;
      dashboardSlates[kind] = value;
      retainDisplayed();
      succeeded++;
      stopped = value.stopped;
      polling.setSlate(value);
    } catch(e) {
      if(e.name === "AbortError" || generation !== pullGeneration) return;
      requiresReload ||= e.requiresReload === true;
      dashboardSlates[kind] = {...(dashboardSlates[kind] || {}),dashboard_error:e.message};
    }
    const available = dashboardSlates.ev?.policy ? dashboardSlates.ev : dashboardSlates.arbs;
    if (available?.policy) {
      current = available;
      games = [...new Map(Object.values(dashboardSlates).flatMap(v=>v?.games || []).map(g=>[g.game_key,g])).values()];
      catalogOptions();
      persist();
      draw(current);
    } else preserveContent(()=>drawOpportunityDashboard($("content"),dashboardSlates,{},openDetails));
  }
  failures = requiresReload ? 4 : succeeded ? 0 : failures + 1;
  const failed = Object.values(dashboardSlates).some(v=>v?.dashboard_error);
  $("retry").hidden = !failed;
  $("retry").textContent = "Reload results";
  setStatus(failed ? "Some local results could not be refreshed. Each section shows its availability." : "");
  if(detail?.kind === "result") refreshDetails();
  // Two complete view reads share the ordinary lane; avoid rapid pending loops.
  polling.delay = Math.max(polling.delay, 10000);
  polling.schedule();
}
async function pull() {
  if (dashboard) return pullDashboard();
  polling.cancel();
  if (failures >= 4) return;
  const c = context(), generation = ++pullGeneration;
  try {
    const value = await readSlate(read, c, {
      isCurrent: () => generation === pullGeneration && !unloading,
      onProgress: ({loaded,total}) => { if (!current) setStatus(`Loading saved results · ${loaded} of ${total} games…`, "busy"); },
      onRecovery: () => setStatus(current ? "Current reads unavailable. Prior values have unverified freshness. Recovering stored observations…" : "Recovering stored observations…", "busy"),
    });
    if (!value || generation !== pullGeneration) return;
    polling.setSlate({ ...value, stopped: stopRequested || value.stopped });
    const continued = followGame(
      games.find((g) => g.game_key === game) ||
        (previousSelection?.game_key === game ? previousSelection : null),
      value.games,
      game,
    );
    if (continued !== game) {
      game = continued;
    }
    games = value.games;
    $("game").disabled = !games.length;
    document.querySelector(".selection").hidden = !games.length;
    $("settings").hidden = !games.length;
    $("applied").hidden = !games.length;
    $("filters").hidden = view !== "arbs" || !games.length;
    $("sort-setting").hidden = view !== "arbs" || !games.length;
    stopped = stopRequested || value.stopped;
    $("stop").disabled = stopped;
    $("stop").textContent = stopped ? "Collection stopped" : "Stop collection";
    current = value;
    retainDisplayed();
    catalogOptions();
    persist();
    failures = 0;
    $("retry").hidden = true;
    $("read-diagnostics").hidden = true;
    if (!games.length) {
      draw(value);
      setStatus("");
      return;
    }
    if (game && !games.some((g) => g.game_key === game)) {
      game = "";
      catalogOptions();
      persist();
    }
    draw(value);
    if (detail?.kind === "result") refreshDetails();
  } catch (e) {
    if (e.name === "AbortError" || generation !== pullGeneration) return;
    polling.setSlate(null);
    failures = e.requiresReload ? 4 : failures + 1;
    if (!games.length) {
      $("game").disabled = true;
      $("game").replaceChildren(el("option", "Games unavailable"));
    }
    if (filter !== "all")
      $("content").replaceChildren(
        el(
          "p",
          "Positive results withheld while current reads are unavailable.",
          "notice",
        ),
      );
    if (!current) {
      document.querySelector(".selection").hidden = true;
      $("settings").hidden = true;
      $("filters").hidden = true;
    }
    setStatus(e.requiresReload
      ? "This captured list expired or became unavailable. Reload results to capture a new list; your filters and position are kept where possible. Prior values have unverified freshness."
      : current ? "Current reads unavailable. Prior values have unverified freshness. Retry or check sources in Admin." : "Couldn’t load current games. Retry or check sources in Admin.", "error");
    $("retry").textContent = "Reload results";
    $("read-error").textContent = e.message;
    $("read-diagnostics").hidden = false;
    $("retry").hidden = false;
    if (view === "ev") {
      if (current) draw(current);
      else preserveContent(() => drawOpportunityDashboard($("content"), {ev:{dashboard_error:e.message}}, {}, openDetails, ["ev"]));
    }
  } finally {
    if (generation === pullGeneration && !read.pending) polling.schedule();
  }
}
function showDialog(button) {
  opener = button;
  $("details").showModal();
  $("close-details").focus();
}
function closeDetails() {
  const wasOpen = $("details").open;
  if (detail?.selectedToken) fetch("/api/boards/read-lease?read_token=" + encodeURIComponent(detail.selectedToken), {method:"DELETE"}).catch(() => {});
  detail = null;
  detailRead.cancel();
  originalRead.cancel();
  $("details").close();
  polling.schedule();
  if (wasOpen) {
    const target = opener?.isConnected
      ? opener
      : [...$("content").querySelectorAll("button[data-key]")].find(
          (b) => b.dataset.key === opener?.dataset.key,
        );
    if (target) target.focus();
    else (dashboard || view === "ev" ? $("content") : $("game")).focus();
  }
}
$("close-details").onclick = closeDetails;
$("details").addEventListener("keydown", e => {
  if (e.key !== "Tab") return;
  const targets = [...$("details").querySelectorAll("button:not([disabled]), summary, a[href], input:not([disabled]), select:not([disabled]), [tabindex='0']")].filter(n => n.getClientRects().length);
  const first = targets[0], last = targets[targets.length - 1];
  if (e.shiftKey && document.activeElement === first || !e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    (e.shiftKey ? last : first)?.focus();
  }
});
$("details").addEventListener("cancel", (e) => {
  e.preventDefault();
  closeDetails();
});
function reconcile(v) {
  renderSavedDetails(v, {
    root: $("detail-content"),
    participants: detail.participants,
  });
}
function detailFailure(message, diagnostic) {
  $("detail-content").replaceChildren(el("p",message,"warning"));
  const explanation=el("details");explanation.dataset.key="error";
  explanation.append(el("summary","Technical details"),el("p",diagnostic,"muted"));
  $("detail-content").append(explanation);
}
async function refreshDetails() {
  const held = detail;
  if (held?.kind !== "result" || detailRead.pending) return;
  const qs = query(held.context),
    d = held.identity;
  qs.set("context_id", d.context_id);
  if (d.read_token) qs.set("read_token", d.read_token);
  qs.set(d.quote_id ? "quote" : "pair", d.quote_id || d.pair_id);
  try {
    const v = await detailRead.read(
      "/api/boards/details?" + qs,
      (x) => checkDetails(x, held.context, d),
      8388608,
    );
    if (!v || detail !== held) return;
    if (v.read_token) { held.identity.read_token = v.read_token; held.selectedToken = v.read_token; }
    held.rendered = true;
    const open = [...$("detail-content").querySelectorAll("details[open]")].map(
        (x, i) => x.dataset.key || String(i),
      ),
      active = document.activeElement,
      activeDisclosure = active?.closest?.("details")?.dataset.key,
      focusedSummary = active?.tagName === "SUMMARY";
    reconcile(v);
    if (v.selection_status === "captured") {
      $("detail-content").prepend(el("p", "Captured result. New inputs are available; this result keeps its original evidence.", "muted"));
      const latest = el("button", "View updated results");
      latest.onclick = () => { closeDetails(); failures=0; pull(); };
      $("detail-content").append(latest);
    }
    for (const [i, x] of [
      ...$("detail-content").querySelectorAll("details"),
    ].entries())
      if (open.includes(x.dataset.key || String(i))) x.open = true;
    if (active === $("close-details")) active.focus({ preventScroll: true });
    else if (focusedSummary && activeDisclosure)
      [...$("detail-content").querySelectorAll("details")].find(x => x.dataset.key === activeDisclosure)?.querySelector("summary")?.focus({ preventScroll: true });
  } catch (e) {
    if (e.name !== "AbortError" && held === detail) {
      detail = {...held, kind:"withdrawn", identity:null};
      detailFailure("Current inputs changed, were removed or are unavailable. Close Details and reopen the current selection.",e.message);
      const reopen = el("button", "Close and load current results");
      reopen.onclick = () => { closeDetails(); failures=0; pull(); };
      $("detail-content").append(reopen);
    }
  }
}
// Selected evidence has its own bounded read lane. A slow/failed whole-slate
// refresh must not let an actively opened selection's cache lease expire.
const selectedTimer = setInterval(() => {
  if (!unloading && detail?.kind === "result") refreshDetails();
}, 10000);
addEventListener("pagehide", () => clearInterval(selectedTimer), { once: true });
function openDetails(row, button, selectedGame) {
  detailRead.cancel();
  originalRead.cancel();
  detail = { kind: "result", context: { ...context(), view:row.pair_id ? "arbs" : "ev", game: selectedGame.game_key }, participants: selectedGame.participants, identity: { ...row.details } };
  $("detail-content").replaceChildren(el("p", "Loading current Details…"));
  showDialog(button);
  refreshDetails();
}
async function openOriginal(q, button, selectedGame) {
  polling.cancel();
  detailRead.cancel();
  originalRead.cancel();
  const selectedBoard = current.boards.find(b => b.game_key === selectedGame.game_key);
  const held = (detail = { kind: "price", context: { ...context(), game: selectedGame.game_key }, participants: selectedGame.participants, quote: q, identity: { ...q.inputs_identity, quote_revision: q.quote_revision, observation_revision: q.observation_revision, policy_revision: selectedBoard?.calculation_context?.policy_revision } });
  const renderFrame = inputs => preserveDisclosures($("detail-content"), () => renderOriginalDetails(
    inputs.evidence?.observation_display ? {...q, observation_display:inputs.evidence.observation_display, source_state:inputs.evidence.source_state, source_health:inputs.evidence.source_health} : q,
    { estimate_availability: selectedBoard?.estimate_availability, ...inputs }, { root: $("detail-content"), participants: selectedGame.participants, title: selectedGame.title }));
  renderFrame({ evidence: { status: "Loading exact-frame contract and source evidence" } });
  showDialog(button);
  try {
    const qs = query(held.context);
    qs.set("context_id", q.inputs_identity.context_id);
    if (q.inputs_identity.read_token) qs.set("read_token", q.inputs_identity.read_token);
    qs.set("quote", q.quote_id);
    const inputs = await originalRead.read(
      "/api/boards/inputs?" + qs,
      x => checkInputs(x, held.context, held.identity),
      8388608,
    );
    if (!inputs || held !== detail) return;
    held.selectedToken = inputs.read_token;
    renderFrame(inputs);
  } catch (e) {
    if (e.name !== "AbortError" && held === detail) {
      renderFrame({ evidence: { status: "Exact current evidence unavailable", reason: e.message } });
      $("detail-content").append(el("p", "Selected observation frame shown with its original clocks. Current evidence changed or is unavailable; close and reopen the price for a new frame.", "warning"));
    }
  }
}
function changeSettings(next) {
  applied = next;
  form();
  persist();
  if (current) draw(current);
  if (detail?.kind === "result") {
    detail.context = { ...detail.context, ...applied };
    detailRead.cancel();
    refreshDetails();
  }
  setStatus("Settings apply when you open selected Details. Shared comparisons keep their displayed defaults.");
}
const settingsDisclosure=document.querySelector(".calculation-settings");
// Close after the outside click has its target. Closing on pointerdown or
// focusout moves the next disclosure before mouseup and swallows that click.
document.addEventListener("click",event=>{
  if (settingsDisclosure.open && !settingsDisclosure.contains(event.target)) settingsDisclosure.open=false;
});
document.addEventListener("keydown",event=>{
  if (event.key==="Escape" && settingsDisclosure.open && !$("details").open) {
    settingsDisclosure.open=false;
    settingsDisclosure.querySelector("summary").focus();
  }
});
$("settings").onsubmit = (e) => {
  e.preventDefault();
  try {
    changeSettings(
      settings(
        $("amount").value.trim(),
        $("buffer").value.trim(),
        $("benchmark").value,
      ),
    );
  } catch (e) {
    setStatus(e.message, "error");
  }
};
$("restore").onclick = () => changeSettings({ ...defaults });
$("search").oninput = () => {
  catalogOptions();
  persist();
  if (current) draw(current);
};
$("game").onchange = () => {
  game = $("game").value;
  persist();
  if (current) draw(current);
};
$("sort").onchange = () => { if (current) draw(current); };
for (const key of ["league", "family", "period", "venue"]) if ($(key)) $(key).onchange = () => {
  const selected = games.find(g => g.game_key === game);
  if (key === "league" && $(key).value && selected && (selected.league || selected.scope?.split("/")[0]) !== $(key).value) game = "";
  catalogOptions(); persist(); if (current) draw(current);
};
for (const b of $("filters").querySelectorAll("button")) {
  b.onclick = () => {
    filter = b.dataset.filter;
    for (const other of $("filters").querySelectorAll("button"))
      other.setAttribute("aria-pressed", String(other === b));
    failures = 0;
    pullGeneration++;
    read.cancel();
    pull();
  };
}
$("retry").onclick = () => {
  failures = 0;
  pull();
};
$("stop").onclick = async () => {
  polling.cancel();
  polling.setSlate(null);
  pullGeneration++;
  read.cancel();
  detailRead.cancel();
  closeDetails();
  polling.cancel();
  stopRequested = true;
  stopped = true;
  $("stop").disabled = true;
  current = null;
  $("content").replaceChildren();
  $("stop").textContent = "Stopping…";
  setStatus("Stopping collection. Positive results are withheld during cleanup.", "busy");
  try {
    const r = await fetch("/api/admin/current", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "stop" }),
    });
    if (!r.ok) throw Error("Stop cleanup unavailable; inspect Admin.");
    failures = 0;
    pull();
  } catch (e) {
    setStatus(e.message, "error");
  }
};
$("title").textContent =
  dashboard ? "Opportunities" : view === "odds" ? "Odds" : view === "ev" ? "Expected value" : "Arbitrage";
if (view === "ev") document.querySelector(".view-help p").textContent = "Expected value estimates the return after modeled costs and one buffer. Conditional estimates cover decisive outcomes only; they remain separate from complete-outcome EV. Open Details for funding, assumptions and original inputs.";
$("filters").hidden = dashboard || view !== "arbs";
$("filters").querySelector("[data-filter=hedges]").hidden = view !== "arbs";
for (const a of document.querySelectorAll("nav a"))
  if (a.getAttribute("href") === location.pathname)
    a.setAttribute("aria-current", "page");
if (dashboard) {
  document.body.classList.add("dashboard-page");
  drawOpportunityDashboard($("content"),dashboardSlates,{},openDetails);
}
if (dashboard || view === "odds" || view === "ev") {
  $("settings").querySelector("strong").textContent = "Details settings";
  $("content").after($("settings"));
  document.querySelector(".settings-body").prepend($("applied"));
}
if (!dashboard && view === "ev") {
  document.body.classList.add("ev-outcome-page");
  const disclosure = el("details", undefined, "ev-filters");
  disclosure.append(el("summary", "Filter games, sources & markets"), document.querySelector(".board-controls"));
  $("content").before(disclosure);
  drawOpportunityDashboard($("content"), {ev:null}, {}, openDetails, ["ev"]);
}
form();
const ageClock = window.setInterval(() => {
  if (unloading || document.hidden) return;
  if (view === "odds" && current && !$("details").open && oddsGroups !== priceGroups(current)) draw(current);
  updateRelativeAges($("content"));
  if ($("details").open) updateRelativeAges($("detail-content"));
}, 1000);
window.addEventListener("pagehide", () => {
  unloading = true;
  window.clearInterval(ageClock);
  polling.cancel();
  pullGeneration++;
  read.cancel();
  detailRead.cancel();
  originalRead.cancel();
});
pull();
