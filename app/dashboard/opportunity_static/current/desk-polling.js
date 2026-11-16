// Own the update timer and the single recheck for each expiry boundary.
export function createDeskPolling({state, replay, currentPhase, drawer, expireResultValues,
  receivingUpdates, postedDesk, usingResults, visibleAnchor, load, selections, previousResults}) {
  let updateTimer;
  let updateDelay = 6500;
  let checkedBoundary;
  const RECOVERY_POLL_MS = 2000;

  function scheduleUpdates() {
    if (replay) return;
    clearTimeout(updateTimer);
    const deadline = Date.parse(state.page?.refresh_at) - Date.now();
    const delay = state.loadFailed || state.previousReason || state.page?.last_known_at ? RECOVERY_POLL_MS : updateDelay;
    updateTimer = setTimeout(followUpdates, deadline > 0 ? Math.min(delay, Math.max(deadline, 250)) : delay);
  }

  async function followUpdates() {
    try {
      if (document.hidden) return;
      drawer.expireInspection();
      expireResultValues();
      if (!receivingUpdates()) return;
      if ((state.loadFailed || state.previousReason || state.page?.last_known_at) && !state.request && !usingResults()) {
        await load(state.offset, {background:true, freshMembership:postedDesk(), anchor:visibleAnchor()});
        return;
      }
      if (drawer.isOpen() && !postedDesk()) {
        await drawer.checkSelection();
        return;
      }
      const page = state.page;
      if (!page?.update_cursor || state.request || state.query !== JSON.stringify(selections())) return;
      const expired = Date.parse(page.refresh_at) <= Date.now();
      if (usingResults()) return;
      const query = new URLSearchParams({layout:'desk', phase:currentPhase(), after:page.update_cursor});
      let change;
      try {
        const response = await fetch(`/api/comparison-current/updates?${query}`);
        if (!response.ok) throw Error('Price status unavailable');
        change = await response.json();
      } catch {
        if (state.page === page && !state.request) {
          await load(state.offset, {background:true, freshMembership:postedDesk(), anchor:visibleAnchor()});
        }
        return;
      }
      if (state.page !== page || state.request || !receivingUpdates() || !postedDesk() && drawer.isOpen() || usingResults()) return;
      updateDelay = Math.max(1000, Number(change.poll_after_ms) || 6500);
      const recheckExpiry = expired && checkedBoundary !== page.refresh_at;
      if (change.changed || recheckExpiry || change.phase && change.phase !== currentPhase()) {
        checkedBoundary = page.refresh_at;
        await load(state.offset, {background:true, freshMembership:postedDesk(),
          anchor:postedDesk() && scrollY ? visibleAnchor() : undefined});
      } else if (!expired) {
        previousResults();
        if (postedDesk() && drawer.isOpen()) await drawer.checkSelection();
      }
    } finally {
      scheduleUpdates();
    }
  }

  return scheduleUpdates;
}
