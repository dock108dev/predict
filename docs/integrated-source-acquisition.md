# Integrated source-evidence acquisition

**Current state:** revision 3 was explicitly authorized and consumed. It charged 34 credits (39 reserved), completed one aggregate cycle, and stopped on an unsupported native listing's null-schedule processing defect. Both native sources also hit their response caps without retry. [Live closeout](../evidence/integrated-acquisition-r3-20260930/LIVE-RESULT.md) and [versioned local repairs](../evidence/integrated-r3-derived-20260930-v1/README.md) govern next steps. The key is now persisted locally in ignored owner-only `.env`. No further collection is authorized; the implementation has changed, and native payload policy still needs redesign before a fresh candidate. The preparation description below is historical.

[Revision 3](../evidence/integrated-acquisition-r3-20260930/README.md) is the current offline repair candidate. Revision 2's original package and consumed live attempt remain preserved. That attempt charged 15 credits, reserved 18, and stopped after US catalog truncation; it did not complete six-sport acquisition.

Revision 3 keeps the six-sport/63-cell objective and 180-second ordinary Start. US event pages shrink from 50 to two, with up to 75 pages retaining 150 listing slots per generation. The response cap remains 256 KiB; oversized-source admission/work stops without retry while healthy peers continue. Shared persistence, memory and storage failures still stop globally. Pagination exhaustion and missing coverage remain explicit.

Worst-case bounds are 37 aggregate requests / 135 credits, 58 Kalshi and 486 US HTTP attempts, and 12 total WebSocket attempts: 581 HTTP / 593 establishments. Existing byte, time, concurrency, 128 MiB session storage and 4 KiB metadata caps remain. These are conservative ceilings, not guaranteed attainable coverage. No recovery replenishes quota.

The retained NFL/NCAAF/NBA observations support two source-scoped NCAAF aliases and verify existing returned-market bindings. They do not qualify native crosswalks, repeated updates, missing economics or championship facts. Current real credential is not persisted; only dummy handoff tests were performed. The new candidate/destination is unapproved and unused. See the package for exact identities, focused verification, prerequisites and authorization wording.

Focused verification and original-evidence preservation are recorded in the revision 3 package. The six-sport scope is also explicit in native inventory metadata; no default NFL label substitutes for the approved open-catalog scope.
