---
updatedAt: 2026-09-10T15:58:27.000Z
---

Fetch the complete documentation index at: https://docs.prophetx.co/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# Bones for Building a Bot

Build a sandbox trading bot that authenticates with the API, retrieves market data, submits orders, and runs scheduled automation safely.

Build a sandbox trading bot that authenticates with the API, retrieves market data, submits orders, and runs scheduled automation safely.

Use the current Trading API endpoint paths in your integration. Your local code can retain implementation-specific identifiers such as `sport_events`, but use the documented API terms in developer-facing logs, interfaces, and documentation.

<Callout icon="exclamation-triangle" theme="warning">
  You are responsible for the behavior of your bot. Test only in the sandbox environment, and do not use production credentials or production endpoints during development.
</Callout>

## Goals

* Authenticate with the API
* Seed markets, events, and prices
* Submit and cancel orders
* Maintain sessions and WebSocket connections
* Run scheduled automated logic (strategy)
* Log activity, test behavior, and enforce sandbox safety checks

## Prerequisites

Use Python for the examples in this guide. You can adapt the same workflow to another language if needed.

1. Install Python 3.8 or later.
2. Install the recommended packages:

```bash
pip install requests pysher schedule pytz
```

3. Get sandbox credentials and confirm you are using a sandbox API endpoint.

## Project layout

* src/main.py — entry point for startup and scheduling
* src/mm\_calls.py — core MMInteractions class for authentication, seeding, order submission, order cancellation, and WebSocket handling
* src/config.py — endpoints, keys loader
* src/user\_info.json — user keys & preferences (create locally)
* src/log.py, src/constants.py — logging and constants used by the bot

## Configuration

1. Create `src/user_info.json`:

```json
{
  "access_key": "YOUR_ACCESS_KEY",
  "secret_key": "YOUR_SECRET_KEY",
  "tournaments": [123],
  "load_all_tournaments": false
}
```

2. Ensure `BASE_URL` in your config points to the sandbox URL: <https://api.sandbox.prophetx.dev/>

## Implementation outline

1. Authentication
   * Call `POST /auth/login` with `access_key` and `secret_key`.
   * Store the `access_token` and a `requests.Session` for headers and cookies.
   * Refresh the session with `POST /auth/refresh`, or authenticate again if refresh fails.

2. Seed data
   * Call `GET /mm/get_price_ladder`, `GET /mm/get_tournaments`, `GET /mm/get_sport_events`, and `GET /mm/get_markets` or `GET /mm/get_multiple_markets`.
   * Build in-memory structures such as `valid_prices`, `all_tournaments`, and an event cache. Your local code may still name that cache `sport_events`.
   * Validate that each market includes the required `strike_id` before you submit an order.

3. Balance
   * Call `GET /mm/get_balance` to fetch and store the available balance.
   * Check the available balance before submitting orders.

4. Submit and cancel orders
   * Submit orders with `POST /mm/submit_order` or `POST /mm/submit_multiple_orders`.
   * Cancel orders with `POST /mm/cancel_order` or `POST /mm/cancel_multiple_orders`.
   * Maintain a mapping of `external_id` to `order_id` for cancellations.

5. WebSocket subscription (optional but highly recommended)
   * Call `GET /websocket/connection-config`, then call `POST /mm/pusher` with the connected socket ID to retrieve signed channels.
   * Use pysher (or websocket-client) to subscribe and update local state on events.
   * Bind public and private handlers to process market updates and order confirmations.

6. Scheduling & automation
   * Use `schedule` to run periodic tasks:
     * seed every 30 minutes
     * run `start_ordering` every N seconds with a small sandbox interval during testing
     * cancel random orders or batch cancellations
     * refresh the session every few minutes
   * Run schedule in a background thread.

7. Strategy & risk
   * Start with a deterministic test strategy, not real money. For example, submit fixed small orders at random valid prices.
   * Implement quantity sizing, maximum exposure, and per-tournament limits.
   * Add price filters to avoid thin markets.
   * Never point to production endpoints or use production keys during development. Assert that `BASE_URL` contains `sandbox` before submitting orders.

8. Resilience & safety
   * Add retry/backoff for transient network errors.
   * Rate-limit requests to respect API constraints.
   * Validate API responses and handle malformed responses.
   * Add logging and error alerts.

## Testing

* Use sandbox/test accounts only.
* Add unit tests for:
  * auth flow (mock responses)
  * seeding/parsing market data
  * order submission and cancellation logic (mock API)
* Run `python3 src/main.py` in staging and review the bot behavior, logs, and API calls.

## Deployment & monitoring

* Run in a contained environment (VM or container).
* Use process manager (systemd, supervisord) or Docker to restart on failures.
* Monitor logs, balance changes, and submitted orders.
* Set alerts for failed refreshes, repeated API errors, or unusually large orders.

## Extending the bot

* Replace randomized orders with a strategy module:
  * create `src/strategy.py` with a class that returns candidate orders
  * integrate the strategy into `start_ordering()`
* Add persistence (sqlite/postgres) for order history and state.
* Add metrics (Prometheus) and dashboards.

## Minimal run example

From repo root:

```bash
cd sandbox-bot/mm-trading-bot
python3 src/main.py
```

## Safety checklist before running

* [ ] Use sandbox credentials
* [ ] Confirm `BASE_URL` points to the sandbox environment
* [ ] Start with extremely small order sizes
* [ ] Ensure logging is enabled
* [ ] Understand scheduled intervals

## Useful TODOs

* Implement unit tests for mm\_calls methods
* Add Dockerfile for sandboxed runs
* Add an integration test that mocks API endpoints