---
updatedAt: 2026-09-11T09:07:05.000Z
---

Fetch the complete documentation index at: https://docs.prophetx.co/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# Integration with Websockets

Real-time market data — game lines, halves/quarters/innings, and player/team props — is delivered to Market Maker (MM) partners over WebSockets, powered by **Talaria**, ProphetX's in-house WebSocket platform. This guide covers the full integration: connecting, discovering events, registering subscriptions, and consuming updates.

> Talaria is a wire-protocol-compatible in-house replacement for a third-party hosted WebSocket vendor ProphetX previously used — it speaks the identical wire protocol (same event names, same double-JSON-encoded frames, same channel/auth signing scheme) so existing integrations need, at most, a host repoint. That's why the literal event strings below (`pusher:connection_established`, `pusher:subscribe`, `pusher:signin`, `pusher_internal:subscription_succeeded`, `pusher:error`, and the `"service": "pusher"` field) still read that way — that's the wire protocol's own name, not a vendor reference, and it's unchanged on purpose. Nothing else in this guide targets that vendor: connect to, and think of this entirely as, Talaria.

***

## What you need to do

We're splitting market updates that today all flow through a single shared channel into dedicated channels per event (and per prop type). This keeps your feed focused and scales better as market coverage grows.

| You consume                                                                                                                                                  | Action required                  | Deadline            |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------- | ------------------- |
| **Main markets** (game lines, halves, quarters, innings — this set now also includes `sup_moneyline` and `moneyline_3_way`, not just moneyline/spread/total) | Start to plan your migration now | **August 12, 2026** |
| **Player Props**                                                                                                                                             | Subscribe to the new channels    | **July 29, 2026**   |

**Migrate from** `POST /partner/mm/pusher` **to** `POST /partner/mm/websocket` to get access to the new channel types. The new channels are available in your sandbox environment now — start testing there before the deadlines above.

***

## Before you begin

1. Generate API tokens from the sandbox UI.
2. Exchange your access key and secret key for a session token by calling `POST /auth/login`.
3. Store the `access_token` and send it in the `Authorization` header as `Bearer <access_token>`.

***

## 1. What's changing: the channel model

Today, `market_selections` updates for every event and every market type flow through one shared channel. Going forward, they're split by event and, for props, by market sub-type:

| Channel                                                                 | Pattern                                                                         | Carries                                                                                                                                                                                   |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Main public channel** *(existing — being phased out for market data)* | `private-broadcast-service=6-device_type=5`                                     | Carries main-market updates during the migration window; after **August 12, 2026** it no longer carries `market_selections` at all. (Other message types on this channel are unaffected.) |
| **Event channel** *(new)*                                               | `private-broadcast-service=6-device_type=5-event={event_id}`                    | All main-market updates for one event                                                                                                                                                     |
| **Sub-markets channel** *(new)*                                         | `private-broadcast-service=6-device_type=5-event={event_id}-subtype={sub_type}` | One channel per prop `sub_type`, per event                                                                                                                                                |

Both new channel types publish under the same event name, `market_selections` — the payload schema itself is unchanged, only the routing changes.

***

## What about the old, third-party-hosted service itself?

Separately from the channel migration above, ProphetX is also retiring the legacy externally-hosted service that Talaria replaces. A few things worth knowing:

* **This is already live in sandbox.** Sandbox hands back a `ws_host` today, so if you're connecting there, you're already on Talaria.
* **Production is currently running both in parallel** (dual-publish), with the legacy service still primary — nothing changes for production connections yet.
* **September 16, 2026 is the cutover date.** On that date, we stop using the official Pusher-hosted service entirely and move fully onto Talaria. Nothing you need to do differently in your code because of this — everything in this guide (the wire protocol, the event names, the `service: "pusher"` field) stays the same before and after that cutover, since Talaria will keep speaking this same wire protocol regardless of which service is behind it.

If you're seeing `pusher:connection_established` after connecting to a `ws_host` value, that's expected — see the callout above.

***

## 2. Connecting

