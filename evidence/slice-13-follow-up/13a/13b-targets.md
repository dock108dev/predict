# Proposed 13B acceptance envelope — not yet qualified

Freeze the 13A templates and use both two and four markets per venue. Do not
reduce pair count, book depth, side count, burst size or unknown-input coverage
to get a passing result. The measured ordinary full-pipeline capacity falls from
roughly 10 to 4 books/s as pair count grows from four to sixteen, while receipt
work itself is much smaller. That supports reducing repeated full-view/artifact
work before considering a larger bounded queue.

The supported test envelope is one book already in flight followed by **40 books
within 50 ms**, using the existing 13A overflow schedule and 100 ms/receipt
injection to ensure a real in-flight book. This includes 41 book items, 82 side
receipts plus 8/16 bootstrap side receipts. Keep all eight formerly rejected
items and all 32 formerly abandoned items accountable; the repaired supported
case must accept and commit all 41. This is a new engineering target, not a claim
that 13A currently supports the envelope. Re-run the 24-item burst as a smaller
regression: it currently loses 12 accepted items at four markets on Stop.

Also retain ordinary 4 books/s, the 16-book 10 books/s slow-write case (50 ms
per side receipt), disconnect plus quiet interval, and one concurrent on-demand
depth request. Use two repeats at each size, finite inputs capped at 128 book/
control items and 512 receipts, 60 seconds of collection, 128 MiB raw storage,
and a 256 MiB disposable-database guard. These are independent scenario runs,
not an authorization for sustained streaming or a larger combined workload.

Acceptance targets for that candidate:

- Every supported-envelope offer accepted; accepted = processed + explicitly
  unprocessed, with **zero rejected and zero unprocessed** at a clean finish.
  Every book's two side receipts and calculation input bindings must survive
  fresh-connection database readback. Bootstrap, controls and wire units remain
  separate. Preserve unknown upstream quantities.
- Under a no-added-delay 40-book burst, commit receipt work at **at least 8 book
  items/s** averaged from first item worker start to last receipt commit (at least
  16 side observations/s), at both market limits. Report observed view cadence
  separately; do not claim evaluation of every intermediate opportunity.
- Begin with the plan's **250 ms view-refresh target**, measure achieved refresh
  latency and age under load, and account for skipped intermediate evaluations.
  If full view persistence cannot meet the target, record a failed gate rather
  than increasing queue capacity or silently weakening cadence.
- Request Stop with backlog and during depth: producers close within **2 seconds**;
  accepted work, in-flight depth and finalization settle within **10 seconds of
  Stop**. No database work may be presumed cancelled because an await was cancelled.
- Choose and publish finite item and byte limits from this envelope and measured
  object overhead. The baseline queue holds 39,543 serialized bytes at 32 items;
  this is not a heap-size measurement. 13B must also measure retained memory and
  test byte-limit exhaustion. Do not enlarge the queue as the sole repair.
- Beyond the envelope or on database/receipt/byte limit failure, stop within the
  same declared bounds, identify committed subsets and every rejected/unprocessed
  item, preserve the first stop reason, and leave no counter ahead of committed
  state. Final user-facing status agreement is a separate 13C gate.

Prioritize repeated calculation/artifact work, bounded capture transactions,
explicit view cadence, capture priority over depth, and deterministic drain.
Retain audit replay integrity, Decimal values and unknowns. Larger original wire
payloads, complete depth searches, live reconnection, and production throughput
require later separately scoped evidence. None of these repairs were implemented
as part of 13A.
