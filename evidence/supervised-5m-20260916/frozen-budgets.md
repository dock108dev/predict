# Five-minute budgets frozen before implementation

Profile: predict-supervised-segmented-5m-v1. Only isolated offline fixtures.
300 seconds including discovery; initial + one refresh at120; active Stop at240;
independent300-second deadline test. Thirty-minute qualification deferred.

The retained active-span arithmetic at2x for300 seconds is45,114 logical rows,
15,039 frames,92.96 MiB encoded and329.41 MiB expanded. Real mean expanded
row8,762 bytes versus tiny mock1,654; real p99=57,325, max457,631 bytes.
Allow refresh68 Kalshi/78 US requests under stable inventory, metadata and churn.

Frozen session ceilings:65,536 logical,65,793 physical (logical+2*128+terminal),
160 MiB encoded ingress,512 MiB expanded ingress,176 MiB physical journals,
520 MiB physical expanded,128 segments. Segments unchanged:1,024 logical
threshold (effective1,023),4 MiB encoded,8 MiB expanded;64 KiB/64 physical
records structural reserve. Single row<=1 MiB encoded and expanded.

Frames24,000 aggregate/20,000 per group; body64 MiB/venue including REST and
pending frame reservations. REST128 attempts/venue,64 per traversal, two
traversals, max two attempts/request, <=2 requests/second/venue and verified
account pacing (unchanged).12 distinct groups,24 connection attempts, two/group,
six concurrent sockets,100 selected/venue,128 events/256 markets per catalog,
256 unique market IDs/venue. Per-second admission ceilings are1024 rows,
256 frames,8 MiB encoded/32 MiB expanded in rolling1s windows. No sampling.

Queue48 retained objects/4 MiB. RSS256 MiB hard,224 MiB intake stop.
Live/replay retained state64 MiB each; diagnostic samples128 per list with
1 MiB aggregate diagnostic ceiling. Snapshot ring60. Exact identity checking
uses4096-UUID sorted chunks, up to16 files/1 MiB disk, no whole-run UUID set.

Output224 MiB:176 journals+16 routine metadata/spool+32 finalization reserve.
Free disk floor1 GiB, with remaining-output reservation. Manifest<=256 KiB,
cumulative write bytes256 MiB (32 MiB finalization reserve). No evidence deletion.
Finalization300 seconds hard; qualification target<=240 seconds. Stop intake<=1s,
task/feed close/drain<=5s. At2x traffic require RSS<=192 MiB, state<=48 MiB,
queue<=24/2 MiB, post-warmup matched-cardinality memory growth<=8 MiB, and
logical/frame/encoded/expanded/output ceilings >=25% spare. Limits are joint.

Experiments: fresh processes, explicit loopback/network and credential guards;
two major lifecycle runs, each<=660 seconds wall/600 CPU seconds,224 MiB
collector output+8 MiB harness output, plus focused suites each<=180 seconds,
256 MiB RSS. All new artifacts<=1 GiB. Retained exactness run<=60 seconds,
64 MiB output. Existing applicable fault tests reused; no real disk exhaustion.
Stop at a required qualification failure; no budget increase/retry to hide it.
Source/evidence preservation hashing uses streamed reads, <=4 GiB original input.