**Step 1 — Get your connection config.** Don't hardcode these values — fetch them, since they can change:

```
GET <BASE_URL>/partner/websocket/connection-config
Headers: { "Authorization": "<token>", "Content-Type": "application/json" }
```

Example response:

```json
{
  "app_id": "<app_id>",
  "key": "<app_key>",
  "cluster": "<cluster>",
  "ws_host": "<talaria_host>",
  "service": "pusher"
}
```

* `cluster` is unchanged from before the migration.
* `ws_host` is the new field: when present, connect to it instead of the default Pusher cluster host. It's live in sandbox now. If it's ever absent from the response, fall back to resolving the Pusher cluster host as before — that's the deliberate rollback path on our end, not a bug on yours.
* There's no `ws_port` or `http_host` field — don't build against either.

**Step 2 — Connect to Talaria using that config, and capture your** `socket_id` from the `pusher:connection_established` event:

```json
{
  "event": "pusher:connection_established",
  "data": "{\"socket_id\":\"123.456\"}"
}
```

Note: `data` is a JSON string containing JSON — decode it twice to get `socket_id`.

***

## 3. Discover event and market IDs

Before registering, you need the `event_id` for every event you care about, and — for props — the `sub_type` for every prop market on that event.

| You need | Endpoint                                                  | Field                                          |
| -------- | --------------------------------------------------------- | ---------------------------------------------- |
| Event ID | `GET /partner/mm/get_sport_events?tournament_id={id}`     | `event_id`                                     |
| Sub-type | `GET /partner/v4/mm/get_multiple_markets?event_ids={ids}` | `sub_type` (optional field — read defensively) |

There's currently no endpoint that tells you which `sub_type`s are classified "main" vs. "prop" for a given tournament — that classification is server-side configuration that varies by tournament and can change over time. **Subscribing to the** `event` **channel always gets you every current main market for that event**, regardless of what the underlying list holds at any given time — you don't need to track the main/prop split yourself for that channel.

**Ensure you are using the V4 versions of** `get_markets` **or** `get_multiple_markets` **when searching for** `sub_type`

### Fallback reference: sub-types by tournament (point-in-time snapshot)

If you need a starting point before you can call the endpoints above, here's the current breakdown by tournament. **This will go stale, and the main/prop split can change** — treat it as a reference, not a contract.

<details>
<summary><b>NFL</b> (tournament_id: 31)</summary>

**Main markets:** `1st_quarter_moneyline`, `1st_quarter_spread`, `1st_quarter_total`, `first_half_moneyline`, `first_half_spread`, `first_half_total`, `moneyline`, `spread`, `sup_moneyline`, `to_go_to_overtime`, `total`

**Prop sub-types:** `first_team_to_score`, `player_defensive_interception`, `player_interceptions_thrown`, `player_longest_pass`, `player_longest_reception`, `player_longest_rush`, `player_to_score_first_touchdown`, `player_to_score_last_touchdown`, `player_total_assists`, `player_total_field_goals_made`, `player_total_kicking_points`, `player_total_pass_completions`, `player_total_passing_attempts`, `player_total_passing_rushing_yards`, `player_total_passing_touchdowns`, `player_total_passing_yards`, `player_total_receiving_yards`, `player_total_receptions`, `player_total_rushing_attempts`, `player_total_rushing_receiving_yards`, `player_total_rushing_yards`, `player_total_sacks`, `player_total_tackles`, `player_total_tackles_assists`, `team_total_points`, `to_score_a_touchdown`

</details>

<details>
<summary><b>NBA</b> (tournament_id: 132)</summary>

**Main markets:** `first_half_moneyline`, `first_half_spread`, `first_half_total`, `moneyline`, `spread`, `sup_moneyline`, `total`

