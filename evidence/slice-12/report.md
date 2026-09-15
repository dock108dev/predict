# Slice 12 verification result

The finite capture → PostgreSQL → query → export → replay workflow is complete.
Next: **Slice 13 — simple live dashboard. Stop before Slice 13.**

- 321 existing offline tests passed.
- 26 separate real PostgreSQL integration tests passed.
- All eleven existing examples and the new storage example passed.
- 96 saved detector/depth audits replayed in the source database, again after
  self-contained bundle restore, and again after PostgreSQL backup restore.
- These are repeated, separately identified verification imports, not 96
  independent candidates or opportunities. Each successful demonstration imports
  one historical and one synthetic session with 24 calculation audits total.
- A corrupted bundle failed and rolled back; a real terminated persistence
  connection left an incomplete session and produced a recovered failure journal.
- Three temporary databases from the final restore run were removed explicitly.
- The dedicated PostgreSQL 14.20 runtime is stopped. Stop/start preserved the
  complete database summary. Data, backup, bundle and local failure journals remain.
- All 547 preexisting implementation/test/evidence files plus the included
  PLAN.md check remain unchanged. Credentials were never read or hashed.

Final stored counts: {"artifact": 434, "artifact_edge": 524, "calculation": 96, "calculation_receipt": 696, "candidate_observation": 176, "capture_session": 13, "coverage_event": 39, "metadata_version": 462, "quote_observation": 59, "receipt": 59}.
Session states: {"complete": 8, "failed": 2, "interrupted": 3, "running": 0}. Earlier failed development
imports and intentional outage sessions are preserved, never relabeled complete.
The final example succeeds; historical production still has zero qualified
opportunities. Conditional positive synthetic calculations remain isolated.

Retention defaults: 1,000 receipts / 60 seconds / 16 MiB per raw or normalized
image / 128 MiB raw receipt input; 32 MiB calculation envelopes. Historical demo
processing declares 300 seconds. No automatic deletion, background service or
live scanner. Bounded full images and compact distinct receipts are retained.
Saved calculations replay; continuous book reconstruction, every exchange event
and opportunity survival across missing intervals are not claimed. Observed
duration remains zero for censored discrete samples.

See [workflow and exact commands](../../docs/slice-12.md),
[checks](verification.json), [restore results](restore-verification.json),
[runtime results](runtime-verification.json), [query](query.json),
[history](candidate-history.json), [bundle](replay-bundle.json),
[PostgreSQL backup](project-postgres.dump), and [hashes](manifest.json).
