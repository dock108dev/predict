> ## Documentation Index
> Fetch the complete documentation index at: https://docs.novig.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Rate Limits & URL's

> HTTP REST API for order management and market data

**PROD URL:** `https://api.novig.com/nbx/v2`

**QA URL:** `https://api-qa.novig.us/nbx/v2`

## Rate Limits

| Endpoint                                                             | Interval                   | Limit                    |
| -------------------------------------------------------------------- | -------------------------- | ------------------------ |
| `emm/orders/place` (Order Placement)                                 | 1 s                        | 64                       |
| `emm/orders/batch` (Batch Order Placement)                           | 1 s                        | 64                       |
| `emm/orders/{orderId}` (Order cancellation)                          | 1 s                        | 512                      |
| `emm/kill` (Kill switch)                                             | 30 s                       | 1                        |
| `emm/fills/all`, `emm/orders/all`, `emm/transactions` (User history) | 1 s burst / 60 s sustained | 32 burst / 512 sustained |
| All Others                                                           | 1 s                        | 256                      |

User history endpoints (`/fills`, `/orders`, `/transactions`) also support a maximum `limit` of **256 items per request** (default 100).

### Rate limit responses

When a limit is exceeded the API responds with **HTTP `429 Too Many Requests`**. Every response (both `2xx` and `429`) carries rate-limit headers:

| Header                  | Meaning                                         |
| ----------------------- | ----------------------------------------------- |
| `X-RateLimit-Limit`     | Max requests allowed in the current window      |
| `X-RateLimit-Remaining` | Requests remaining in the current window        |
| `X-RateLimit-Reset`     | Time until the current window resets            |
| `Retry-After`           | Time to wait before retrying (present on `429`) |

<Warning>
  `Retry-After` and `X-RateLimit-Reset` are reported in **milliseconds**, not seconds. A value of `73` means wait **73 ms**, not 73 seconds. Do not feed these values into helpers that assume the HTTP-standard seconds unit.
</Warning>

Endpoints with a two-tier `burst` + `sustained` policy (the user-history endpoints) emit a separate set of headers per tier, suffixed with the tier name — e.g. `X-RateLimit-Remaining-burst` and `X-RateLimit-Remaining-sustained`. Honor whichever tier is closest to its limit.

We recommend retrying on `429` after the `Retry-After` delay with exponential backoff.

**Timeout:** 5 seconds

## Features

* Place, cancel, and query orders
* Retrieve market data and positions
