> ## Documentation Index
> Fetch the complete documentation index at: https://docs.novig.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Get events

> Fetch a list of events with optional filters. Results are limited to a maximum of 100 items by default.

Filter on `status=OPEN_INGAME` for the set of live events — the condition under which taker fees are charged. Use this as your liveness snapshot on startup and after a WebSocket reconnect, then track the `EVENT_GOLIVE` / `EVENT_UNLIVE` ticks on the `lifecycle` channel for subsequent transitions.

**Rate limit:** 512 requests per second.



## OpenAPI

````yaml /api-reference/spec-files/openapi31.json get /nbx/v2/emm/events
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
  /nbx/v2/emm/events:
    get:
      tags:
        - Events
      summary: Get events
      description: >-
        Fetch a list of events with optional filters. Results are limited to a
        maximum of 100 items by default.


        Filter on `status=OPEN_INGAME` for the set of live events — the
        condition under which taker fees are charged. Use this as your liveness
        snapshot on startup and after a WebSocket reconnect, then track the
        `EVENT_GOLIVE` / `EVENT_UNLIVE` ticks on the `lifecycle` channel for
        subsequent transitions.


        **Rate limit:** 512 requests per second.
      operationId: getEvents
      parameters:
        - name: league
          in: query
          description: Filter by league (e.g., NFL, NBA, MLB)
          required: false
          schema:
            type: string
        - name: type
          in: query
          description: Filter by event type (e.g., Game)
          required: false
          schema:
            type: string
        - name: status
          in: query
          description: >-
            Filter by event status (e.g., OPEN_PREGAME, OPEN_INGAME).
            `OPEN_INGAME` means the event is live
          required: false
          schema:
            type: string
            enum:
              - INITIAL
              - OPEN_PREGAME
              - CLOSED_PREGAME
              - OPEN_INGAME
              - FINAL
              - DELAYED
              - CANCELED
        - name: limit
          in: query
          description: Number of results to return (max 100, default 100)
          required: false
          schema:
            type: integer
            maximum: 100
            default: 100
        - name: offset
          in: query
          description: Pagination offset (default 0)
          required: false
          schema:
            type: integer
            default: 0
      responses:
        '200':
          description: Successfully retrieved events.
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: '#/components/schemas/EventWithMarketsDto'
        '400':
          description: Bad request
      x-code-samples:
        - lang: bash
          label: cURL Example
          source: >-
            curl -X GET
            "https://api.novig.com/nbx/v2/emm/events?league=NFL&type=Game&status=OPEN_PREGAME&limit=100"
            \
              -H "Authorization: Bearer $TOKEN"
components:
  schemas:
    EventWithMarketsDto:
      type: object
      properties:
        id:
          type: string
          description: The unique identifier of the event
          example: 550e8400-e29b-41d4-a716-446655440000
        type:
          type: string
          description: The type of event
          example: Game
        status:
          type: string
          description: >-
            The current status of the event. `OPEN_INGAME` means the event is
            live — taker fees are charged only on fills matched while the event
            is live, and a live event's resting orders were cancelled when it
            went live
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
          description: A human-readable description of the event
          example: Kansas City Chiefs @ Buffalo Bills
        league:
          type: string
          description: The league this event belongs to
          example: NFL
        scheduledStart:
          type: string
          format: date-time
          description: The scheduled start time of the event
          example: '2025-01-26T18:30:00.000Z'
        game:
          $ref: '#/components/schemas/GameResponseDto'
          description: The game details associated with the event
        marketIds:
          type: array
          items:
            type: string
          description: Array of market IDs associated with this event
          example:
            - market-uuid-1
            - market-uuid-2
            - market-uuid-3
      required:
        - id
        - type
        - status
        - description
        - league
        - scheduledStart
        - marketIds
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

````