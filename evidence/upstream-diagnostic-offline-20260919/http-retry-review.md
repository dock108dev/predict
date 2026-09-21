# HTTP library retry boundary

Post-run inspection of the installed aiohttp client showed `_retry_connection`
defaults true: a disconnected GET may be retried within one counted client call.
Disable that behavior on the diagnostic session only. Discovery retries remain
explicit and charged; references have no retry. An actual loopback endpoint
disconnects without a response, and the regression requires exactly one server
request. This is a dependency seam that must remain regression-tested on upgrades.

No timed run encountered this failure. Both major attempt identities remain
unchanged and consumed; the final revision is verified with focused fixtures.
Do not claim either prior timed run used this final revision.
