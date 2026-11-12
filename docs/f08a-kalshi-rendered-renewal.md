# F08A Kalshi rendered schedule renewal

**November 11 status.** The fee formula remains installed. Predict's local
review expired, and the direct official PDF request returned HTTP 429.
The provider's effective date and the app's verification deadline are
separate. The [active fee work](../NEXT_STEPS.md#f08af09--keep-fees-effective-and-make-missing-fees-actionable)
covers reliable verification and standing-term handling.

November 10, 2026 · Integrated on `main` and exercised with fixtures.

The ordinary data owner now renews the Kalshi exchange review after a fresh
official PDF rendering matches the November 10 approval and the exact-market
evidence matches all 18 reviewed series. The reference is the complete
12-page July 7, 2026 schedule as represented by the research renderer.
The check compares the SHA-256 of the entire text after whitespace
normalization. The captured text includes the general and maker terms, worked
tables, non-standard multipliers and other product sections. A change anywhere
in this representation goes to review. The checked-in November 10 terms
continue to supply the fee model when the fresh evidence agrees with them.
[Official PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf) ·
[Reviewed terms](../app/fixtures/kalshi-fees-review-20261110.json)

The worker compares the current type and multiplier for each reviewed series,
the scoped series history, the scoped event overrides from the complete
empty-cursor event listing, and the official rounding document. A successful
check opens a prospective 24-hour review and schedules the next check in six
hours. Retrieval failures preserve the current deadline and retry in 15
minutes. Changed or ambiguous terms require explicit review before another
automatic renewal. Previously captured fees keep their evidence and deadlines.
Admin keeps the direct PDF 429 separate from the renderer, origin and API
receipts. The individual receipts are attached to the verified product revision.
[Series fee changes](https://docs.kalshi.com/api-reference/exchange/get-series-fee-changes) ·
[Event fee changes](https://docs.kalshi.com/api-reference/events/get-event-fee-changes) ·
[Fee rounding](https://docs.kalshi.com/getting_started/fee_rounding)

## Runtime access needed for the live witness

The installed data owner needs outbound HTTPS access to a trusted rendering
endpoint and to Kalshi's API and documentation hosts. The research renderer
used here runs in the research tool. No callable endpoint for it is configured
in the project. The direct PDF and regulatory-page receipts from the ordinary
runtime returned 429. The original session also could not resolve the public Kalshi
hosts from the shell, connect to the installed Admin or PostgreSQL socket, or
inspect or signal the installed processes through the launcher. The existing
processes were left in place in that session. The local follow-up recovered
process access and restarted both ordinary processes. The owner confirmed
that no verified renderer URL is available. The research renderer exposes
no callable endpoint to the worker. Jina Reader documents extracted text
and optional metadata, while the worker requires a request-bound receipt
for the official origin fetch, including the fetched PDF's SHA-256.
The documented Reader API is insufficient for this qualification.
[Jina Reader API reference](https://docs.jina.ai/)

The data owner reads `.local/kalshi-fee-renderer.json` at the next due Kalshi
check. Its only field is `url`, the trusted HTTPS endpoint. The endpoint URL
has no query string, fragment or credentials. The worker sends
`GET <url>?request_id=<random hex>` with `Cache-Control: no-cache`. The endpoint
must fetch the fixed official PDF for that request, verify its source and PDF
format, and render every page using the reviewed extraction and order. It
returns one UTF-8 JSON object with these fields:

| Field | Required value |
| --- | --- |
| `format` | `predict-kalshi-fee-rendering-v1` |
| `request_id` | The exact nonce from this request |
| `source_url` | The final fetch URL, `https://kalshi.com/docs/kalshi-fee-schedule.pdf` |
| `origin_http_status` | The observed official origin status as an integer |
| `origin_retrieved_at` | ISO 8601 with explicit time zone, between request start and response receipt |
| `origin_sha256` | Lowercase SHA-256 of the fetched PDF bytes on an origin 200 |
| `complete` | Boolean true only when the entire PDF was rendered |
| `page_count` | The rendered document's actual page count |
| `text` | Complete extracted text in the reviewed order, without search snippets or an added summary |

The transport requires a current HTTP `Date`, accepts a cache `Age` of at most
five seconds, and permits up to 1 MiB per response. It uses no redirects or
ambient proxy configuration. The full pass is bounded to 50 seconds. The public
API reads are paced at one-second intervals and check the existing source and
global controls before dispatch. The renderer must use synchronized clocks and
fetch the official origin each time. An alternative extractor whose output
differs needs an explicit comparison and approval of its full representation
before use. The retained reference rendering and test log are in
`.local/f08a-kalshi-rendered-20261110/`.

## Renderer implementation

Run `python -m app.collection.kalshi_fee_renderer --port 8787` on the
qualified host with Poppler's `pdftotext` installed. It binds to loopback
and exposes `GET /kalshi-fee-rendering`. Publish that route through a
trusted HTTPS reverse proxy restricted to the data owner's network. Leave
caching disabled and preserve the response Date. The renderer accepts
only a request nonce, fetches the fixed official HTTPS origin, bounds the
request and output, and hashes the original PDF bytes before rendering.
An origin error is a failed receipt and carries no approved text.

The implementation passed a packaged PDF extraction fixture and a
simulated origin 429. This Mac's direct official PDF request also
returned 429. Production still needs a host with legitimate origin
access and a complete Poppler rendering compared against the approved
representation. If the complete normalized text differs, explicitly
review the new representation before enabling automatic renewal.

## Evidence and remaining verification

The fixture ran the ordinary scheduler with HTTP fixtures, passed the resulting
product state through the Admin route, and published a current 50-cent Kalshi
offer through the ordinary desk calculation without a Pinnacle reference. The
conservative fee was **$0.02**. The Admin and offer verification clocks,
deadline and origin evidence matched. The prior direct 429 remained separate.
The same path passed using the captured research rendering and the retained
official API bodies through fixture transport. The captured rendering matched
the runtime fingerprint.
Tests covered transport and freshness failures, changed document, series,
series history, event and rounding terms, incomplete rendering and pagination,
sticky explicit review, and a source pause during the attempt. The fixture
wrote only the Kalshi product row in its disposable store. This pass made zero
production accounting writes or acquisitions.

At 10:13:08 a.m. Eastern on November 10, the installed scheduler reported
`kalshi_renderer_unconfigured`. Admin displayed **Connect the official PDF
renderer**, retained the direct 429 receipt and preserved the manual deadline
of **November 10 at 11:24:42 p.m. Eastern**. The ordinary desk and pinned
drawer verified a $0.01 conservative fee under that manual review. The 10:13:39
a.m. sample covered all 870 current offers, including all 66 Kalshi offers.
All were pregame. It separately counted 8,047 retained unavailable and six
unpublished working prices. The follow-up passed 34 focused checks, with
source controls and all 18 original holds covering 49 credits preserved.
The Admin, drawer and census evidence is under
`.local/f08a-kalshi-rendered-20261110/`.

The last checked Admin status still shows the November 10 manual deadline.
Any manual renewal needs fresh official schedule and exact-market evidence.
Once a qualified runtime route is available, verify the next scheduled
renewal in Admin and match its new verification time and deadline to a
current desk offer.

Review decision: Live Kalshi scheduled renewal | Runtime origin receipt is missing from the available rendering sources | Kept the live witness open and preserved deadline protection.
