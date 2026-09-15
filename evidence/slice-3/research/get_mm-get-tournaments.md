---
updatedAt: 2026-09-08T17:40:44.000Z
---

Fetch the complete documentation index at: https://docs.prophetx.co/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# List tournaments

list all available tournaments

# OpenAPI definition

```json
{
  "openapi": "3.0.0",
  "info": {
    "description": "Provides data upon sport events, markets for market maker",
    "title": "External Market Maker API",
    "contact": {
      "name": "prophetexchange",
      "url": "https://api.sandbox.prophetx.dev/partner",
      "email": "support@prophetexchange.com"
    },
    "version": ""
  },
  "paths": {
    "/mm/get_tournaments": {
      "get": {
        "security": [
          {
            "Token": []
          }
        ],
        "description": "list all available tournaments",
        "tags": [
          "Tournaments"
        ],
        "summary": "List tournaments",
        "parameters": [
          {
            "description": "set it true if want to return tournaments that have active sport_events",
            "name": "has_active_events",
            "in": "query",
            "schema": {
              "type": "boolean"
            }
          }
        ],
        "responses": {
          "200": {
            "description": "OK",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/market_maker.TournamentListResponse"
                }
              }
            }
          },
          "400": {
            "description": "Bad request",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/response.ErrorResponse"
                }
              }
            }
          },
          "401": {
            "description": "Unauthorized",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/response.ErrorResponse"
                }
              }
            }
          },
          "500": {
            "description": "Internal server error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/response.ErrorResponse"
                }
              }
            }
          }
        }
      }
    }
  },
  "servers": [
    {
      "url": "https://api.sandbox.prophetx.dev/partner"
    }
  ],
  "components": {
    "securitySchemes": {
      "Token": {
        "description": "Please use \"access_token\" from the response of /auth/login endpoint, and add \"Bearer\" with space as prefix. For example: /auth/login response: {\"access_token\": \"ACCESS_TOKEN\"}, then please use \"Bearer ACCESS_TOKEN\"",
        "type": "apiKey",
        "name": "Authorization",
        "in": "header"
      }
    },
    "schemas": {
      "contract.Category": {
        "type": "object",
        "properties": {
          "countryCode": {
            "type": "string"
          },
          "id": {
            "type": "integer"
          },
          "name": {
            "type": "string"
          }
        }
      },
      "contract.Sport": {
        "type": "object",
        "properties": {
          "id": {
            "type": "integer"
          },
          "name": {
            "type": "string"
          }
        }
      },
      "contract.Tournament": {
        "type": "object",
        "properties": {
          "banner": {
            "type": "string"
          },
          "category": {
            "$ref": "#/components/schemas/contract.Category"
          },
          "id": {
            "type": "integer"
          },
          "image": {
            "type": "string"
          },
          "name": {
            "type": "string"
          },
          "sport": {
            "$ref": "#/components/schemas/contract.Sport"
          },
          "updated_at": {
            "type": "integer"
          }
        }
      },
      "market_maker.TournamentListResponse": {
        "type": "object",
        "properties": {
          "data": {
            "type": "object",
            "properties": {
              "tournaments": {
                "type": "array",
                "items": {
                  "$ref": "#/components/schemas/contract.Tournament"
                }
              }
            }
          }
        }
      },
      "response.ErrorResponse": {
        "type": "object",
        "properties": {
          "error": {},
          "message": {
            "description": "| Error Code                         | Error Message                                                                         | HTTP Status Code | Description                                                                                                                                                                                                             |\n\t\t   \t\t\t\t| ---------------------------------- | ------------------------------------------------------------------------------------- | ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |\n\t\t   \t\t\t\t| invalid_request                    | Invalid request                                                                       | 400              | Invalid request: invalid body or param or header provided in general. When can’t find detail error                                                                                                                      |\n\t\t   \t\t\t\t| invalid_param                      | Invalid param: <param_name>                                                           | 400              | Invalid parameter with given name                                                                                                                                                                                       |\n\t\t   \t\t\t\t| unauthorized                       | Unauthorized                                                                          | 401              | Invalid authorization token                                                                                                                                                                                             |\n\t\t   \t\t\t\t| data_not_found                     | Data not found                                                                        | 404              | Requested data does not exists or not found                                                                                                                                                                             |\n\t\t   \t\t\t\t| data_not_found                     | Not found: <entity_name>                                                              | 404              | Requested data does not exists or not found (point out detail which entity not found)                                                                                                                                   |\n\t\t   \t\t\t\t| internal_error                     | Internal server error                                                                 | 500              | Internal server error                                                                                                                                                                                                   |\n\t\t   \t\t\t\t| keypair_num_exceed                 | Cannot create new key pair, only 20 key pair can be created                           | 403              | Number of existed key pairs has reached the maximum number of 20 key pairs                                                                                                                                              |\n\t\t   \t\t\t\t| session_num_exceed                 | Cannot authorize new session, only 20 sessions can exist simultaneously               | 403              | Number of authorized sessions has reached the maximum number of 20 sessions                                                                                                                                             |\n\t\t   \t\t\t\t| rate_limit_reached                 | Rate limit reached, can only send up to 50 requests per seconds                       | 429              | Rate limit reached                                                                                                                                                                                                      |\n\t\t   \t\t\t\t| insufficient_amount                | You don’t have sufficient amount to proceed the operation                             | 403              | This is an example error code for any given operation                                                                                                                                                                   |\n\t\t   \t\t\t\t| invalid_line_id                    | Invalid line id                                                                       | 400              | Invalid line id                                                                                                                                                                                                         |\n\t\t   \t\t\t\t| invalid_stake                      | Invalid stake                                                                         | 400              | Invalid stake                                                                                                                                                                                                           |\n\t\t   \t\t\t\t| invalid_external_id                | Invalid external id                                                                   | 400              | Invalid external id                                                                                                                                                                                                     |\n\t\t   \t\t\t\t| wager_limit_exceeded               | Wager limit exceeded                                                                  | 400              | The error is raised when total wager or bet exceeds the allowed limit, currently the maximum batch is 20.                                                                                                               |\n\t\t   \t\t\t\t| invalid_wager_id                   | Invalid wager id                                                                      | 400              | Invalid wager id                                                                                                                                                                                                        |\n\t\t   \t\t\t\t| invalid_cursor                     | Invalid cursor                                                                        | 400              | Invalid cursor param                                                                                                                                                                                                    |\n\t\t   \t\t\t\t| invalid_from                       | Invalid param from                                                                    | 400              | Invalid param from                                                                                                                                                                                                      |\n\t\t   \t\t\t\t| invalid_to                         | Invalid param to                                                                      | 400              | Invalid param to                                                                                                                                                                                                        |\n\t\t   \t\t\t\t| invalid_updated_at_from            | Invalid param updated_at_from                                                         | 400              | Invalid param updated_at_from                                                                                                                                                                                           |\n\t\t   \t\t\t\t| invalid_updated_at_to              | Invalid param updated_at_to                                                           | 400              | Invalid param updated_at_to                                                                                                                                                                                             |\n\t\t   \t\t\t\t| invalid_competitor_id              | Invalid competitor id                                                                 | 400              | Invalid competitor id, when                                                                                                                                                                                             |\n\t\t   \t\t\t\t| sport_event_not_found              | Sport event not found                                                                 | 404              | Sport event not found                                                                                                                                                                                                   |\n\t\t   \t\t\t\t| market_invalid_event               | Invalid event_id                                                                      | 400              | This error is used when attempting to create or access a market with an invalid event ID. The condition EventID <= 0 or r.EventID > 2147483647 checks if the provided event ID is equal to 0 or falls outside the valid |\n\t\t   \t\t\t\t| market_event_limit_exceeded        | Event limit exceeded                                                                  | 400              | This error is raised when the number of event_ids in a market query exceeds the allowed limit, currently (0, 50]                                                                                                        |\n\t\t   \t\t\t\t| opened_retry                       | We are processing other request. Please wait and retry later                          | 500              | Newly opened wager is in its first matching queue, please retry after 300ms.                                                                                                                                            |\n\t\t   \t\t\t\t| unknown_error                      | Unknown error                                                                         | 500              | Unknown error                                                                                                                                                                                                           |\n\t\t   \t\t\t\t| err_ref_id_invalid                 | reference id invalid                                                                  | 404              | Reference id invalid, currently 0                                                                                                                                                                                       |\n\t\t   \t\t\t\t| event_not_available                | event is not available for betting                                                    | 400              | Event is not available for betting                                                                                                                                                                                      |\n\t\t   \t\t\t\t| sport_event_competitor_blacklisted | can not place bet with given competitors                                              | 400              | The event competitor in blacklisted                                                                                                                                                                                     |\n\t\t   \t\t\t\t| sport_event_is_not_booked          | sport event is not booked                                                             | 400              | sport event is not booked                                                                                                                                                                                               |\n\t\t   \t\t\t\t| wager_ref_id_existed               | wager ref id is already existing                                                      | 400              | Wager ref id is already existing                                                                                                                                                                                        |\n\t\t   \t\t\t\t| wager_already_matched              | failed to cancel wager. wager is already matched                                      | 400              | Wager is already matched                                                                                                                                                                                                |\n\t\t   \t\t\t\t| wager_not_belongs_to_user          | this wager does not belong to user                                                    | 500              | Wager not belong to the user (who 's calling)                                                                                                                                                                           |\n\t\t   \t\t\t\t| wager_already_cancelled            | failed to cancel wager. wager is already cancelled                                    | 400              | Wager is already cancelled                                                                                                                                                                                              |\n\t\t   \t\t\t\t| wager_is_invalid                   | The wager you attempting to cancel is invalid                                         | 400              | Wager’ status is invalid                                                                                                                                                                                                |\n\t\t   \t\t\t\t| wager_invalid_odds                 | invalid odds (consider extract keyword and return like partner error, for consistent) | 400              | invalid odds, when odds <= 1.0                                                                                                                                                                                          |\n\t\t   \t\t\t\t| wager_not_matching_external_id     | external id must matches with existing wager                                          | 400              | External id must matches with existing wager                                                                                                                                                                            |\n\t\t   \t\t\t\t| wager_opened_retry                 | Newly opened wager is in its first matching queue, please retry after 300ms.          | 425              | Failed to lock wager when cancel wager.                                                                                                                                                                                 |\n\t\t   \t\t\t\t| wager_is_placing                   | cannot cancel a placing wager, please try again later                                 | 409              | Cannot cancel a placing wager                                                                                                                                                                                           |\n\t\t   \t\t\t\t| wager_stake_exceeds_max            | your wager stake exceeds the maximum allowed                                          | 400              | your wager stake exceeds the maximum allowed, currently 100000000                                                                                                                                                       |\n\t\t   \t\t\t\t| wager_external_id_existed          | given user id already has wager with the same external id                             | 400              | given user id already has wager with the same external id                                                                                                                                                               |\n\t\t   \t\t\t\t| wager_balance_check_timeout        | wallet check balance request timeout                                                  | 500              | Time out when check wager balance                                                                                                                                                                                       |\n\t\t   \t\t\t\t| wager_unable_place                 | we cannot place your bet                                                              | 500              | Unhadled error in wager.                                                                                                                                                                                                |\n\t\t   \t\t\t\t| wager_unable_cancel                | failed to cancel wager                                                                | 500              | For unhanled wager                                                                                                                                                                                                      |\n\t\t   \t\t\t\t| invalid_market_id                  | Invalid market id                                                                     | 400              | Invalid market id, when even id equal to zero                                                                                                                                                                           |\n\t\t   \t\t  \t| invalid_event_id                   | Invalid event id                                                                      | 400              | Invalid event id, when even id equal to zero                                                                                                                                                                            |\n\t\t   \t\t  \t| supplemental_market_pre_match_only | supplemental market just ready for pre-match sport event                              | 400              | When market line' type is sup_moneyline, the sport event’ status must not equal to not_started                                                                                                                          |\n\t\t   \t\t  \t| market_line_invalid                | market line id is invalid                                                             | 400              | when can’t found market by line id in database                                                                                                                                                                          |\n\t\t   \t\t  \t| wallet_not_found                   | Wallet not found                                                                      | 404              | Wallet not found                                                                                                                                                                                                        |\n\t\t   \t\t  \t| no_cancellable_wagers              | Failed to cancel wagers. No available wagers to be cancelled                          | 404              | No cancellable wagers                                                                                                                                                                                                   |\n\t\t   \t\t  \t| wager_invalid_profit               | update odds or stake then try again                                                   | 400              | The profit calculated from odds and stake less than 1 cent                                                                                                                                                              |\n\t\t   \t\t  \t| reporting_not_available            | reporting service not available                                                       | 503              | Reporting DB in maintenance mode                                                                                                                                                                                        |\n\t\t   \t\t  \t| from_date_greater_than_to_date     | from date must be lower than to date                                                  | 400              | Param from must be lower than param to                                                                                                                                                                                  |\n\t\t   \t\t  \t| invalid_from_to_range              | 'from' can't be more than 7 days from 'to'                                            | 400              | Param from can't be more than 7 days from param to                                                                                                                                                                      |\n\t\t   \t\t  \t| invalid_updated_at_range           | updated_at_from can't be more than 2 days from updated_at_to                          | 400              | Param updated_at_from can't be more than 2 days from param updated_at_to                                                                                                                                                |\n\t\t\t\t\t| missing_date_range           | missing date range param                          | 400              | Missing date range param                                                                                                                                                |\n\t\t\t\t\t| too_many_delayed_requests           |The request cannot be delayed at the moment                         | 429              | Request rate limit for delayed processing has been reached                                                                                                                                                |\n\t\t\t\t\t| err_wager_placement_disabled           | wager placement is currently disabled                         | 403              | The system under maintenance mode so not allow place wager                                                                                                                                                |\n\t\t\t\t\t| err_add_liquidity_only_disabled           | add-liquidity-only orders are not currently available                         | 400              | ALO (`order_strategy`/`wager_strategy: \"ALO\"`) is currently disabled                                                                                                                                |",
            "type": "string"
          }
        }
      }
    }
  }
}
```