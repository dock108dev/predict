---
updatedAt: 2026-09-10T16:22:57.000Z
---

Fetch the complete documentation index at: https://docs.prophetx.co/llms.txt. Use this file to discover all available pages before exploring further. Append .md to any documentation page URL to get its markdown version.

# Submit order

### Submit an order
`order_strategy` with value `fillOrKill` that will be auto-canceled if no match is made in 2 seconds
`order_strategy` with value `ALO` (add-liquidity-only) rests and posts liquidity only; never takes
For normal orders, just remove the `order_strategy` field


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
    "/v4/mm/submit_order": {
      "post": {
        "security": [
          {
            "Token": []
          }
        ],
        "description": "### Submit an order\n`order_strategy` with value `fillOrKill` that will be auto-canceled if no match is made in 2 seconds\n`order_strategy` with value `ALO` (add-liquidity-only) rests and posts liquidity only; never takes\nFor normal orders, just remove the `order_strategy` field\n",
        "tags": [
          "Order"
        ],
        "summary": "Submit order",
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {
                "$ref": "#/components/schemas/market_maker.PlaceOrderRequest"
              }
            }
          },
          "description": "body",
          "required": true
        },
        "responses": {
          "200": {
            "description": "OK",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/market_maker.PlaceOrderResponse"
                }
              }
            }
          },
          "400": {
            "description": "Sport event is not booked",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/response.ErrorResponseV4"
                }
              }
            }
          },
          "401": {
            "description": "Unauthorized",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/response.ErrorResponseV4"
                }
              }
            }
          },
          "403": {
            "description": "User is suspended",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/response.ErrorResponseV4"
                }
              }
            }
          },
          "404": {
            "description": "Your requested data is not found",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/response.ErrorResponseV4"
                }
              }
            }
          },
          "500": {
            "description": "Internal server error",
            "content": {
              "application/json": {
                "schema": {
                  "$ref": "#/components/schemas/response.ErrorResponseV4"
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
      "market_maker.PlaceOrderRequest": {
        "type": "object",
        "properties": {
          "external_id": {
            "type": "string"
          },
          "order_strategy": {
            "type": "string",
            "enum": [
              "fillOrKill",
              "ALO"
            ],
            "example": "fillOrKill"
          },
          "price": {
            "type": "number"
          },
          "quantity": {
            "type": "number"
          },
          "strike_id": {
            "type": "string"
          }
        }
      },
      "market_maker.PlaceOrderResponse": {
        "type": "object",
        "properties": {
          "data": {
            "type": "object",
            "properties": {
              "order": {
                "$ref": "#/components/schemas/v4.Order"
              },
              "success": {
                "type": "boolean"
              }
            }
          }
        }
      },
      "v4.Order": {
        "type": "object",
        "properties": {
          "external_id": {
            "type": "string"
          },
          "filled_quantity": {
            "type": "number"
          },
          "market_id": {
            "type": "integer"
          },
          "matching_status": {
            "type": "string",
            "enum": [
              "unmatched",
              "fully_matched",
              "partially_matched"
            ]
          },
          "open_quantity": {
            "type": "number"
          },
          "order_id": {
            "type": "string"
          },
          "outcome_id": {
            "type": "integer"
          },
          "price": {
            "type": "number"
          },
          "profit": {
            "type": "number"
          },
          "quantity": {
            "type": "number"
          },
          "sport_event_id": {
            "type": "integer"
          },
          "status": {
            "type": "string",
            "enum": [
              "void",
              "closed",
              "canceled",
              "manually_settled",
              "inactive",
              "wiped",
              "open",
              "invalid"
            ]
          },
          "strike": {
            "type": "number"
          },
          "strike_id": {
            "type": "string"
          },
          "user_id": {
            "type": "string"
          },
          "winning_status": {
            "type": "string",
            "enum": [
              "profit",
              "loss",
              "no_result",
              "tbd",
              "manually_lost",
              "manually_won",
              "draw",
              "push"
            ]
          }
        }
      },
      "response.ErrorResponseV4": {
        "type": "object",
        "properties": {
          "error": {},
          "message": {
            "description": "| Error Code                         | Error Message                                                                          | HTTP Status Code | Description                                                                                                                                                                                                             |\n| ---------------------------------- | -------------------------------------------------------------------------------------- | ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |\n| invalid_request                    | Invalid request                                                                        | 400              | Invalid request: invalid body or param or header provided in general. When can’t find detail error                                                                                                                      |\n| invalid_param                      | Invalid param: <param_name>                                                            | 400              | Invalid parameter with given name                                                                                                                                                                                       |\n| unauthorized                       | Unauthorized                                                                           | 401              | Invalid authorization token                                                                                                                                                                                             |\n| data_not_found                     | Data not found                                                                         | 404              | Requested data does not exists or not found                                                                                                                                                                             |\n| data_not_found                     | Not found: <entity_name>                                                               | 404              | Requested data does not exists or not found (point out detail which entity not found)                                                                                                                                   |\n| internal_error                     | Internal server error                                                                  | 500              | Internal server error                                                                                                                                                                                                   |\n| keypair_num_exceed                 | Cannot create new key pair, only 20 key pair can be created                            | 403              | Number of existed key pairs has reached the maximum number of 20 key pairs                                                                                                                                              |\n| session_num_exceed                 | Cannot authorize new session, only 20 sessions can exist simultaneously                | 403              | Number of authorized sessions has reached the maximum number of 20 sessions                                                                                                                                             |\n| rate_limit_reached                 | Rate limit reached, can only send up to 50 requests per seconds                        | 429              | Rate limit reached                                                                                                                                                                                                      |\n| insufficient_amount                | You don’t have sufficient amount to proceed the operation                              | 403              | This is an example error code for any given operation                                                                                                                                                                   |\n| invalid_strike_id                  | Invalid strike id                                                                      | 400              | Invalid strike id                                                                                                                                                                                                       |\n| invalid_quantity                   | Invalid quantity                                                                       | 400              | Invalid quantity                                                                                                                                                                                                        |\n| invalid_external_id                | Invalid external id                                                                    | 400              | Invalid external id                                                                                                                                                                                                     |\n| order_limit_exceeded               | Order limit exceeded                                                                   | 400              | The error is raised when total order or bet exceeds the allowed limit, currently the maximum batch is 20.                                                                                                               |\n| invalid_order_id                   | Invalid order id                                                                       | 400              | Invalid order id                                                                                                                                                                                                        |\n| invalid_cursor                     | Invalid cursor                                                                         | 400              | Invalid cursor param                                                                                                                                                                                                    |\n| invalid_from                       | Invalid param from                                                                     | 400              | Invalid param from                                                                                                                                                                                                      |\n| invalid_to                         | Invalid param to                                                                       | 400              | Invalid param to                                                                                                                                                                                                        |\n| invalid_updated_at_from            | Invalid param updated_at_from                                                          | 400              | Invalid param updated_at_from                                                                                                                                                                                           |\n| invalid_updated_at_to              | Invalid param updated_at_to                                                            | 400              | Invalid param updated_at_to                                                                                                                                                                                             |\n| invalid_competitor_id              | Invalid competitor id                                                                  | 400              | Invalid competitor id, when                                                                                                                                                                                             |\n| sport_event_not_found              | Sport event not found                                                                  | 404              | Sport event not found                                                                                                                                                                                                   |\n| market_invalid_event               | Invalid event_id                                                                       | 400              | This error is used when attempting to create or access a market with an invalid event ID. The condition EventID <= 0 or r.EventID > 2147483647 checks if the provided event ID is equal to 0 or falls outside the valid |\n| market_event_limit_exceeded        | Event limit exceeded                                                                   | 400              | This error is raised when the number of event_ids in a market query exceeds the allowed limit, currently (0, 50]                                                                                                        |\n| opened_retry                       | We are processing other request. Please wait and retry later                           | 500              | Newly opened order is in its first matching queue, please retry after 300ms.                                                                                                                                            |\n| unknown_error                      | Unknown error                                                                          | 500              | Unknown error                                                                                                                                                                                                           |\n| err_ref_id_invalid                 | reference id invalid                                                                   | 404              | Reference id invalid, currently 0                                                                                                                                                                                       |\n| event_not_available                | event is not available for betting                                                     | 400              | Event is not available for betting                                                                                                                                                                                      |\n| sport_event_competitor_blacklisted | can not place order with given competitors                                             | 400              | The event competitor in blacklisted                                                                                                                                                                                     |\n| sport_event_is_not_booked          | sport event is not booked                                                              | 400              | sport event is not booked                                                                                                                                                                                               |\n| order_ref_id_existed               | order ref id is already existing                                                       | 400              | Order ref id is already existing                                                                                                                                                                                        |\n| order_already_filled               | failed to cancel order. order is already matched                                       | 400              | Order is already matched                                                                                                                                                                                                |\n| order_not_belongs_to_user          | this order does not belong to user                                                     | 500              | Order not belong to the user (who 's calling)                                                                                                                                                                           |\n| order_already_cancelled            | failed to cancel order. order is already cancelled                                     | 400              | Order is already cancelled                                                                                                                                                                                              |\n| order_is_invalid                   | The order you attempting to cancel is invalid                                          | 400              | Order’ status is invalid                                                                                                                                                                                                |\n| invalid_price                      | invalid price (consider extract keyword and return like partner error, for consistent) | 400              | invalid price, when price <= 1.0                                                                                                                                                                                        |\n| order_not_matching_external_id     | external id must matches with existing order                                           | 400              | External id must matches with existing order                                                                                                                                                                            |\n| order_opened_retry                 | Newly opened order is in its first matching queue, please retry after 300ms.           | 425              | Failed to lock order when cancel order.                                                                                                                                                                                 |\n| order_is_placing                   | cannot cancel a placing order, please try again later                                  | 409              | Cannot cancel a placing order                                                                                                                                                                                           |\n| order_quantity_exceeds_max         | your order quantity exceeds the maximum allowed                                        | 400              | your order quantity exceeds the maximum allowed, currently 100000000                                                                                                                                                    |\n| order_external_id_existed          | given user id already has order with the same external id                              | 400              | given user id already has order with the same external id                                                                                                                                                               |\n| order_balance_check_timeout        | wallet check balance request timeout                                                   | 500              | Time out when check order balance                                                                                                                                                                                       |\n| order_unable_to_place              | we cannot place your order                                                             | 500              | Unhadled error in order.                                                                                                                                                                                                |\n| order_unable_to_cancel             | failed to cancel order                                                                 | 500              | For unhanled order                                                                                                                                                                                                      |\n| invalid_market_id                  | Invalid market id                                                                      | 400              | Invalid market id, when even id equal to zero                                                                                                                                                                           |\n| invalid_event_id                   | Invalid event id                                                                       | 400              | Invalid event id, when even id equal to zero                                                                                                                                                                            |\n| supplemental_market_pre_match_only | supplemental market just ready for pre-match sport event                               | 400              | When market strike' type is sup_moneyline, the sport event’ status must not equal to not_started                                                                                                                        |\n| strike_id_invalid                  | market strike id is invalid                                                            | 400              | when can’t found market by strike id in database                                                                                                                                                                        |\n| wallet_not_found                   | Wallet not found                                                                       | 404              | Wallet not found                                                                                                                                                                                                        |\n| no_cancellable_orders              | Failed to cancel orders. No available orders to be cancelled                           | 404              | No cancellable orders                                                                                                                                                                                                   |\n| order_invalid_profit               | update price or quantity then try again                                                | 400              | The profit calculated from price and quantity less than 1 cent                                                                                                                                                          |\n| reporting_not_available            | reporting service not available                                                        | 503              | Reporting DB in maintenance mode                                                                                                                                                                                        |\n| from_date_greater_than_to_date     | from date must be lower than to date                                                   | 400              | Param from must be lower than param to                                                                                                                                                                                  |\n| invalid_from_to_range              | 'from' can't be more than 7 days from 'to'                                             | 400              | Param from can't be more than 7 days from param to                                                                                                                                                                      |\n| invalid_updated_at_range           | updated_at_from can't be more than 2 days from updated_at_to                           | 400              | Param updated_at_from can't be more than 2 days from param updated_at_to                                                                                                                                                |\n| missing_date_range                 | missing date range param                                                               | 400              | Missing date range param                                                                                                                                                                                                |\n| too_many_delayed_requests          | The request cannot be delayed at the moment                                            | 429              | Request rate limit for delayed processing has been reached                                                                                                                                                              |\n| err_order_placement_disabled       | order placement is currently disabled                                                  | 403              | The system under maintenance mode so not allow place order                                                                                                                                                              |\n| err_add_liquidity_only_disabled    | add-liquidity-only orders are not currently available                                  | 400              | ALO (`order_strategy: \"ALO\"`) is currently disabled                                                                                                                                                    |",
            "type": "string"
          }
        }
      }
    }
  }
}
```