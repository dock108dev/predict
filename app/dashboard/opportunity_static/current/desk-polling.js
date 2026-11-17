// Own the update timer and the single recheck for each expiry boundary.
export function createDeskPolling({state, replay, arb, currentPhase, drawer, expireResultValues,
  receivingUpdates, supportsAutoUpdate, usingResults, visibleAnchor, load, selections, unitBoard, previousResults}) {
  let updateTimer;
  let updateDelay = 6500;
  let checkedBoundary;
  const RECOVERY_POLL_MS = 2000;

  function scheduleUpdates() {
    clearTimeout(updateTimer);
    if (replay || unitBoard() && !selections().unit_usd && !state.loadFailed) return;
    const deadline = Date.parse(state.page?.refresh_at) - Date.now();
    const delay = state.loadFailed || state.previousReason || state.page?.replacement_pending
      || state.page?.state === 'valuation_pending' ? RECOVERY_POLL_MS : updateDelay;
    updateTimer = setTimeout(followUpdates, deadline > 0 ? Math.min(delay, Math.max(deadline, 250)) : delay);
  }

  async function followUpdates() {
    try {
      if (document.hidden) return;
      drawer.expireInspection();
      expireResultValues();
      if (!receivingUpdates()) return;
      if ((state.loadFailed || state.previousReason && !unitBoard()) && !state.request && !usingResults()) {
        await load(state.offset, {background:true, freshMembership:supportsAutoUpdate(), anchor:visibleAnchor()});
        return;
      }
      if (drawer.isOpen() && !supportsAutoUpdate()) {
        await drawer.checkSelection();
        return;
      }
      const page = state.page;
      if (!page || state.request || state.query !== JSON.stringify(selections())) return;
      const expired = Date.parse(page.refresh_at) <= Date.now();
      if (usingResults()) return;
      if (unitBoard() || arb && supportsAutoUpdate()) {
        // An explicit withdrawal can arrive independently of the source head.
        await load(state.offset, {background:true, freshMembership:arb, refresh:arb,
          anchor:scrollY ? visibleAnchor() : undefined});
        return;
      }
      if (!page.update_cursor) return;
      const query = new URLSearchParams({layout:'desk', phase:currentPhase(), after:page.update_cursor});
      let change;
      try {
        const response = await fetch(`/api/comparison-current/updates?${query}`);
        if (!response.ok) throw Error('Price status unavailable');
        change = await response.json();
      } catch {
        if (state.page === page && !state.request) {
          await load(state.offset, {background:true, freshMembership:supportsAutoUpdate(), anchor:visibleAnchor()});
        }
        return;
      }
      if (state.page !== page || state.request || !receivingUpdates() || !supportsAutoUpdate() && drawer.isOpen() || usingResults()) return;
      updateDelay = Math.max(1000, Number(change.poll_after_ms) || 6500);
      const recheckExpiry = expired && checkedBoundary !== page.refresh_at;
      if (change.changed || recheckExpiry || change.phase && change.phase !== currentPhase()) {
        checkedBoundary = page.refresh_at;
        await load(state.offset, {background:true, freshMembership:supportsAutoUpdate(),
          anchor:supportsAutoUpdate() && scrollY ? visibleAnchor() : undefined});
      } else if (!expired) {
        previousResults();
        if (supportsAutoUpdate() && drawer.isOpen()) await drawer.checkSelection();
      }
    } finally {
      scheduleUpdates();
    }
  }

  return scheduleUpdates;
}