**Prop sub-types:** `player_to_record_a_double_double`, `player_to_record_a_triple_double`, `player_total_3_pointers_made_milestones`, `player_total_assists`, `player_total_assists_milestones`, `player_total_blocks`, `player_total_field_goals_attempted`, `player_total_free_throws_made`, `player_total_points`, `player_total_points_assists`, `player_total_points_milestones`, `player_total_points_rebounds`, `player_total_points_rebounds_assists`, `player_total_rebounds`, `player_total_rebounds_assists`, `player_total_rebounds_milestones`, `player_total_steals`, `player_total_steals_blocks`, `player_total_three_pointers_made`, `player_total_turnovers`, `team_total_points`

</details>

<details>
<summary><b>Premier League</b> (tournament_id: 17)</summary>

**Main markets:** `moneyline`, `moneyline_3_way`, `spread`, `sup_moneyline`, `total`

**Prop sub-types:** `both_teams_to_score`, `first_team_to_score`, `player_to_give_assist`, `player_to_have_at_least_1_shot`, `player_to_have_at_least_1_shot_on_target`, `player_to_have_at_least_2_shots`, `player_to_have_at_least_2_shots_on_target`, `player_to_have_at_least_3_shots_on_target`, `player_to_receive_a_card`, `player_to_receive_a_red_card`, `player_to_score_a_goal`, `player_to_score_at_least_2_goals`, `player_to_score_at_least_3_goals`, `player_to_score_or_give_assist`, `player_total_assists_milestones`, `player_total_saves_milestones`, `player_total_shots_milestones`, `player_total_shots_on_target_milestones`, `player_total_tackles_milestones`, `team_clean_sheet`, `total_goal_odd_even`

</details>

<details>
<summary><b>MLB</b> (tournament_id: 109)</summary>

**Main markets:** `1st_5th_inning_moneyline`, `1st_5th_inning_spread`, `1st_5th_inning_total`, `1st_inning_moneyline`, `1st_inning_spread`, `1st_inning_total`, `moneyline`, `spread`, `sup_moneyline`, `total`

**Prop sub-types:** `player_doubles`, `player_hits_allowed`, `player_pitcher_to_record_a_win`, `player_singles`, `player_stolen_bases`, `player_total_bases`, `player_total_batting_strikeouts`, `player_total_earned_runs_allowed`, `player_total_hits`, `player_total_hits_runs_rbis`, `player_total_home_runs`, `player_total_operator_fantasy_points`, `player_total_outs_recorded`, `player_total_pitching_strikeouts`, `player_total_pitching_strikeouts_milestones`, `player_total_rbis`, `player_total_runs`, `player_total_walks`, `player_walks_allowed`, `team_total_runs`

</details>

<details>
<summary><b>UEFA Champions League</b> (tournament_id: 7)</summary>

**Main markets:** `moneyline`, `moneyline_3_way`, `spread`, `sup_moneyline`, `total`

**Prop sub-types:** `both_teams_to_score`, `player_to_give_assist`, `player_to_have_at_least_1_shot`, `player_to_have_at_least_1_shot_on_target`, `player_to_have_at_least_2_shots`, `player_to_have_at_least_2_shots_on_target`, `player_to_have_at_least_3_shots_on_target`, `player_to_receive_a_card`, `player_to_receive_a_red_card`, `player_to_score_a_goal`, `player_to_score_at_least_2_goals`, `player_to_score_at_least_3_goals`, `player_to_score_or_give_assist`, `player_total_assists_milestones`, `player_total_saves_milestones`, `player_total_shots_milestones`, `player_total_shots_on_target_milestones`, `player_total_tackles_milestones`, `team_clean_sheet`, `total_goal_odd_even`

</details>

<details>
<summary><b>MLS</b> (tournament_id: 242)</summary>

**Main markets:** `moneyline`, `moneyline_3_way`, `spread`, `total`

**Prop sub-types:** `both_teams_to_score`, `player_to_give_assist`, `player_to_have_at_least_1_shot`, `player_to_have_at_least_1_shot_on_target`, `player_to_have_at_least_2_shots`, `player_to_have_at_least_2_shots_on_target`, `player_to_have_at_least_3_shots_on_target`, `player_to_score_a_goal`, `player_to_score_at_least_2_goals`, `player_to_score_at_least_3_goals`, `player_to_score_or_give_assist`, `player_total_assists_milestones`, `player_total_saves_milestones`, `player_total_shots_milestones`, `player_total_shots_on_target_milestones`, `player_total_tackles_milestones`, `team_clean_sheet`, `total_goal_odd_even`

