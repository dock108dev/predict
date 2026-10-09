# October 8 venue freshness repair

The owner reported day-old prices after launch. A six-sport refresh now succeeds and all supported aggregate sports are selected for automatic 15-minute checks during 09:00–23:00 America/New_York.

## Repairs

- Replayed the older retained NFL baseline followed by the newly received NFL diagnostic. The update failed with `Quote changed without a coherent revision`: binding evidence changed although the unchanged price fingerprint did not. Aggregate revision fingerprints now cover binding evidence and native association changes.
- Preserve quote times when the price and provider clock are unchanged. Accept an explicit newer provider update clock even for the same price; HTTP receipts alone do not renew freshness. Regressive source clocks remain rejected.
- Check every selected supported aggregate sport rather than excluding inventory-inactive sports. Empty odds responses retire old sport quotes; headers reconcile the actual charge against a reserved worst case.
- Separate optional `aggregate_sports` from native `sports`; omitted/empty aggregate scope inherits native scope for existing configurations. Local owner configuration selects NFL, NCAAF, NBA, NCAAB, MLB and NHL for aggregate checks. Native discovery remains NFL: attempting all sports exceeded Polymarket's existing inventory capacity. Existing resource ceilings are preserved.

## Verification

The retained failing transition now passes in disposable local state. Focused aggregate/service/state/SSOT checks passed (62 tests), including inactive-sport dispatch, zero-credit empty response, stale quote retirement, independent native scope, revision evidence changes and explicit provider-clock behavior. Tests use fictional data; retained replay is historical evidence.

A single owner-directed live six-sport refresh completed at approximately 17:40 Eastern, October 8. All six batches were applied. Provider usage moved from 21 used / 99,979 remaining to 36 used / 99,964 remaining: 15 credits; NCAAB's empty response charged zero. No unresolved charges or ledger pause remained. This manual refresh preserves the scheduled due time (17:45 Eastern). Native Polymarket NFL book images were observed at 17:40; this does not prove broader native coverage. Kalshi had an independent discovery failure at that snapshot. Quote freshness eligibility remains separate from delivery and source timestamps.

Owner acceptance, full native coverage and a probability model remain open. No commit, push, deployment, credential change or accounting reset was performed.
