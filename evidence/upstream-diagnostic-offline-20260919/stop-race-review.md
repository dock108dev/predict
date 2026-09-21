# Stop boundary review after the first major run

The direct major run completed on candidate
`3601a26697b27172d924552f883b0d7800d027e41ef848182174da196d5ee89f`.
No runtime gate failed. Closeout inspection identified a ready-receive race:
the owner may close intake before a previously scheduled recv continuation runs.
Add an explicit post-receive admission guard, retaining raw bytes and an intentional
shutdown rejection without mutating reconstruction, coverage or primary receipt.
Teach the analyzer to distinguish that rejection from a software loss.

Verification: the new focused test injects exactly that ordering. This is a bounded
post-run repair, not another major run or a reset. Preserve the first run's exact
candidate and metrics; do not relabel it as a full timed run of the final revision.
The final revision receives the full focused suite and the second major cutoff run.
No third major run is permitted by this task's envelope.