</details>

<details>
<summary><b>WNBA</b> (tournament_id: 1600000176)</summary>

**Main markets:** `first_half_moneyline`, `first_half_spread`, `first_half_total`, `moneyline`, `spread`, `sup_moneyline`, `total`

**Prop sub-types:** `player_to_record_a_double_double`, `player_to_record_a_triple_double`, `player_total_3_pointers_made_milestones`, `player_total_assists`, `player_total_assists_milestones`, `player_total_points`, `player_total_points_assists`, `player_total_points_assists_milestones`, `player_total_points_milestones`, `player_total_points_rebounds`, `player_total_points_rebounds_assists`, `player_total_points_rebounds_assists_milestones`, `player_total_points_rebounds_milestones`, `player_total_rebounds`, `player_total_rebounds_assists`, `player_total_rebounds_milestones`, `player_total_three_pointers_made`

</details>

<details>
<summary><b>World Cup</b> (tournament_id: 53)</summary>

**Main markets:** `moneyline`, `moneyline_3_way`, `spread`, `sup_moneyline`, `total`

**Prop sub-types:** `both_teams_to_score`, `player_to_give_assist`, `player_to_have_at_least_1_shot`, `player_to_have_at_least_1_shot_on_target`, `player_to_have_at_least_2_shots`, `player_to_have_at_least_2_shots_on_target`, `player_to_have_at_least_3_shots_on_target`, `player_to_score_a_goal`, `player_to_score_at_least_2_goals`, `player_to_score_at_least_3_goals`, `player_to_score_or_give_assist`, `team_clean_sheet`, `total_goal_odd_even`

</details>

<details>
<summary><b>NCAAB</b> (tournament_id: 648)</summary>

**Main markets:** `first_half_moneyline`, `first_half_spread`, `first_half_total`, `moneyline`, `spread`, `sup_moneyline`, `total`

**Prop sub-types:** `player_total_assists`, `player_total_blocks`, `player_total_points`, `player_total_points_assists`, `player_total_points_rebounds`, `player_total_points_rebounds_assists`, `player_total_rebounds`, `player_total_rebounds_assists`, `player_total_steals`, `player_total_three_pointers_made`, `player_total_turnovers`, `team_total_points`

</details>

<details>
<summary><b>NCAA / NCAAF</b> (tournament_id: 27653)</summary>

**Main markets:** `1st_quarter_moneyline`, `1st_quarter_spread`, `1st_quarter_total`, `first_half_moneyline`, `first_half_spread`, `first_half_total`, `moneyline`, `spread`, `sup_moneyline`, `total`

**Prop sub-types:** `first_team_to_score`, `player_interceptions_thrown`, `player_total_completions`, `player_total_passing_attempts`, `player_total_passing_touchdowns`, `player_total_passing_yards`, `player_total_receiving_yards`, `player_total_receptions`, `player_total_rushing_yards`, `team_total_points`, `to_score_a_touchdown`

</details>

<details>
<summary><b>NHL</b> (tournament_id: 234)</summary>

**Main markets:** `moneyline`, `moneyline_3_way`, `spread`, `sup_moneyline`, `total`

**Prop sub-types:** `first_period_goal_in_first_ten_minutes`, `player_powerplay_points`, `player_to_score_a_goal`, `player_total_assists`, `player_total_blocked_shots`, `player_total_goals_allowed`, `player_total_points`, `player_total_saves`, `player_total_shots_on_goal`, `team_total_goals`

</details>

<details>
<summary><b>UFC</b> (tournament_id: 1500000003)</summary>

**Main markets:** `moneyline`, `sup_moneyline`, `total`

