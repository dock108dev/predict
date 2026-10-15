import {
  defaults,
  numeric,
  money,
  percent,
  quantity,
  settings,
  SlateAccumulator,
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
} from "./board-elements.js";
import { createSlateViews } from "./stored-views.js";
import { renderSavedDetails } from "./stored-details.js";

const setStatus = (message, state = "ready") => {
  if ($("status").textContent !== message) $("status").textContent = message;
  $("status").dataset.state = state;
};
const view =
  location.pathname === "/ev"
    ? "ev"
    : location.pathname === "/arbs"
      ? "arbs"
      : "odds";
const read = new LatestRead(),
  detailRead = new LatestRead(),
  originalRead = new LatestRead();
let pullGeneration = 0;
let previousSelection = null;
let applied = { ...defaults },
  games = [],
  game = "",
  filter = view === "odds" ? "all" : "positive",
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
} catch {}
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
}
function preserveContent(draw) {
  const active = document.activeElement,
    key = active?.dataset.key,
    disclosures = [...$("content").querySelectorAll("details[open]")].map(
      (d) => d.dataset.key,
    );
  draw();
  for (const d of $("content").querySelectorAll("details"))
    if (disclosures.includes(d.dataset.key)) d.open = true;
  if (key)
    $("content")
      .querySelectorAll("button[data-key]")
      .forEach((b) => {
        if (b.dataset.key === key) b.focus({ preventScroll: true });
      });
}
function draw(v) {
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
  $("applied").textContent =
    money(applied.amount) +
    " funded · modeled fees included · " +
    percent(String(numeric(applied.buffer) * 100)) +
    " buffer · " +
    venue(applied.benchmark_venue);
  const pending = v.boards.filter(b => b.delivery_state === "pending").length;
  const unavailable = v.storage?.state === "unavailable",
    storageLimit = String(v.storage?.error || "").includes("storage_cap") || (v.storage?.sql_bytes != null && v.storage?.sql_bytes >= v.storage?.sql_byte_cap);
  const storageNote = unavailable ? (storageLimit ? "Saving paused — storage limit reached · " : "Current updates paused · ") : v.storage?.state === "catching_up" ? "Saving new inputs · " : "";
  setStatus((stopped ? "Collection stopped · " : "") + storageNote + v.games.length + " current games · " + (!unavailable && pending ? pending + " calculations pending · " : "") + "Each price and result keeps its own source age", unavailable ? "error" : pending ? "busy" : "ready");
  if (failures) setStatus("Current reads unavailable · prior values have unverified freshness", "error");
  preserveContent(() =>
    renderers.draw(v, {
      view,
      filter,
      game,
      search: $("search").value,
      sort: $("sort").value,
      onShowAll: () => $("filters").querySelector("[data-filter=all]").click(),
    }),
  );
}
function catalogOptions() {
  const search = $("search").value.toLowerCase(),
    visible = games.filter(
      (g) => g.title.toLowerCase().includes(search) || g.game_key === game,
    );
  const signature = JSON.stringify(visible.map((g) => [g.game_key, g.title]));
  if ($("game").dataset.signature === signature) { $("game").value = game; return; }
  $("game").dataset.signature = signature;
  $("game").replaceChildren(
    (() => { const o = el("option", "All games"); o.value = ""; return o; })(),
    ...visible.map((g) => {
      const o = el(
        "option",
        g.title +
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
async function pull() {
  polling.cancel();
  if (failures >= 4) return;
  const c = context(), generation = ++pullGeneration;
  try {
    const qs = query({ ...c, game: "" });
    qs.set("view", c.view);
    qs.set("filter", c.filter);
    qs.set("limit", "50");
    const pages = new SlateAccumulator(c);
    do {
      qs.set("offset", String(pages.nextOffset));
      if (pages.expectedRevision) qs.set("expected_revision", pages.expectedRevision);
      const completed = await read.read("/api/boards/slate?" + qs, (page, metadata) => {
        pages.append(page, metadata.bytes);
        return true;
      }, 8388608);
      if (!completed || generation !== pullGeneration) return;
    } while (!pages.complete);
    const value = pages.result();
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
    $("filters").hidden = view === "odds" || !games.length;
    $("sort-setting").hidden = view === "odds" || !games.length;
    stopped = stopRequested || value.stopped;
    $("stop").disabled = stopped;
    catalogOptions();
    persist();
    if (!games.length) {
      draw(value);
      setStatus("No current games available.");
      return;
    }
    if (game && !games.some((g) => g.game_key === game)) {
      game = "";
      catalogOptions();
      persist();
    }
    failures = 0;
    draw(value);
    $("retry").hidden = true;
    if (detail?.kind === "result") refreshDetails();
  } catch (e) {
    if (e.name === "AbortError" || generation !== pullGeneration) return;
    polling.setSlate(null);
    failures++;
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
    setStatus(
      "Current view unavailable: " +
        e.message +
        (current ? " · Prior view retained; freshness is unverified." : ""),
      "error",
    );
    $("retry").hidden = false;
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
    else $("game").focus();
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
async function refreshDetails() {
  const held = detail;
  if (held?.kind !== "result") return;
  const qs = query(held.context),
    d = held.identity;
  qs.set("context_id", d.context_id);
  qs.set(d.quote_id ? "quote" : "pair", d.quote_id || d.pair_id);
  try {
    const v = await detailRead.read(
      "/api/boards/details?" + qs,
      (x) => checkDetails(x, held.context, d),
      8388608,
    );
    if (!v || detail !== held) return;
    held.rendered = true;
    const open = [...$("detail-content").querySelectorAll("details[open]")].map(
        (x, i) => x.dataset.key || String(i),
      ),
      active = document.activeElement,
      activeDisclosure = active?.closest?.("details")?.dataset.key,
      focusedSummary = active?.tagName === "SUMMARY";
    reconcile(v);
    for (const [i, x] of [
      ...$("detail-content").querySelectorAll("details"),
    ].entries())
      if (open.includes(x.dataset.key || String(i))) x.open = true;
    if (active === $("close-details")) active.focus({ preventScroll: true });
    else if (focusedSummary && activeDisclosure)
      [...$("detail-content").querySelectorAll("details")].find(x => x.dataset.key === activeDisclosure)?.querySelector("summary")?.focus({ preventScroll: true });
  } catch (e) {
    if (e.name !== "AbortError" && held === detail)
      $("detail-content").replaceChildren(
        el("p", "Current inputs changed, were removed or are unavailable. Close Details and reopen the current selection. " + e.message, "warning"),
      );
  }
}
function openDetails(row, button, selectedGame) {
  detailRead.cancel();
  originalRead.cancel();
  detail = { kind: "result", context: { ...context(), game: selectedGame.game_key }, participants: selectedGame.participants, identity: { ...row.details } };
  $("detail-content").replaceChildren(el("p", "Loading current Details…"));
  showDialog(button);
  refreshDetails();
}
async function openOriginal(q, button, selectedGame) {
  polling.cancel();
  const { selection } = labelsFor(selectedGame.participants);
  detailRead.cancel();
  originalRead.cancel();
  const held = (detail = { kind: "price", context: { ...context(), game: selectedGame.game_key }, participants: selectedGame.participants, quote: q, identity: { ...q.inputs_identity, policy_revision: current.policy.revision } });
  $("detail-content").replaceChildren(el("p", "Loading current original contract and source evidence…"));
  showDialog(button);
  try {
    const qs = query(held.context);
    qs.set("context_id", q.inputs_identity.context_id);
    qs.set("quote", q.quote_id);
    const inputs = await originalRead.read(
      "/api/boards/inputs?" + qs,
      x => checkInputs(x, held.context, held.identity),
      8388608,
    );
    if (!inputs || held !== detail) return;
    $("detail-content").replaceChildren(el("h3", selection(q)), el("p", venue(q.venue) + " · " + price(q)));
    textLine($("detail-content"), "Original native price", quantity(q.original.value) + " " + words(q.original.units));
    textLine($("detail-content"), "Original source / receipt", time(q.freshness?.source_at) + " / " + time(q.freshness?.received_at));
    const d = el("details");
    d.append(
      el("summary", "Original contract and source evidence"),
      el("pre", JSON.stringify(inputs.evidence, null, 2)),
    );
    $("detail-content").append(d);
  } catch (e) {
    if (e.name !== "AbortError" && held === detail)
      $("detail-content").replaceChildren(el("p", "Original inputs changed, expired or are unavailable. Reopen the current price. " + e.message, "warning"));
  }
}
function changeSettings(next) {
  applied = next;
  form();
  persist();
  failures = 0;
  pullGeneration++;
  read.cancel();
  closeDetails();
  current = null;
  $("content").replaceChildren();
  setStatus("Loading requested settings…", "busy");
  pull();
}
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
  setStatus("Stopping collection · positive authority withdrawn.", "busy");
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
  view === "odds" ? "Odds" : view === "ev" ? "Expected value" : "Arbitrage";
$("purpose").textContent =
  view === "odds"
    ? "Every current game and its available winner prices, with a separate fair benchmark."
    : view === "ev"
      ? "Compare estimated profit across all games after modeled costs, rule effects and one buffer."
      : "Compare opposing selections across all games, with one shared amount and margins after costs.";
$("filters").hidden = view === "odds";
$("filters").querySelector("[data-filter=hedges]").hidden = view !== "arbs";
for (const a of document.querySelectorAll("nav a"))
  if (a.getAttribute("href") === location.pathname)
    a.setAttribute("aria-current", "page");
form();
window.addEventListener("pagehide", () => {
  unloading = true;
  polling.cancel();
  pullGeneration++;
  read.cancel();
  detailRead.cancel();
  originalRead.cancel();
});
pull();
