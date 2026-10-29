// Bounded cancellable reads and completion-based polling; no response schema policy.
export class LatestRead {
  constructor(fetcher = (...args) => fetch(...args)) {
    this.fetcher = fetcher;
    this.generation = 0;
  }
  get pending() {
    return this.active !== undefined;
  }
  cancel() {
    this.generation++;
    this.controller?.abort();
  }
  async releaseSlate(token) {
    // Release only this client's abandoned traversal, never a displayed frame
    // or a selected Details lease. Failure falls back to the bounded TTL.
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      await this.fetcher('/api/boards/read-lease?read_token=' + encodeURIComponent(token),
        {method:'DELETE', keepalive:true, signal:controller.signal});
    } catch {} finally { clearTimeout(timeout); }
  }
  async read(url, validate, limit = 524288) {
    this.cancel();
    const token = this.generation,
      controller = (this.controller = new AbortController());
    const active = (this.active = { token, controller });
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 30000);
    try {
      const response = await this.fetcher(url, { signal: controller.signal });
      // Read bounded bytes even when the peer omits Content-Length.
      const reader = response.body.getReader();
      let length = 0;
      const chunks = [];
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        length += value.length;
        if (length > limit) {
          await reader.cancel();
          throw Error("Response exceeds its current-data bound.");
        }
        chunks.push(value);
      }
      if (token !== this.generation) return null;
      if (controller.signal.aborted) {
        if (timedOut) throw Error("Current data read timed out. Retry the current view.");
        return null;
      }
      const bytes = new Uint8Array(length);
      let at = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, at);
        at += chunk.length;
      }
      const value = JSON.parse(new TextDecoder().decode(bytes));
      if (!response.ok) {
        const error = Error(value.reason || value.error || "Current data unavailable.");
        error.code = value.error;
        error.reason = value.reason;
        error.status = response.status;
        throw error;
      }
      return validate(value, { bytes: length });
    } catch (error) {
      // User cancellation supersedes the generation. A deadline on the still
      // current request must reach the controller's warning/failure budget.
      if (timedOut && token === this.generation) {
        const timeoutError = Error("Current data read timed out. Retry the current view.");
        timeoutError.code = "current_read_timeout";
        throw timeoutError;
      }
      throw error;
    } finally {
      clearTimeout(timeout);
      if (this.active === active) this.active = undefined;
    }
  }
}

// Schedule the next saved read after completion. A delayed timer cannot start
// overlapping work or resume a modal/closed controller that withdrew reads.
export class SavedReadPoller {
  constructor({ onRead, canRead, setTimer = (callback, delay) => globalThis.setTimeout(callback, delay), clearTimer = timer => globalThis.clearTimeout(timer) }) {
    this.onRead = onRead;
    this.canRead = canRead;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    this.delay = 10000;
    this.generation = 0;
  }
  setSlate(v) {
    this.delay = v && !v.stopped && v.storage?.state !== "unavailable" && v.boards?.some(b => b.delivery_state === "pending") ? 2000 : 10000;
  }
  cancel() {
    this.generation++;
    if (this.timer !== undefined) this.clearTimer(this.timer);
    this.timer = undefined;
  }
  schedule() {
    this.cancel();
    if (!this.canRead()) return;
    const token = this.generation;
    this.timer = this.setTimer(() => {
      this.timer = undefined;
      if (token === this.generation && this.canRead()) this.onRead();
    }, this.delay);
  }
}
