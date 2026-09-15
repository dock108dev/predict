> ## Documentation Index
> Fetch the complete documentation index at: https://docs.novig.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Get lock status

> Report every live trading lock: the current system lock, and the IDs of every locked event.

A lock counts as live when it has not been cleared and has not expired. `systemLock` reports `null` when the exchange is open. An event with several live locks still appears once in `lockedEventIds`.

**Rate limit:** 256 requests per second.



## OpenAPI

````yaml /api-reference/spec-files/openapi31.json get /nbx/v2/emm/locks
openapi: 3.1.0
info:
  title: NBX API
  description: >+
    ## API Overview


    The NBX API is designed with a tri-interface architecture:


    - **REST API**
      - **URL:**          `https://api.novig.com/nbx/v2`
      - **Constraints:**
        - **Rate limits:**
          - Order placement (single and batch): 64 requests per second
          - Order cancellation: 512 requests per second
          - Kill switch: 1 request per 30 seconds
          - Data retrieval: 256 requests per second
          - User history (`/fills`, `/orders`, `/transactions`): 32 requests/second burst, 512 requests/minute sustained
        - **Timeout:**    5 seconds
      - **Features:**
        - Place, cancel, and query orders.
        - Retrieve market data and positions.
        - Manage account settings and balances.
      - **Best Practices:**
        - Use appropriate HTTP methods.
        - Include `Authorization` and `Content-Type` headers.
        - Implement exponential backoff for handling rate limits and robust error handling.

    - **WebSocket API**
      - **URL:**          `wss://api.novig.com/tape`
      - **Constraints:**
        - **Keepalive:** protocol-level WebSocket Ping every 15 seconds; standard clients respond automatically, and a client that misses a full interval is disconnected
      - **Features:**
        - Real-time order book ticks.
        - Real-time market lifecycle updates.
        - Private place, fill, and cancel notifications.
        - Protocol-level heartbeat to ensure connection health.
      - **Best Practices:**
        - Implement reconnection logic with exponential backoff.
        - Process messages sequentially to maintain order book integrity.
        - Appropriately handle various event types.
        - Subscribe to specific market events or to the global tape.

    - **GraphQL API**
      - **URL:**          `https://gql.novig.com/v1/graphql`
      - **Constraints:**
        - **Rate limit:** 650 requests per minute
        - **Timeout:**    2 seconds
      - **Features:**
        - Interactive Explorer available via [**Hoppscotch GraphQL Sandbox**](https://hoppscotch.io/graphql)
        - Flexible querying of market data and prices with tailored filters.
        - Access historical data and statistics.
        - Role-based access control with baseline lurker permissions.
      - **Best Practices:**
        - Use GraphQL for historical analysis and non-time-critical queries.
        - Opt for the WebSocket API for real-time data needs.

    ## Authentication


    The NBX API uses [**OAuth 2.0 Client
    Credentials**](https://auth0.com/docs/get-started/authentication-and-authorization-flow/client-credentials-flow)
    with JSON Web Tokens (JWT).


    1. **Obtain Credentials:** Request your client ID and secret from Novig.

    2. **Request an Access Token:** Send a POST request to the OAuth endpoint.
    For example:

    ```bash

    curl 
      --request POST 
      --url https://auth.novig.us/oauth/token 
      --header "Content-Type: application/json" 
      --data '{ 
        "audience"      : "https://api.novig.us", 
        "grant_type"    : "client_credentials", 
        "client_id"     : "YOUR_CLIENT_ID", 
        "client_secret" : "YOUR_CLIENT_SECRET" 
      }'
    ```

    3. **Use the Token:** Include the token in your requests by setting the HTTP
    header:

    ```bash

    Authorization: Bearer YOUR_ACCESS_TOKEN

    ```


    > **Note:** For integration in the QA environment, you'll need to use
    different endpoints:

    > - **Issuer:** `https://auth-qa.novig.us`

    > - **Audience:** `https://api-qa.novig.us`

    > - **API Base URL:** `https://api-qa.novig.us`

  version: 0.0.44
  contact:
    name: Contact
    url: https://novig.com
    email: tech@novig.com
servers:
  - url: https://api.novig.com
    description: Production
  - url: https://api-qa.novig.us
    description: QA
security: []
tags:
  - name: Orders
    description: Endpoints for managing orders and trades
  - name: Markets
    description: Endpoints for accessing market data and order books
  - name: Events
    description: Endpoints for discovering events and fetching event-related data
  - name: Account
    description: Endpoints for managing account settings and balances
  - name: Positions
    description: Endpoints for accessing positions and fills
  - name: WebSockets
    description: Channels for real-time market data and order updates
  - name: GraphQL
    description: GraphQL API for querying market data and prices
paths:
  /nbx/v2/emm/locks:
    get:
      tags:
        - Markets
      summary: Get lock status
      description: >-
        Report every live trading lock: the current system lock, and the IDs of
        every locked event.


        A lock counts as live when it has not been cleared and has not expired.
        `systemLock` reports `null` when the exchange is open. An event with
        several live locks still appears once in `lockedEventIds`.


        **Rate limit:** 256 requests per second.
      operationId: getLockStatus
      parameters: []
      responses:
        '200':
          description: Lock status reported.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/LockStatusResponseDto'
      x-code-samples:
        - lang: bash
          label: cURL Example
          source: |-
            curl -X GET "$API/emm/locks" \
              -H "Authorization: Bearer $TOKEN"
components:
  schemas:
    LockStatusResponseDto:
      type: object
      properties:
        systemLock:
          $ref: '#/components/schemas/ActiveLockDto'
          description: The current exchange-wide lock.
          nullable: true
        lockedEventIds:
          type: array
          description: >-
            IDs of every event with a live lock. An event with several live
            locks appears once.
          items:
            type: string
            format: uuid
      required:
        - systemLock
        - lockedEventIds
    ActiveLockDto:
      type: object
      properties:
        id:
          type: string
          format: uuid
          description: The lock's ID.
          example: 123e4567-e89b-12d3-a456-426614174000
        minuteDuration:
          type: integer
          nullable: true
          description: >-
            How long the lock lasts, in minutes, from `createdAt`. `null` means
            indefinite — the lock stays live until it's cleared.
          example: 60
        createdAt:
          type: string
          format: date-time
          description: When the lock was placed.
          example: '2026-08-27T14:54:24.000Z'
        reason:
          type: string
          nullable: true
          description: Why the lock was placed.
          example: incident
      required:
        - id
        - minuteDuration
        - createdAt
        - reason

````