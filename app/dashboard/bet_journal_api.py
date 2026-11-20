"""Personal journal HTTP routes and a provider-free background quote sampler."""

import asyncio
import csv
import io
from pathlib import Path

from aiohttp import web

from .bet_journal import Journal, Conflict
from .local_security import read_json


def mount(app, *, journal=None, monitor=True):
    journal = journal or Journal()

    async def page(request):
        return web.FileResponse(
            Path(__file__).parent / "opportunity_static/current/bet-journal.html"
        )

    async def records(request):
        if request.method == "POST":
            body = await read_json(request)
            if not isinstance(body, dict) or set(body) != {"kind", "snapshot"}:
                return web.json_response(
                    dict(error="Supply the opportunity kind and original snapshot"),
                    status=422,
                )
            try:
                key = await asyncio.to_thread(
                    journal.observe, body["kind"], body["snapshot"], manual=True
                )
            except (ValueError, KeyError, TypeError):
                return web.json_response(
                    dict(error="The original opportunity snapshot is incomplete"),
                    status=422,
                )
            try:
                result = await asyncio.to_thread(journal.get, key)
            except Exception as exc:
                # observe committed successfully. A later read failure cannot
                # truthfully report a failed save or encourage another bet.
                from app.diagnostics import failure
                failure(__name__, "saved_quote_read", exc)
                result = dict(id=key, quote_saved=True, details_available=False)
            return web.json_response(result, status=201)
        download = request.query.get("download")
        if download and download not in ("json", "csv"):
            return web.json_response(
                dict(error="Choose a JSON or CSV export"), status=422
            )
        filters = {
            key: request.query.get(key, "") for key in ("kind", "decision", "search")
        }
        if download:
            # One SQLite read transaction owns membership, corrections, quotes
            # and metrics. Concurrent saves cannot shift offset-based pages.
            snapshot = await asyncio.to_thread(
                journal.export, history=download == "json"
            )
            histories = snapshot["entries"]
            entries = [record["entry"] for record in histories]
            if download == "json":
                return web.json_response(
                    dict(
                        schema="predict-personal-journal-1",
                        entries=histories,
                        monitor=snapshot["monitor"],
                    ),
                    headers={
                        "Content-Disposition": 'attachment; filename="predict-bet-journal.json"'
                    },
                )
            return export_csv(entries)
        result = await asyncio.to_thread(
            journal.list,
            limit=request.query.get("limit", 100),
            offset=request.query.get("offset", 0),
            view=request.query.get("view", "log"),
            defer_observed=request.query.get("defer_observed") == "1",
            **filters,
        )
        return web.json_response(result)

    def export_csv(entries):
        output = io.StringIO()
        fields = [
            "id",
            "kind",
            "decision",
            "created_at",
            "game",
            "notes",
            "observed_ev",
            "entry_ev",
            "close_ev",
            "entry_arb_return",
            "close_arb_return",
            "realized_profit_usd",
            "realized_roi",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for entry in entries:
            row = {
                field: entry.get(field, entry["metrics"].get(field, ""))
                for field in fields
            }
            row["game"] = entry["snapshot"].get("game", "")
            # Notes and names remain data when opened in a spreadsheet.
            row = {
                k: "'" + v
                if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r"))
                else v
                for k, v in row.items()
            }
            writer.writerow(row)
        return web.Response(
            text=output.getvalue(),
            content_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="predict-bet-journal.csv"'
            },
        )

    async def record(request):
        try:
            if request.method == "DELETE":
                body = await read_json(request)
                if not isinstance(body, dict) or set(body) != {"revision"}:
                    raise ValueError(
                        "Supply the current revision to delete this record"
                    )
                await asyncio.to_thread(
                    journal.delete, request.match_info["id"], body["revision"]
                )
                return web.json_response(dict(deleted=True))
            elif request.method == "POST":
                body = await read_json(request)
                result = await asyncio.to_thread(
                    journal.update, request.match_info["id"], body
                )
            else:
                result = await asyncio.to_thread(
                    journal.get, request.match_info["id"], history=True
                )
        except Conflict as exc:
            return web.json_response(dict(error=str(exc)), status=409)
        except KeyError:
            return web.json_response(dict(error="Unknown journal entry"), status=404)
        except (ValueError, TypeError) as exc:
            return web.json_response(
                dict(
                    error=str(exc)
                    if type(exc) is ValueError
                    else "Invalid trade inputs"
                ),
                status=422,
            )
        return web.json_response(result)

    async def preview(request):
        try:
            body = await read_json(request)
            result = await asyncio.to_thread(
                journal.preview, request.match_info["id"], body
            )
        except KeyError:
            return web.json_response(dict(error="Unknown journal entry"), status=404)
        except (ValueError, TypeError):
            return web.json_response(
                dict(
                    error="Enter valid stakes, pre-fee prices and one outcome for each leg."
                ),
                status=422,
            )
        return web.json_response(result)

    app.router.add_post("/api/bet-journal/{id}/preview", preview)
    app.router.add_get("/my-bets", page)
    app.router.add_get("/api/bet-journal", records)
    app.router.add_post("/api/bet-journal", records)
    app.router.add_get("/api/bet-journal/{id}", record)
    app.router.add_post("/api/bet-journal/{id}", record)
    app.router.add_delete("/api/bet-journal/{id}", record)

    if monitor:

        async def lifecycle(app):
            async def run():
                from .bet_journal_monitor import poll

                while True:
                    try:
                        await asyncio.to_thread(poll, journal=journal)
                    except Exception:
                        from app.diagnostics import failure
                        import sys

                        failure(__name__, "personal_quote_monitor", sys.exception())
                    await asyncio.sleep(1)

            task = asyncio.create_task(run(), name="predict-personal-quote-monitor")
            yield
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        app.cleanup_ctx.append(lifecycle)
