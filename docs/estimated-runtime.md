# Compatibility current-state runtime

Ordinary comparison calculations use current SQL rows and transient reads,
as described in [architecture](architecture.md). This guide covers the separate
current-state provider, which supports
injected fixtures, retained admission, complete snapshot reads and temporary
policy calculations through the same router. Its admission generations and
temporary resources are separate from the ordinary board's v2 context IDs.
It is not a database-failure fallback.

## Admission and publication

Strict complete source commits acknowledge only successful complete installation.
An opt-in retained provider can admit owned inputs cooperatively: one active job
and one latest pending descriptor, no unbounded queue. It first exposes validated
original numerical prices through `/api/current/prices`; financial results remain
withheld until the complete generation is admitted.

Candidate generation binds input content, runtime, policy and admission attempt;
it is separate from committed epoch/revision. Pending, rejected, superseded and
stopped work advertises no committed identity. Success atomically installs the
state, indexes and deadlines; rejection preserves the previous complete state.
Original native identities, units, transformations and clocks pass strict validation.
Opaque outcomes distinguish success, rejection, supersession and Stop rather than
relying on boolean coercion.

Source reducers retain synchronous commit ownership. A queued receipt is not an
acknowledgement. Harmless age updates do not restart calculations; a real economic
boundary closes the iterator and supersedes the future. Rebases preserve original
source clocks and share the initial 300-second lease, with at most four rebases.
Stop revokes publication before iterator and resource cleanup.

## Reads and transport

Price transport owns at most 16,000 rows and a 64 MiB input/row graph. Pages carry
one row with a 256 KiB limit; sixteen readers have ten-second leases. Unknown totals
remain null. Rows preserve exact numerical values, native IDs, units and original
source/receipt/projection clocks. No financial number is implied by price progress.
See the [price contract](contracts/predict-retained-prices-1.md).

Complete Current/Comparison bodies remain coherent captured JSON. Large bodies
write in 64 KiB blocks with backpressure. Encoded responses have bounded file,
byte, cache and reader pools: four files, sixteen readers, a 30-second cache and
300-second reader leases. EOF, disconnect, supersession, expiry and Stop release
owned resources. Temporary policy calculations use one active/latest-pending job;
settings changes cancel the old reader before requesting the latest variant.

Selected Details reconstructs its exact economic group and expands only the
selected quote/pair, retaining both leg identities. Runtime, revision, selection
and settings mismatches reject rather than substitute data. Browser code validates
echoed context and withholds delayed responses.

## Limits and testing

These bounds do not guarantee full-slate response latency or browser paint time.
Synchronous admission and encoding can block the event loop. Listener readiness,
complete HTTP receipt, financial readiness and DOM paint are different measurements.
Use focused admission, deadline, encoded-body, temporal and cancellation tests
listed in `scripts/ci/suites.json`. Explicit sustained harnesses under `tests/`
are optional workload tools, not app setup instructions. Use disposable authored
inputs and never infer fresh provider coverage from a synthetic or retained run.