**Prop sub-types:** `fight_to_go_the_distance`, `fighter_to_win_by_any_knockout_submission_dq`, `fighter_to_win_by_decision`, `fighter_to_win_by_knockout_tko`, `fighter_to_win_by_split_or_majority_decision`, `fighter_to_win_by_submission`, `fighter_to_win_by_unanimous_decision`, `fighter_total_significant_strikes_landed`

</details>

<details>
<summary><b>Club World Cup</b> (tournament_id: 36)</summary>

**Main markets:** `moneyline`, `spread`, `total`

**Prop sub-types:** `both_teams_to_score`, `team_clean_sheet`, `total_goal_odd_even`

</details>

<details>
<summary><b>Presidents Cup</b> (tournament_id: 1600000163)</summary>

**Main markets:** `1st_5th_inning_moneyline`, `1st_5th_inning_spread`, `1st_5th_inning_total`, `1st_inning_moneyline`, `1st_inning_spread`, `1st_inning_total`, `moneyline`, `spread`, `sup_moneyline`, `total`

**Prop sub-types:** `team_total_runs`

</details>

<details>
<summary><b>Golf</b> (tournament_id: 1600000234)</summary>

**Main markets:** `1st_round_matchup`, `2nd_round_matchup`, `3rd_round_matchup`, `4th_round_matchup`, `make_the_cut`, `moneyline`, `sup_moneyline`, `tournament_matchup`, `tournament_top_10_finish`, `tournament_top_20_finish`, `tournament_top_5_finish`, `tournament_winner`

**Prop sub-types:** none currently

</details>

<details>
<summary><b>Tennis</b> — 68 ATP/WTA tour events + Grand Slams (M/W draws of Australian Open, French Open, Wimbledon; full ATP/WTA season calendar)</summary>

**Main markets:** `1st_set_moneyline`, `moneyline`, `spread`, `total`, `total_sets`, `sup_moneyline`

**Prop sub-types:** `player_a_to_win_a_set`, `player_b_to_win_a_set`

</details>

***

## 4. Register your subscription

```
POST <BASE_URL>/partner/v4/mm/websocket
Headers: { "Authorization": "<token>", "Content-Type": "application/json" }
```

```json
{
  "socket_id": "1234.5678",
  "service": "pusher",
  "subscriptions": [
    { "type": "event",         "ids": ["18756"] },
    { "type": "event_subtype", "ids": ["18756:player_to_record_a_double_double"] }
  ]
}
```

* `event_subtype` id format is `"{event_id}:{sub_type}"`.
* **The subscription set is declarative.** Every call states your complete desired set of subscriptions — it replaces, not appends to, your previous call.
* `service` defaults to `"pusher"` if omitted — this is the wire protocol's name, not a vendor reference (see the note at the top of this guide), and it stays literally `"pusher"` under Talaria.

### Response

```json
{
  "auth": "<string>",
  "data": {
    "success": true,
    "status": "<string>",
    "updated_at": 1784813285,
    "subscriptions": [
      { "type": "<string>", "ids": ["<string>"] }
    ],
    "authorized_channel": [
      {
        "channel_name": "<string>",
        "auth": "<string>",
        "binding_events": [
          { "name": "<string>", "type": "<string>" }
        ],
        "scope": { "event_id": 0, "sub_type": "<string>" }
      }
    ],
    "channel_count": 0,
    "channel_limit": 0,
    "authenticated": { "auth": "<string>", "user_data": "<string>" }
  }
}
```

`scope` appears **only** on Event channels (`{"event_id": ...}`) and Sub-markets channels (`{"event_id": ..., "sub_type": ...}`) — it's not present on the main public channel or your private user channel.

### Example response (sanitized)

