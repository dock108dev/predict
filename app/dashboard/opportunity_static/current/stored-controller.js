import {
  defaults,
  numeric,
  money,
  percent,
  quantity,
  settings,
  checkSlate,
  checkDetails,
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
  originalRead = new LatestRead(),
  historyRead = new LatestRead();
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
  const storageNote = unavailable ? (storageLimit ? "Saving paused — storage limit reached · " : "Saved updates paused · ") : v.storage?.state === "catching_up" ? "Saving new inputs · " : "";
  setStatus((stopped ? "Collection stopped · " : "") + storageNote + v.games.length + " saved games · " + (!unavailable && pending ? pending + " calculations pending · " : "") + "Each price and result keeps its own source age", unavailable ? "error" : pending ? "busy" : "ready");
  if (failures) setStatus("Saved reads unavailable · retained values have unverified freshness", "error");
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
  const c = context();
  try {
    const qs = query({ ...c, game: "" });
    qs.set("view", c.view);
    qs.set("filter", c.filter);
    const value = await read.read("/api/boards/slate?" + qs, v => checkSlate(v, c), 8388608);
    if (!value) return;
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
      setStatus("No saved NFL winner games available.");
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
    if (e.name === "AbortError") return;
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
          "Positive results withheld while saved reads are unavailable.",
          "notice",
        ),
      );
    setStatus(
      "Saved view unavailable: " +
        e.message +
        (current ? " · Prior view retained; freshness is unverified." : ""),
      "error",
    );
    $("retry").hidden = false;
  } finally {
    if (!read.pending) polling.schedule();
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
  historyRead.cancel();
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
$("details").addEventListener("cancel", (e) => {
  e.preventDefault();
  closeDetails();
});
function reconcile(v) {
  const { advanced, history } = renderSavedDetails(v, {
    root: $("detail-content"),
    participants: detail.participants,
  });
  const load = el("button", "Load original input envelopes");
  load.onclick = async () => {
    const held = detail;
    try {
      const qs = query(held.context);
      qs.set("result_id", held.identity.result_id);
      const inputs = await originalRead.read(
        "/api/boards/inputs?" + qs,
        (x) => {
          if (
            x.version !== "predict-board-inputs-1" ||
            x.inputs?.input_version !== v.original_inputs_identity.input_version
          )
            throw Error("Original input identity crossed.");
          return x;
        },
        8388608,
      );
      if (inputs && held === detail)
        advanced.append(el("pre", JSON.stringify(inputs, null, 2)));
    } catch (e) {
      if (e.name !== "AbortError") load.textContent = e.message;
    }
  };
  advanced.append(load);
  history.addEventListener("toggle", async () => {
    if (!history.open || history.dataset.loaded) return;
    const held = detail;
    try {
      const x = await historyRead.read(
        "/api/boards/history?" + query(held.context),
        (x) => {
          if (
            x.version !== "predict-board-history-1" ||
            x.game_key !== held.context.game ||
            x.policy_revision !== held.identity.policy_revision
          )
            throw Error("History identity crossed.");
          return x;
        },
      );
      if (!x || held !== detail) return;
      history.dataset.loaded = "true";
      for (const entry of x.results) {
        const b = el("button", "Open " + time(entry.calculated_at));
        b.onclick = () => {
          detail = {
            ...held,
            rendered: false,
            identity: {
              ...held.identity,
              result_id: entry.result_id,
              snapshot_id: entry.snapshot_id,
            },
          };
          refreshDetails();
        };
        history.append(b);
      }
      if (!x.results.length)
        history.append(el("p", "No saved history for these settings."));
    } catch (e) {
      history.append(el("p", e.message));
    }
  });
}
async function refreshDetails() {
  const held = detail;
  if (held?.kind !== "result") return;
  const qs = query(held.context),
    d = held.identity;
  qs.set("result_id", d.result_id);
  qs.set(d.quote_id ? "quote" : "pair", d.quote_id || d.pair_id);
  try {
    const v = await detailRead.read(
      "/api/boards/details?" + qs,
      (x) => checkDetails(x, held.context, d),
      8388608,
    );
    if (!v || detail !== held) return;
    if (held.rendered) {
      const age = $("detail-freshness");
      age.replaceChildren();
      freshness(
        age,
        (v.pair || v.quote.calculations.funded_estimate).freshness,
      );
      return;
    }
    held.rendered = true;
    const open = [...$("detail-content").querySelectorAll("details[open]")].map(
        (x, i) => x.dataset.key || String(i),
      ),
      active = document.activeElement;
    reconcile(v);
    for (const [i, x] of [
      ...$("detail-content").querySelectorAll("details"),
    ].entries())
      if (open.includes(x.dataset.key || String(i))) x.open = true;
    if (active === $("close-details")) active.focus({ preventScroll: true });
  } catch (e) {
    if (e.name !== "AbortError" && held === detail)
      $("detail-content").prepend(
        el("p", "Details unavailable: " + e.message, "warning"),
      );
  }
}
function openDetails(row, button, selectedGame) {
  detailRead.cancel();
  originalRead.cancel();
  historyRead.cancel();
  detail = { kind: "result", context: { ...context(), game: selectedGame.game_key }, participants: selectedGame.participants, identity: { ...row.details } };
  $("detail-content").replaceChildren(el("p", "Loading exact saved Details…"));
  showDialog(button);
  refreshDetails();
}
async function openOriginal(q, button, selectedGame) {
  polling.cancel();
  const { selection } = labelsFor(selectedGame.participants);
  detailRead.cancel();
  originalRead.cancel();
  historyRead.cancel();
  const held = (detail = { kind: "price", context: { ...context(), game: selectedGame.game_key }, participants: selectedGame.participants, quote: q });
  $("detail-content").replaceChildren(
    el("h3", selection(q)),
    el("p", venue(q.venue) + " · " + price(q)),
  );
  textLine(
    $("detail-content"),
    "Original native price",
    quantity(q.original.value) + " " + words(q.original.units),
  );
  freshness($("detail-content"), q.freshness);
  showDialog(button);
  try {
    const inputs = await originalRead.read(
      "/api/boards/inputs?" + query(held.context),
      (x) => {
        if (
          x.version !== "predict-board-inputs-1" ||
          x.inputs?.input_version !== q.inputs_identity.input_version ||
          x.inputs.game_key !== q.inputs_identity.game_key
        )
          throw Error("Original price changed; reopen its current identity.");
        return x;
      },
      8388608,
    );
    if (!inputs || held !== detail) return;
    const d = el("details");
    d.append(
      el("summary", "Original contract and source evidence"),
      el("pre", JSON.stringify(inputs, null, 2)),
    );
    $("detail-content").append(d);
  } catch (e) {
    if (e.name !== "AbortError")
      $("detail-content").append(el("p", e.message, "warning"));
  }
}
function changeSettings(next) {
  applied = next;
  form();
  persist();
  failures = 0;
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
  read.cancel();
  detailRead.cancel();
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
    ? "Every saved game and its available winner prices, with a separate fair benchmark."
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
  read.cancel();
  detailRead.cancel();
  originalRead.cancel();
  historyRead.cancel();
});
pull();
