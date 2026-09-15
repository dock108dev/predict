> ## Documentation Index
> Fetch the complete documentation index at: https://docs.novig.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Heartbeat & Connection Management

> Keep WebSocket connections alive and handle reconnection

## Heartbeat Mechanism

Keepalive is handled entirely at the **WebSocket protocol layer** (RFC 6455 control frames), not with JSON messages.

### Server Ping

The server sends a protocol-level **Ping frame every 15 seconds**. Conformant WebSocket clients (browsers, `ws`, `websockets`, tungstenite, etc.) automatically reply with a protocol Pong frame — you don't write any code for this.

<Warning>A client that misses a full 15-second interval without a protocol Pong is **disconnected**.</Warning>

### No application-level ping/pong

There is **no** `{"event": "ping"}` / `{"event": "pong"}` JSON exchange. Sending a JSON text frame like that is rejected with a `MALFORMED_REQUEST` error frame — it does not count toward keepalive. If your client library exposes ping/pong hooks, make sure they operate on protocol frames, not text messages.

### Example Implementation

<CodeGroup>
  ```javascript JavaScript/TypeScript theme={null}
  import WebSocket from "ws"

  const ws = new WebSocket("wss://api.novig.com/tape", {
      headers: {
          Authorization: `Bearer ${ACCESS_TOKEN}`,
      },
  })

  // The `ws` library answers protocol Pings automatically — no handler needed.
  // Optionally observe them to monitor connection health:
  ws.on("ping", () => {
      lastHeartbeat = Date.now()
  })

  ws.on("message", (data) => {
      const message = JSON.parse(data.toString())
      // Handle subscription acks, ticks, errors...
  })
  ```
</CodeGroup>

### Reconnection

Implement reconnection with exponential backoff. On reconnect, re-send your `subscribe` messages — subscriptions do not survive a disconnect.
