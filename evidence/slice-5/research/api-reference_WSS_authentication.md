> ## Documentation Index
> Fetch the complete documentation index at: https://docs.novig.com/llms.txt
> Use this file to discover all available pages before exploring further.

# WebSocket Authentication

> Authenticate WebSocket connections with JWT tokens

## Authentication

WebSocket connections to the NBX API require authentication using OAuth 2.0 JWT Bearer tokens.

### Obtaining an Access Token

Before connecting to the WebSocket, you must obtain a valid access token. See the [Authentication](/api-reference/authentication) guide for detailed instructions on obtaining OAuth 2.0 JWT Bearer tokens.

### Connecting with Authentication

Pass the access token in the `Authorization` header when establishing the WebSocket connection.

<CodeGroup>
  ```javascript JavaScript/TypeScript theme={null}
  import WebSocket from 'ws';

  const ws = new WebSocket('wss://api.novig.com/tape', {
    headers: {
      'Authorization': `Bearer ${access_token}`
    }
  });

  ws.on('open', () => {
    console.log('Connected to Novig WebSocket');
  });
  ```
</CodeGroup>

### QA Environment

For testing in the QA environment, use these endpoints:

* **Auth URL:** `https://auth-qa.novig.us/oauth/token`
* **Audience:** `https://api-qa.novig.us`
* **WebSocket URL:** `wss://api-qa.novig.us/tape`

### Token Expiration

JWT tokens expire after a certain period. Monitor for authentication errors and refresh your token as needed. If your connection is rejected with an authentication error, obtain a new token and reconnect.
