# Frozen qualification execution envelope

Source policy and PROFILE are unchanged from supervised-5m-20260916.
Every gate uses a fresh process and exclusive output directory; no allocation snapshots.
Pacing and bounds: 180 s wall/CPU, 256 MiB process ceiling, 8 MiB harness artifacts.
Active and deadline: each 660 s wall / 600 CPU s; collector 192 MiB qualification
RSS, 256 MiB hard ceiling, 224 MiB intake stop, 224 MiB collector output plus
8 MiB harness artifacts. Busy fixture uses actual clocks and 52 frames/s, not
an accelerated timer. Fixture is a separate process: 128 MiB RSS, 120 CPU s,
660 s wall, 2 MiB artifacts, 256 request receipts and 24 connections.
The collector retains owner, native state, journal, incremental replay and the
independent sequence/count checker. No collector-owned state is transferred.
The multiprocessing resource-tracker helper is additional harness overhead;
passive process samples report it separately (expected below 32 MiB). The two
main process high-water marks are reported separately and as their summed upper
bound; helper samples are not an exact helper lifetime peak.
Legacy/history: separate fresh suites, each 180 s wall/CPU and 256 MiB RSS,
224 MiB temporary-output ceiling with 8 MiB retained harness artifacts.
Original replay/math: 60 s wall/CPU, 256 MiB RSS, 64 MiB temporary output,
8 MiB retained harness artifacts. Total new artifacts <=1 GiB.
Network connects are loopback-only and credential loading raises immediately.
Original evidence hashing before/after is streamed, <=4 GiB total original bytes.
Only clearly diagnosed harness defects may be minimally corrected/rerun; an
actual collector/resource/unexplained failure blocks dependent gates.
