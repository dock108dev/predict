# Audit comparator repair

The new post-run audit stopped on exact dictionary equality. Inspection showed the
only difference was replay retained-object memory telemetry: 52,659 versus 52,859
bytes in separate Python processes. All classifications, inputs, native hashes,
lineage and counts were identical. Compare all deterministic evidence fields
exactly; independently require both memory measurements below 48 MiB. This fixes
an invalid process-dependent equality assertion without relaxing a resource cap
or conclusion rule. Failed audit log retained. No capture rerun or extra major
experiment is started by this repair; the already-running independent cutoff
experiment has not encountered a collector or resource failure.
