# Bounded repair 1

The first launcher suite stopped after five checks. The lock-conflict fixture manually constructed an output under macOS's `/var` temporary alias, while the strict spec correctly requires the resolved `/private/var` path. It failed before testing flock contention. Resolve the disposable fixture root before deriving alternate outputs; keep production canonical-path validation unchanged. Failure log: launcher-1.log. Rerun the fail-fast launcher suite after this fixture-only repair.
