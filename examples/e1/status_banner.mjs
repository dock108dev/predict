// Scroll Down 087411753d6f4a2665820f84bf6270b08d05ea91:
// web/src/components/layout/DegradedBanner.tsx, status/recovery pattern only.
// Independent local probe, no React, timers, polling or app modification.
// No upstream license found; this is not a vendored or cleared distribution.
import assert from 'node:assert/strict';
export function transition(previous, event) {
  if (event === 'dismiss') return {...previous, dismissed: true};
  if (event === 'recovered') return {degraded: false, dismissed: false};
  if (event === 'degraded') return {degraded: true, dismissed: previous.dismissed};
  throw new Error('unknown status event');
}
export function display(state, mode) {
  if (!['Live', 'Historical', 'Synthetic'].includes(mode)) throw new Error('explicit mode required');
  return {mode, rowStatus: state.degraded ? 'Data delayed' : 'Status reported healthy',
    showBanner: state.degraded && !state.dismissed};
}
let state = transition({degraded: false, dismissed: false}, 'degraded');
assert.equal(display(state, 'Synthetic').showBanner, true);
state = transition(state, 'dismiss');
assert.equal(display(state, 'Synthetic').showBanner, false);
assert.equal(display(state, 'Synthetic').rowStatus, 'Data delayed');
state = transition(transition(state, 'recovered'), 'degraded');
assert.equal(display(state, 'Synthetic').showBanner, true);
assert.equal(display(state, 'Historical').mode, 'Historical');
console.log('PASS: dismiss preserves row status; recovery resets banner; modes stay explicit');
