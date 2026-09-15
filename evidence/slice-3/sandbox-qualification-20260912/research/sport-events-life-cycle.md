---
updatedAt: 2026-07-21T17:06:28.000Z
---

Fetch the complete documentation index at: https://docs.prophetx.co/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# Events Life Cycle

Handle Trading API `sport_event` WebSocket updates when events are listed, re-listed, or unlisted.

Handle `sport_event` broadcast updates when an event is listed, re-listed, or unlisted.

## Subscribe to event lifecycle updates

Listen on the `tournament_xxx` broadcast topic for changes to events in that tournament. The message `op` value identifies the change:

| `op` value | Meaning                                                       |
| ---------- | ------------------------------------------------------------- |
| `c`        | Create an event that is listed immediately.                   |
| `u`        | Update an existing event, including listing or re-listing it. |
| `d`        | Delete an event by unlisting it.                              |

## Event lifecycle behavior

| Event state change                       | WebSocket message                            |
| ---------------------------------------- | -------------------------------------------- |
| Event created but not listed             | No message is sent.                          |
| Event created and listed                 | Send a `sport_event` message with `op: "c"`. |
| Event listed or re-listed after creation | Send a `sport_event` message with `op: "u"`. |
| Event unlisted                           | Send a `sport_event` message with `op: "d"`. |

## Event created and listed

The broadcast message uses `change_type: "sport_event"` and `op: "c"`.

```json
{
  "change_type": "sport_event",
  "op": "c",
  "payload": "eyJpZCI6IjE1MDAwOTAxNTAiLCJ0b3VybmFtZW50X2lkIjoiMTYwMDAwMDA3MyIsImluZm8iOnsibmFtZSI6InRlcyBYYW5kZXIgU2NoYXVmZmVsZSB0byBXaW4iLCJkaXNwbGF5X25hbWUiOiIiLCJ0eXBlIjoiY3VzdG9tIiwiZXZlbnRfaWQiOjE1MDAwOTAxNTAsInNwb3J0X25hbWUiOiJHb2xmIiwidG91cm5hbWVudF9uYW1lIjoiVHJhdmVsZXJzIENoYW1waW9uc2hpcCIsInRvdXJuYW1lbnRfaWQiOjE2MDAwMDAwNzMsImNvbXBldGl0b3JzIjpbXSwic3RhdHVzIjoibm90X3N0YXJ0ZWQiLCJzY2hlZHVsZWQiOiIyMDIzLTA2LTI1VDIyOjAwOjAwWiIsInVwZGF0ZWRfYXQiOjE2ODcyNzgwMTkxOTkwNjczNjB9fQ==",
  "timestamp": 1687278019324319700
}
```

Decoded payload:

```json
{
  "id": "1500090150",
  "tournament_id": "1600000073",
  "info": {
    "name": "tes Xander Schauffele to Win",
    "display_name": "",
    "type": "custom",
    "event_id": 1500090150,
    "sport_name": "Golf",
    "tournament_name": "Travelers Championship",
    "tournament_id": 1600000073,
    "competitors": [],
    "status": "not_started",
    "scheduled": "2023-06-25T22:00:00Z",
    "updated_at": 1687278019199067400
  }
}
```

## Event listed or re-listed

After an event exists, listing or re-listing it sends a `sport_event` message with `op: "u"`.

```json
{
  "change_type": "sport_event",
  "op": "u",
  "payload": "eyJpZCI6IjE1MDAwMDAxNDQiLCJ0b3VybmFtZW50X2lkIjoiMTUwMDAwMDA2MCIsImluZm8iOnsibmFtZSI6Ik5vdmEgdGVzdDIiLCJkaXNwbGF5X25hbWUiOiIiLCJ0eXBlIjoiY3VzdG9tIiwiZXZlbnRfaWQiOjE1MDAwMDAxNDQsInNwb3J0X25hbWUiOiJCYXNrZXRiYWxsIiwidG91cm5hbWVudF9uYW1lIjoiVG91cm5hbWVudCBUZXN0IE5vdmExIiwidG91cm5hbWVudF9pZCI6MTUwMDAwMDA2MCwiY29tcGV0aXRvcnMiOlt7ImlkIjoxNjAwMDAwMDUwLCJuYW1lIjoiWWVzIiwiZGlzcGxheV9uYW1lIjoiWWVzIiwiYWJicmV2aWF0aW9uIjoiWWVzIiwic2lkZSI6ImhvbWUifSx7ImlkIjoxNjAwMDAwMDUxLCJuYW1lIjoiTm8iLCJkaXNwbGF5X25hbWUiOiJObyIsImFiYnJldmlhdGlvbiI6Ik5vIiwic2lkZSI6ImF3YXkifV0sInN0YXR1cyI6Im5vdF9zdGFydGVkIiwic2NoZWR1bGVkIjoiMjAyMy0wNC0yNVQxNzo0NjoyNFoiLCJ1cGRhdGVkX2F0IjoxNjg2NzYzMzAxNjY0OTQyNjY5fX0=",
  "timestamp": 1686763301998473000
}
```

Decoded payload:

```json
{
  "id": "1500000144",
  "tournament_id": "1500000060",
  "info": {
    "name": "Nova test2",
    "display_name": "",
    "type": "custom",
    "event_id": 1500000144,
    "sport_name": "Basketball",
    "tournament_name": "Tournament Test Nova1",
    "tournament_id": 1500000060,
    "competitors": [
      {
        "id": 1600000050,
        "name": "Yes",
        "display_name": "Yes",
        "abbreviation": "Yes",
        "side": "home"
      },
      {
        "id": 1600000051,
        "name": "No",
        "display_name": "No",
        "abbreviation": "No",
        "side": "away"
      }
    ],
    "status": "not_started",
    "scheduled": "2023-04-25T17:46:24Z",
    "updated_at": 1686582406275919600
  }
}
```

## Event unlisted

Unlisting an event sends a `sport_event` message with `op: "d"`.

```json
{
  "change_type": "sport_event",
  "op": "d",
  "payload": "eyJpZCI6IjE1MDAwOTAxNTAiLCJ0b3VybmFtZW50X2lkIjoiMTYwMDAwMDA3MyJ9",
  "timestamp": 1687278241642408700
}
```

Decoded payload:

```json
{
  "id": "1500090150",
  "tournament_id": "1600000073"
}
```