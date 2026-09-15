> ## Documentation Index
> Fetch the complete documentation index at: https://docs.novig.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Get order book

> Get the current order book for a specific market. For both outcomes of the market, orders are returned sorted by price-time priority. Orders on the book are partially obfuscated up to price, quantity, and direction.

**Rate limit:** 128 requests per second.



## OpenAPI

````yaml /api-reference/spec-files/openapi31.json get /nbx/v2/emm/book/{marketId}
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
  /nbx/v2/emm/book/{marketId}:
    get:
      tags:
        - Markets
      summary: Get order book
      description: >-
        Get the current order book for a specific market. For both outcomes of
        the market, orders are returned sorted by price-time priority. Orders on
        the book are partially obfuscated up to price, quantity, and direction.


        **Rate limit:** 128 requests per second.
      operationId: getMarketOrderBook
      parameters:
        - name: marketId
          required: true
          in: path
          description: The ID of the market
          schema:
            type: string
        - name: currency
          in: query
          description: The currency denomination
          required: true
          schema:
            type: string
            enum:
              - CASH
              - COIN
      responses:
        '200':
          description: Successfully retrieved the order book.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/BookResponseDto'
        '400':
          description: Bad request
components:
  schemas:
    BookResponseDto:
      type: object
      properties:
        marketId:
          type: string
          description: The ID of the market
        marketDescription:
          type: string
          description: Description of the market
        outcomeLadders:
          description: List of outcomes with their order books
          type: array
          items:
            $ref: '#/components/schemas/BookLadderDto'
      required:
        - marketId
        - marketDescription
        - outcomeLadders
    BookLadderDto:
      type: object
      properties:
        outcomeId:
          type: string
          description: The ID of the outcome
        bids:
          description: List of bid orders in price-time priority order
          type: array
          items:
            $ref: '#/components/schemas/ObfuscatedOrderDto'
      required:
        - outcomeId
        - bids
    ObfuscatedOrderDto:
      type: object
      properties:
        id:
          type: string
          description: The ID of the order
          example: 123e4567-e89b-12d3-a456-426614174000
        price:
          type: number
          description: >-
            The price of the order (in decimal probability, up to 3 decimal
            places)
          example: 0.667
        qty:
          type: number
          description: >-
            The remaining quantity of the order, denominated in Minimum Currency
            Units
          example: 110
        originalQty:
          type: number
          description: >-
            The original quantity of the order, denominated in Minimum Currency
            Units
          example: 110
        currency:
          type: string
          enum:
            - CASH
            - COIN
          description: The currency in which the order is denominated
          example: CASH
        outcomeId:
          type: string
          description: The ID of the outcome for which the order is placed
        marketId:
          type: string
          description: The ID of the market for which the order is placed
        status:
          type: string
          description: The status of the order immediately after execution
          example: RESTING
        created_at:
          type: string
          format: date-time
          description: The timestamp when the order was created
          example: '2024-01-01T00:00:00.000Z'
      required:
        - id
        - price
        - qty
        - originalQty
        - currency
        - outcomeId
        - marketId
        - status
        - created_at

````