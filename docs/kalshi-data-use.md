# Kalshi API data use — corrected personal-trading scope

Updated **2026-09-11**. **Finding: own-trading collection and storage are expressly allowed subject to the agreement's conditions. No project-specific advance permission letter is established as a development prerequisite.** Applying that allowance to this project is an interpretation of published terms and the owner's clarified purpose, not approval from Kalshi.

## Current product intent

This private tool evaluates opportunities to inform the owner's own potential trading on Kalshi and other venues. Historical capture and replay support those personal trading decisions. Beginning read-only does not establish a separate non-trading purpose.

The proposed tool is a personal, noncommercial, locally operated sports moneyline scanner using documented REST and WebSocket interfaces. It would locally retain event metadata, settlement rules, quotes and selected order-book snapshots for cross-venue comparisons and historical replay. No public data distribution, resale, third-party trading service, commercial data product or automated order submission is planned.

## Current official sources

The Developer Agreement, introduction, REST quickstart, WebSocket guide and API-key guide were rechecked for this correction. Other entries retain the earlier September 11 public review. Dates below are document dates, not retrieval dates. Undated sources were reviewed on the date above; search-engine publication estimates are not agreement effective dates.

| Document / direct URL | Entity or publisher | Version / date | Relevant section |
|---|---|---|---|
| [API documentation introduction](https://docs.kalshi.com/welcome) | Kalshi API documentation | Undated, mutable | Opening agreement notice; Predictions APIs |
| [API Developer Agreement landing page](https://kalshi.com/developer-agreement) → [linked PDF](https://assets.kalshi.com/Kalshi-Developer-Agreement.pdf) | KalshiEx LLC | v1.1; no calendar effective date; §1 ties effectiveness to first API use | §§1–5, 6–8 |
| [Kalshi Data Terms of Use](https://kalshi-public-docs.s3.amazonaws.com/kalshi-data-terms-of-service.pdf) | Identifies “Kalshi,” without a full legal entity name | No version/effective date displayed | Opening definition; §§I–IV, pp. 1–3 |
| [Kalshi Member Agreement](https://kalshi.com/docs/kalshi-member-agreement.pdf) | KalshiEX, LLC | v1.6; PDF title identifies June 17, 2026; not independently established as effective date | Opening acceptance; §§I–II, V.B, XII |
| [Quick Start: Market Data](https://docs.kalshi.com/getting_started/quick_start_market_data) | Kalshi API documentation | Undated, mutable | Making Unauthenticated Requests; Next Steps |
| [Quick Start: WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets) | Kalshi API documentation | Undated, mutable | Authentication |
| [API Keys](https://docs.kalshi.com/getting_started/api_keys) | Kalshi API documentation | Undated, mutable | Generating an API Key |
| [Contact Kalshi Support](https://help.kalshi.com/en/articles/13823855-contact-kalshi-support) | Kalshi Help Center | May 20, 2026 | How to reach us; email alternative |

The introduction expressly incorporates the Developer Agreement through a link to the landing page, which links the assets-hosted PDF. The separately indexed [S3 PDF](https://kalshi-public-docs.s3.amazonaws.com/Kalshi-Developer-Agreement.pdf) also displays v1.1; the current official navigation chain is the basis for selecting the assets copy. Website footer branding is not substituted for the agreement's named counterparty.

## Published language versus project interpretation

**Explicit:** §§3–3.1 allow collection, caching, aggregation and storage for a member's own Kalshi trading; sharing with third parties requires prior written authorization. Section 3.5 restricts service monitoring, benchmarking and competitive uses. Sections 1 and 4.1 require membership, agreement acceptance and contact information; API use constitutes acceptance. Sections 2, 4–5 impose security, responsible use, limits and cooperation duties. Section 8 terminates API rights. No numeric retention limit or explicit deletion deadline appears. [Developer Agreement v1.1](https://assets.kalshi.com/Kalshi-Developer-Agreement.pdf).

**Interpretation:** the clarified scanner/replay purpose supports the owner's potential trading. Absence of those implementation names does not establish a separate consent requirement. This is not venue approval or verification of membership, account-specific terms or access eligibility. Post-termination retention and the application of §3.5 to future features remain interpretive questions, not automatic predevelopment approval gates. [Developer Agreement](https://assets.kalshi.com/Kalshi-Developer-Agreement.pdf).

| Use | Current assessment |
|---|---|
| Documented automated collection | Within the own-trading allowance, subject to actual access conditions. |
| Private software | The [market-data quickstart](https://docs.kalshi.com/getting_started/quick_start_market_data) encourages monitoring tools and analysis dashboards. |
| Caching and historical storage | Within the purpose-limited allowance; no perpetual-rights claim. |
| Cross-venue analysis and replay | Project interpretation above applies; no standalone approval requirement established. |
| Third-party sharing | Outside this project; written authorization requirement above applies. |

## Access and applicability distinctions

The [REST quickstart](https://docs.kalshi.com/getting_started/quick_start_market_data) documents unauthenticated access. That is a technical capability, not proof that membership and other applicable conditions are satisfied. [WebSockets](https://docs.kalshi.com/getting_started/quick_start_websockets) require authenticated sessions; [API keys](https://docs.kalshi.com/getting_started/api_keys) are generated within account settings. No account or credentials were inspected and no agreement was accepted in this work.

The [website Data Terms](https://kalshi-public-docs.s3.amazonaws.com/kalshi-data-terms-of-service.pdf) define website content and restrict software/data uses of it. They do not explicitly identify API responses or defer to the Developer Agreement. No express website/API precedence rule was located. These website restrictions cannot automatically be transferred to the separately documented API. Conversely, API access does not license website scraping. Work with wholly synthetic fixtures does not use venue data.

The [Member Agreement](https://kalshi.com/docs/kalshi-member-agreement.pdf) covers membership/services and incorporates exchange and clearing terms. Its §XII data grant is to Kalshi, not to the member. Actual applicable membership, API access and other account conditions remain unverified. This is not a full account or trading qualification.

## Current action and implementation boundary

The earlier mandatory support-inquiry gate is removed. The [optional inquiry](kalshi-data-use-inquiry.md) remains unsent for use if the owner wants clarification or a concrete feature raises an unresolved issue; it is not the next required action.

The owner explicitly authorized Slice 1 using wholly synthetic fixtures. See [implementation and validation](slice-1.md). That work neither requires live venue access nor qualifies it. PLAN.md and Phase 0 captures remain unchanged. Future live collection, account access and later slices require their actual prerequisites and the applicable task authorization, not a blanket Kalshi permission-letter gate.
