> ## Documentation Index
> Fetch the complete documentation index at: https://docs.novig.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Place order

> Place an order into the matching engine queue, conditional on validation. A successful response indicates that the order was placed in the queue, but does **not** guarantee that it will be filled or placed on the order book.
To reliably ensure that an order has been executed, consume messages from the matching tape to reconstruct the order book and other stateful structures.
> **Note:** If an order placed wash trades against an order from the same user, both orders will wash fill each other and effectively be cancelled.

**Rate limit:** 32 requests per second.



## OpenAPI

````yaml /api-reference/spec-files/openapi31.json post /nbx/v2/emm/orders/place
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
  /nbx/v2/emm/orders/place:
    post:
      tags:
        - Orders
      summary: Place order
      description: >-
        Place an order into the matching engine queue, conditional on
        validation. A successful response indicates that the order was placed in
        the queue, but does **not** guarantee that it will be filled or placed
        on the order book.

        To reliably ensure that an order has been executed, consume messages
        from the matching tape to reconstruct the order book and other stateful
        structures.

        > **Note:** If an order placed wash trades against an order from the
        same user, both orders will wash fill each other and effectively be
        cancelled.


        **Rate limit:** 32 requests per second.
      operationId: placeSingleOrder
      parameters: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/OrderRequestDto'
      responses:
        '201':
          description: Order placed successfully
        '400':
          description: Bad request
      x-code-samples:
        - lang: bash
          label: cURL Example
          source: |-
            curl -X POST "$API/emm/orders/place" \
              -H "Authorization: Bearer $TOKEN" \
              -H "Content-Type: application/json" \
              -d '{
                "outcomeId": "123e4567-e89b-12d3-a456-426614174000",
                "price": 0.125,
                "qty": 4200,
                "currency": COIN,
                "tif": "GTC"
            }'
components:
  schemas:
    OrderRequestDto:
      type: object
      properties:
        outcomeId:
          type: string
          description: >-
            The server-generated UUID of the outcome for which the order will
            increase exposure
          example: 123e4567-e89b-12d3-a456-426614174000
        price:
          type: number
          description: >-
            The price of the order in decimal probability, up to 3 decimal
            places
          example: 0.667
        qty:
          type: number
          description: >-
            The number of minimal currency units for the order. Note that this
            must be a positive integer. For CASH orders, 1 unit = 0.01 Novig
            Cash (e.g., 100 units = 1.00 Cash). For COIN orders, 1 unit = 1
            Novig Coin
          example: 110
        currency:
          type: string
          description: Denomination of the order, i.e. `CASH` or `COIN`
          example: CASH
        tif:
          type: string
          description: >-
            `GTC`, `GTT`, `IOC`, `FOK`, or `PO` (default is `GTC`). `PO` (post
            only) rejects the order instead of matching it immediately as a
            taker, so it only ever rests as a maker order.
          example: GTC
        ttl:
          type: number
          description: >-
            Time to live for the order (milliseconds) after which the order will
            be automatically canceled if not totally filled. Required under
            `GTT` time-in-force; optional under `PO`, where it self-expires if
            provided and otherwise rests until canceled
          example: 2400
        flags:
          type: string
          description: >-
            Custom 8-character string field for storing trader-specified flags
            or metadata about the order
          example: ABC12345
          maxLength: 8
      required:
        - outcomeId
        - price
        - qty
        - currency
        - tif

````