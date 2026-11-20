# Monitor clock and near-start priority

The owner requested 30-minute Monitor starts at :20 and :50 to improve the scan
window before games starting on the hour or half-hour. The default is now an
1800-second interval anchored to a 1200-second clock phase. Legacy settings gain
that optional phase on read; no source-database migration or owner-setting reset
is needed. The offset is configurable in Collection settings, which shows the
server's next scheduled target in Eastern time.

Persisted run progress includes monitor_slot_at. A restart within a short boundary
grace can claim that slot once; older missed startup slots are skipped to avoid a
catch-up burst immediately before the next anchor. Normal active overruns and
budget delays coalesce one latest overdue slot, then return to the fixed clock.
Changing timing keeps active work running. Changing the authorized horizon still
uses the existing scope-revocation behavior. Stop, source pauses, Live inactivity,
reservation/hold and account/object budgets remain authoritative.

A read-only audit found the existing startup loader already seeds retained events;
71 were within the 24-hour horizon and 14 within the next hour at that snapshot.
Those near-start known events now receive full alternate refreshes in kickoff order
before bulk league traversal. New discovery still runs, and remaining future full
alternate refreshes follow in kickoff order. An already refreshed event is not
fetched again during that round. No unsupported provider sort parameter or extra
catalog/acquisition request was added.

A completed production round took 18m26s, so :20/:50 are scheduled start times,
not a claim that all quotes arrive simultaneously or every round completes before
kickoff. Near-start priority addresses that practical ordering constraint.

Verification: 19 controlled unit tests, four disposable PostgreSQL tests and ten
Settings browser cases passed. Coverage includes exact boundaries, both DST
transitions, restarts, overrun coalescing, timing edits during active work, nearby
priority, duplicate refresh prevention, guard/fairness behavior, legacy settings,
zero offset, owner-only controls and fixed Save/Close behavior. The installed next
slot provides deployment proof; no separate half-hour observation window is a
completion requirement. The original sprint request independently requires hosted
checks and deployment to be monitored to completion.
