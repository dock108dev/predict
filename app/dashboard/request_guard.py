"""Shared loopback request validation, SQL route retirement and safe errors."""

from aiohttp import web

from app.diagnostics import failure
from .local_security import HEADERS, PublicRequestError, body_limit, check_browser
from .query_policy import validate_http_query, validate_unique_query


def dashboard_guard(current_provider, *, logger):
    """Bind one app's provider without taking ownership of its mutable state."""
    from .current_state import SelectionError

    @web.middleware
    async def guard(request, handler):
        try:
            check_browser(request)
            validate_unique_query(request.query)
            limit = body_limit(request.path)
            if request.method == "POST" and (request.content_length or 0) > limit:
                raise web.HTTPRequestEntityTooLarge(
                    max_size=limit, actual_size=request.content_length
                )
            if request.path in (
                "/api/dashboard",
                "/api/calculate",
                "/api/sessions",
                "/api/resolution",
            ):
                validate_http_query(request.query)
            if getattr(current_provider, "database_mode", False) and (
                request.path
                in (
                    "/api/comparison",
                    "/api/arbs",
                )
                or request.path == "/api/current"
                or request.path.startswith("/api/current/")
                or request.path == "/api/selections"
                or request.path.startswith("/api/selections/")
            ):
                # The ordinary installation has one SQL owner. Its old injected
                # state transport must not silently show an empty/stale fallback.
                response = web.json_response(
                    dict(
                        error="current_state_transport_retired",
                        reason="Use current SQL comparison boards and their revision-bound Details.",
                        current_api="/api/boards/slate",
                        current_url="/",
                        provider_requests=0,
                    ),
                    status=410,
                )
            else:
                response = await handler(request)
        except web.HTTPException as exc:
            response = web.json_response({"error": exc.reason}, status=exc.status)
            if exc.status == 408:
                response.force_close()
            for header in ("Allow", "Retry-After"):
                if header in exc.headers:
                    response.headers[header] = exc.headers[header]
        except SelectionError as exc:
            response = web.json_response(
                exc.body,
                status=exc.status,
                headers={"Retry-After": "1"} if exc.status == 503 else None,
            )
        except PublicRequestError as exc:
            response = web.json_response({"error": str(exc)}, status=422)
        except ValueError as exc:
            failure(logger, "dashboard_input_or_data", exc)
            response = web.json_response(
                {
                    "error": "Invalid input or unavailable local data; check inputs and the local log"
                },
                status=422,
            )
        except ArithmeticError as exc:
            failure(logger, "dashboard_arithmetic", exc)
            response = web.json_response(
                {"error": "Calculation unavailable; check inputs and the local log"},
                status=422,
            )
        except (KeyError, StopIteration):
            response = web.json_response({"error": "Unknown selection"}, status=422)
        except Exception as exc:
            failure(logger, "dashboard_request", exc)
            response = web.json_response(
                {"error": "Local data unavailable"}, status=503
            )
        response.headers.update(HEADERS)
        return response

    return guard