```json
{
  "auth": "<app_key>:<hmac_signature>",
  "data": {
    "success": true,
    "status": "CONNECTED",
    "updated_at": 1784813285,
    "subscriptions": [
      { "type": "tournament", "ids": ["109"] }
    ],
    "authorized_channel": [
      {
        "channel_name": "private-broadcast-service=3-device_type=5",
        "auth": "<app_key>:<hmac_signature_1>",
        "binding_events": [
          { "name": "tournament_109", "type": "tournament" },
          { "name": "general", "type": "general" }
        ]
      },
      {
        "channel_name": "private-service=3-device_type=5-user=<your_account_id>",
        "auth": "<app_key>:<hmac_signature_2>",
        "binding_events": [
          { "name": "wagers", "type": "wagers" },
          { "name": "health_check", "type": "private_system_signal" }
        ]
      },
      {
        "channel_name": "private-broadcast-service=3-device_type=5-event=10078829",
        "auth": "<app_key>:<hmac_signature_3>",
        "binding_events": [ { "name": "market_selections", "type": "market_selections" } ],
        "scope": { "event_id": 10078829 }
      },
      {
        "channel_name": "private-broadcast-service=3-device_type=5-event=10078829-subtype=player_total_hits",
        "auth": "<app_key>:<hmac_signature_4>",
        "binding_events": [ { "name": "market_selections", "type": "market_selections" } ],
        "scope": { "event_id": 10078829, "sub_type": "player_total_hits" }
      }
    ],
    "channel_count": 4,
    "channel_limit": 400,
    "authenticated": {
      "auth": "<app_key>:<hmac_signature_5>",
      "user_data": "{\"id\":\"<your_account_id>\"}"
    }
  }
}
```

**Field notes:**

* `subscriptions` — echoes back what you registered.
* `authorized_channel` — one entry per channel you're authorized on. Use `channel_name` + `auth` to subscribe. `binding_events` tells you which event name(s) to bind on that channel — each has a `name` to bind and a `type` describing the category of payload (`tournament`, `general`, `wagers`, `private_system_signal`, `market_selections`). The main public channel and your private user channel each carry two binding events; Event and Sub-markets channels carry one (`market_selections`).
* `scope` — present on Event/Sub-markets channels only. **Classify incoming messages by** `scope`**, not by channel name.**
* `channel_count` / `channel_limit` — your current usage and cap. Always read `channel_limit` from the response — don't hardcode it, as it can vary by account/tier.
* `authenticated` — `auth` + `user_data` needed to complete the sign-in handshake (next section).
* `rejected` — a partner may see this array if some requested subscriptions couldn't be honored (see [Rejection reasons](#9-rejection-reasons)).
* Each channel's `auth` only works for **that** channel — reusing one channel's `auth` to subscribe to a different channel will fail.

***

## 5. Connecting end-to-end: the full handshake

1. **Get connection config** — `GET /partner/websocket/connection-config` (Section 2)

2. **Connect to Talaria and capture** `socket_id` from `pusher:connection_established` (Section 2)

