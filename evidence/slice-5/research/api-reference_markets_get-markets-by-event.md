> ## Documentation Index
> Fetch the complete documentation index at: https://docs.novig.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Get markets by event

> Fetch all markets for a specific event, including current orderbook data. This endpoint returns markets with their bid/ask data in a single response, eliminating the need to fetch orders separately.

**Rate limit:** 512 requests per second.



## OpenAPI

````yaml /api-reference/spec-files/openapi31.json get /nbx/v2/emm/events/getMarketsByEvent/{eventId}
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
  /nbx/v2/emm/events/getMarketsByEvent/{eventId}:
    get:
      tags:
        - Markets
      summary: Get markets by event
      description: >-
        Fetch all markets for a specific event, including current orderbook
        data. This endpoint returns markets with their bid/ask data in a single
        response, eliminating the need to fetch orders separately.


        **Rate limit:** 512 requests per second.
      operationId: getMarketsByEvent
      parameters:
        - name: eventId
          required: true
          in: path
          description: The server-generated UUID of the event
          schema:
            type: string
        - name: currency
          required: true
          in: query
          description: Currency for orderbook data
          schema:
            type: string
            enum:
              - CASH
              - COIN
      responses:
        '200':
          description: Successfully retrieved markets for the event.
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: '#/components/schemas/MarketWithBookDto'
        '400':
          description: Bad request
        '404':
          description: Event not found
      x-code-samples:
        - lang: bash
          label: cURL Example
          source: >-
            curl -X GET
            "https://api.novig.com/nbx/v2/emm/events/getMarketsByEvent/550e8400-e29b-41d4-a716-446655440000?currency=CASH"
            \
              -H "Authorization: Bearer $TOKEN"
components:
  schemas:
    MarketWithBookDto:
      type: object
      properties:
        id:
          type: string
          description: The ID of the market
          example: 123e4567-e89b-12d3-a456-426614174000
        description:
          type: string
          description: Description of the market
          example: KC v BUF Total
        status:
          type: string
          description: The current status of the market (OPEN, CLOSED, or SETTLED)
          example: OPEN
        strike:
          type: number
          description: The threshold of the market in the unit of the stat type
          nullable: true
          example: 26.5
        type:
          type: string
          description: The type of market (MONEY, SPREAD, TOTAL, RUSHING_ATTEMPTS, etc.)
          example: TOTAL
        league:
          type: string
          description: The league of the market
          example: NFL
        volume:
          type: number
          description: The total volume of the market in CASH denomination
          example: 1000000
        eventId:
          type: string
          description: The event associated with the market
          example: 123e4567-e89b-12d3-a456-426614174000
        event:
          $ref: '#/components/schemas/EventResponseDto'
          description: The event details associated with the market
        outcomeIds:
          description: Array of outcome IDs linked to this market
          type: array
          items:
            type: string
          example:
            - 123e4567-e89b-12d3-a456-426614174002
            - 123e4567-e89b-12d3-a456-426614174003
        outcomes:
          description: Array of outcomes linked to this market
          type: array
          items:
            $ref: '#/components/schemas/OutcomeResponseDto'
        playerId:
          type: string
          description: The player associated with the market (if applicable)
          nullable: true
          example: 123e4567-e89b-12d3-a456-426614174001
        player:
          $ref: '#/components/schemas/PlayerResponseDto'
          description: The player associated with the market (if applicable)
          nullable: true
        competitor:
          $ref: '#/components/schemas/TeamResponseDto'
          description: The competitor associated with the market (if applicable)
          nullable: true
        settledAt:
          type: string
          description: When the market was settled (if applicable)
          nullable: true
          example: '2023-10-05T12:00:00Z'
        book:
          $ref: '#/components/schemas/BookResponseDto'
          description: The current orderbook for this market
      required:
        - id
        - description
        - status
        - type
        - league
        - volume
        - eventId
        - outcomeIds
        - outcomes
        - book
    EventResponseDto:
      type: object
      properties:
        id:
          type: string
          description: The ID of the event
          example: 123e4567-e89b-12d3-a456-426614174000
        game:
          $ref: '#/components/schemas/GameResponseDto'
          description: The game associated with the event
        type:
          type: string
          description: The type of the event
          example: REGULAR_SEASON
        status:
          type: string
          description: The status of the event
          enum:
            - INITIAL
            - OPEN_PREGAME
            - CLOSED_PREGAME
            - OPEN_INGAME
            - FINAL
            - DELAYED
            - CANCELED
          example: OPEN_PREGAME
        description:
          type: string
          description: The description of the event
          example: KC Chiefs vs BUF Bills - Week 14
      required:
        - id
        - type
        - status
        - description
    OutcomeResponseDto:
      type: object
      properties:
        id:
          type: string
          description: The ID of the outcome
          example: 123e4567-e89b-12d3-a456-426614174000
        description:
          type: string
          description: The description of the outcome
          example: Over 26.5
        type:
          type: string
          description: The type of the outcome
          nullable: true
        status:
          type: string
          description: The status of the outcome
          example: TBD
        index:
          type: number
          description: The index of the outcome (0 = Home/Over, 1 = Away/Under)
          example: 0
        last:
          type: number
          description: The last trade price for this outcome
          nullable: true
          example: 0.55
        competitor:
          $ref: '#/components/schemas/TeamResponseDto'
          description: The competitor associated with this outcome
          nullable: true
      required:
        - id
        - description
        - type
        - status
        - index
    PlayerResponseDto:
      type: object
      properties:
        id:
          type: string
          description: The ID of the player
          example: 123e4567-e89b-12d3-a456-426614174000
        name:
          type: string
          description: The name of the player
          nullable: true
          example: Josh Allen
        fullName:
          type: string
          description: The full name of the player
          nullable: true
          example: Joshua Patrick Allen
        position:
          type: string
          description: The position of the player
          nullable: true
          example: QB
      required:
        - id
    TeamResponseDto:
      type: object
      properties:
        id:
          type: string
          description: The ID of the team
          example: 123e4567-e89b-12d3-a456-426614174000
        name:
          type: string
          description: The name of the team
          example: Kansas City Chiefs
        shortName:
          type: string
          description: The short name of the team
          example: Chiefs
        symbol:
          type: string
          description: The symbol of the team
          example: KC
        mascot:
          type: string
          description: The mascot of the team
          example: Chiefs
      required:
        - id
        - name
        - shortName
        - symbol
        - mascot
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
    GameResponseDto:
      type: object
      properties:
        id:
          type: string
          description: The ID of the game
          example: 123e4567-e89b-12d3-a456-426614174000
        league:
          type: string
          description: The league of the game
          example: NFL
        status:
          type: string
          description: The status of the game
          example: SCHEDULED
        scheduledStart:
          type: string
          format: date-time
          description: The scheduled start time of the game
          example: '2023-12-10T20:00:00Z'
        homeTeam:
          $ref: '#/components/schemas/TeamResponseDto'
          description: The home team of the game
        awayTeam:
          $ref: '#/components/schemas/TeamResponseDto'
          description: The away team of the game
      required:
        - id
        - league
        - status
        - scheduledStart
        - homeTeam
        - awayTeam
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