3. **Discover** `event_id` **/** `sub_type` via REST (Section 3)

4. **Register your subscription** — `POST /partner/v4/mm/websocket` (Section 4)

5. **Sign in**, using the `authenticated` block from the register response:

   ```json
   {
     "event": "pusher:signin",
     "data": {
       "auth": "<app_key>:<hmac_signature>",
       "user_data": "{\"user_id\":\"<your_account_id>\"}"
     }
   }
   ```

6. **Wait for confirmation:**

   ```json
   { "event": "pusher:signin_success", "data": {} }
   ```

7. **Subscribe to each authorized channel**, using that channel's own `auth` + `channel_name` pair from Section 4:

   ```json
   {
     "event": "pusher:subscribe",
     "data": {
       "auth": "<app_key>:<hmac_signature>",
       "channel": "private-broadcast-service=3-device_type=5-event=18756-subtype=first_half_moneyline"
     }
   }
   ```

8. **Wait for confirmation, per channel:**

   ```json
   { "event": "pusher_internal:subscription_succeeded", "data": "{}", "channel": "<channel-name>" }
   ```

9. **Bind** `market_selections` **and consume** (next section).

***

## 6. Consuming events

* Bind `market_selections` on each authorized channel. This applies only to the new Event and Sub-markets channels — if you're already consuming the main public channel today, it doesn't change and needs no re-binding.
* Each channel has its own `auth` string, returned per-entry in `authorized_channel`. Subscribe to a channel using **that channel's own** `auth` — reusing another channel's `auth` will fail.
* Payload shape is unchanged from before the channel split.
* **Classify incoming messages by** `scope`**, not by channel name** — this is the single most important behavior change to get right, since Event and Sub-markets channels all publish under the same event name.

***

## 7. Sub-type canonicalization

Channel names can't contain `-` or `=`, so `sub_type` values are canonicalized on the way in: lowercased; spaces, `/`, and `-` become underscores; anything else is dropped.

| You send                       | Channel carries              |
| ------------------------------ | ---------------------------- |
| `MoneyLine`                    | `moneyline`                  |
| `First Half Total`             | `first_half_total`           |
| `{Player Total/Blocked-Shots}` | `player_total_blocked_shots` |
| `{}` (empty/invalid)           | rejected — `malformed_id`    |

Send whatever your market data gave you as-is; use the canonical value echoed back in `scope.sub_type` as your source of truth for matching.

**Current classification rules:**

* Halves, quarters, and innings are **main markets**, not props — e.g. `first_half_total`, `1st_quarter_spread`, `1st_5th_inning_moneyline` ride the Event channel.
* `sup_moneyline` and `moneyline_3_way` are **main markets**, despite the naming.
* `player_*` and `team_*` are almost always props (the large majority of sub-types), but not exclusively — `both_teams_to_score`, `first_team_to_score`, and `total_goal_odd_even` are props too, without that prefix.
* The main-market list is per-tournament server configuration and can change — don't replicate it client-side. Subscribing to the `event` channel always gets you all current main markets for that event.

***

## 8. Channel capacity planning

* Your channel limit per socket is account-configured. The main public channel and your private user channel don't count against it. **Read** `channel_limit` **from the response every time** — don't hardcode it, and don't assume it's the same across accounts or tiers.
* The limit counts the **cumulative union** of channels for a socket — re-registering with different events keeps consuming headroom, it doesn't reset.
* **Reconnecting resets it** — a new `socket_id` gives you a clean slate.
* Going over the cap rejects the **entire** request, with HTTP 400 and reason `exceed_subscription_count`.
* You get one Sub-markets channel per (event, sub\_type) pair. For example, NFL carries 26 prop sub-types — at a 400-channel limit, roughly 15 concurrent NFL events at full prop coverage (\~390 channels) would approach the cap. Subscribe selectively rather than to every event's full prop set, and size your usage against the actual `channel_limit` your account gets back.

***

## 9. Rejection reasons

| Reason                 | Cause                                                                   |
| ---------------------- | ----------------------------------------------------------------------- |
| `wildcard_not_allowed` | `ids: ["all"]` — name each event explicitly instead                     |
| `malformed_id`         | Non-numeric event id, or missing `:` separator in an `event_subtype` id |
| `unknown_type`         | Unrecognized `type` value                                               |

***

## 10. Keep-alive & error handling

* ProphetX actively sends a `health_check` message so you can confirm reachability — this is separate from Talaria's own connection ping.
* Respond to the transport's own ping/pong: protocol v5+ requires responding to every `pusher:ping` with `pusher:pong`; later protocol versions can rely on default WebSocket ping handling.
* Transport-level errors arrive as `pusher:error`.

***

## 11. Migration checklist

* [ ] Fetch `event_id`, then `sub_type` per market (Section 3) — don't hardcode the snapshot tables, and don't assume a static main/prop rule
* [ ] Send `event` / `event_subtype` entries in `subscriptions[]`, as a complete set on every call (Section 4)
* [ ] Classify messages by `scope`, not channel name or event name (Sections 4 & 6)
* [ ] Bind `market_selections` on every authorized channel (Section 6)
* [ ] Handle `rejected[]` and HTTP 400 `exceed_subscription_count` (Sections 8 & 9)
* [ ] Re-send the complete subscription set on every register call — don't append (Section 4)
* [ ] Migrate props before **July 29, 2026**; migrate main markets before **August 12, 2026**
* [ ] Handle the transport's ping/pong and the ProphetX `health_check` message separately (Section 10)