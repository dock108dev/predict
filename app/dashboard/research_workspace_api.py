"""Browser endpoints for retained paper research and original evidence."""

import asyncio
from hashlib import sha256
import re
from uuid import uuid4

from aiohttp import web

from app.collection.odds_http import BudgetStop
from app.diagnostics import failure
from app.owned_work import joined_thread
from app.research import mens_d1, workspace
from app.research import paper_campaigns
from app.storage.store import connect, encoded
from . import paper_results_view
from .local_security import HEADERS, PublicRequestError, read_json

BASE = "/api/research/workspace"


def _response(value, *, filename=None):
    headers = dict(HEADERS)
    if filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return web.Response(body=encoded(value), content_type="application/json", headers=headers)


def _identity(value):
    if not workspace.HASH.fullmatch(value):
        raise PublicRequestError("Select a saved research identity.")
    return value


def mount(app, *, campaigns_only=False):
    gate = asyncio.Semaphore(2)
    dated_export = asyncio.Lock()
    jobs = {}
    active = None

    async def work(fn, *args, read_only=True, timeout=45, **kwargs):
        def operation():
            with connect() as db:
                db.execute("SET statement_timeout='10s'")
                if not read_only:
                    return fn(db, *args, **kwargs)
                with db.transaction():
                    db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    return fn(db, *args, **kwargs)

        try:
            async with asyncio.timeout(timeout), gate:
                return await joined_thread(__name__, "research_workspace_after_cancellation", operation)
        except workspace.UnknownSelection as exc:
            raise web.HTTPNotFound(reason=str(exc)) from None
        except workspace.SelectionError as exc:
            raise PublicRequestError(str(exc)) from None
        except BudgetStop:
            raise web.HTTPServiceUnavailable(reason="Research storage has insufficient free disk for this replay.") from None
        except TimeoutError:
            raise web.HTTPServiceUnavailable(reason="The research workspace is busy. Retry shortly.",
                                             headers={"Retry-After": "1"}) from None

    async def index(request):
        if request.query:
            raise PublicRequestError("The research workspace takes no filters.")
        return _response(await work(workspace.index))

    async def campaigns(request):
        if request.query:
            raise PublicRequestError('Campaign options belong in the JSON body.')
        if request.method == 'POST':
            body = await read_json(request)
            return _response(await work(paper_campaigns.create, body, read_only=False))
        return _response(dict(campaigns=await work(paper_campaigns.index, active_only=True)))

    async def campaign(request):
        query = request.query
        if (set(query) - {'variant', 'mode', 'export'} or len(query) != len(set(query))
                or query.get('export') not in (None, '1')):
            raise PublicRequestError('Select an experiment sizing mode and portfolio.')
        value = await work(paper_campaigns.view, _identity(request.match_info['campaign_id']),
                           query.get('variant'), mode=query.get('mode'))
        name = f'predict-week-{value["config"]["start_date"]}-{value["mode"]}-{value["variant"]}.json'
        return _response(value, filename=name if query.get('export') else None)

    async def campaign_day(request):
        query = request.query
        if (set(query) - {'variant', 'export'} or len(query) != len(set(query))
                or query.get('export') not in (None, '1')):
            raise PublicRequestError('Select an experiment portfolio.')
        value = await work(paper_campaigns.daily, _identity(request.match_info['campaign_id']),
                           request.match_info['game_date'], query.get('variant'))
        name = f'predict-comparison-{value["date"]}-{value["variant"]}.json'
        return _response(value, filename=name if query.get('export') else None)

    async def run(request):
        query = dict(request.query)
        if query not in ({}, {"export": "1"}):
            raise PublicRequestError("Invalid saved run view.")
        identity = _identity(request.match_info["run_id"])
        value = await work(workspace.run_detail, identity, export=bool(query))
        return _response(value, filename=f'predict-research-{value["run"]["date"]}-{identity[:12]}.json' if query else None)

    async def results(request):
        query = request.query
        variant = query.get("variant", "best_venue")
        export = query.get("export")
        status = query.get("status")
        if (set(query) - {"variant", "version", "export", "status"} or len(query) != len(set(query))
                or variant not in paper_results_view.VARIANTS
                or export is not None and export not in paper_results_view.EXPORTS
                or status is not None and (status != "1" or export)):
            raise PublicRequestError("Select a valid paper results view.")
        run_id = _identity(request.match_info["run_id"])
        version_id = _identity(query["version"]) if "version" in query else None
        value = await work(paper_results_view.read, run_id, variant=variant,
                           version_id=version_id, status_only=status == "1")
        if export is None:
            return _response(value)
        if not value["report"] or value["status"]["stale"] and version_id is None:
            raise web.HTTPConflict(reason="Current results are updating. Select a published version to export it.")
        name = f'predict-paper-{value["date"]}-{variant}-{value["version"]["id"][:12]}-{export}.json'
        return _response(paper_results_view.export(value, export), filename=name)

    async def result_evidence(request):
        if request.query:
            raise PublicRequestError("The original result receipt takes no filters.")
        identity = _identity(request.match_info["result_id"])
        digest, body = await work(paper_results_view.original_result, identity)
        return web.Response(body=body, content_type="application/json", headers={**HEADERS,
            "Content-Disposition": f'attachment; filename="predict-original-{digest}.json"'})

    async def offers(request):
        if request.query:
            raise PublicRequestError("The saved offer export takes no filters.")
        identity = _identity(request.match_info["run_id"])
        fields, games, selected = await work(workspace.offer_export_plan, identity)
        filename = f'predict-mens-d1-offers-{fields["date"]}-{identity[:12]}.json'
        response = web.StreamResponse(headers={**HEADERS, "Content-Type": "application/json",
            "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store, no-transform"})
        before = {key:value for key, value in fields.items() if key < "games"}
        after = {key:value for key, value in fields.items() if key > "games"}
        prefix = encoded(before)[:-1] + b',"games":['
        suffix = b'],' + encoded(after)[1:]
        digest = sha256(prefix)
        await response.prepare(request)
        try:
            await response.write(prefix)
            for position, game in enumerate(games):
                async with dated_export:
                    value = await work(workspace.offer_export_game, game, fields["minimum_ev"], selected,
                                       sizing=fields.get("sizing"), timeout=None)
                body = (b"," if position else b"") + encoded(value)
                digest.update(body)
                await response.write(body)
            # Keep the canonical digest independent of transport and append it only after all games.
            digest.update(suffix)
            await response.write(suffix[:-1] + b',"evidence_sha256":' + encoded(digest.hexdigest()) + b"}")
            await response.write_eof()
        except BaseException:
            if request.transport is not None:
                request.transport.close()
            raise
        return response

    async def replay(request):
        nonlocal active
        if request.query:
            raise PublicRequestError("Replay options belong in the JSON body.")
        body = await read_json(request)
        fields = {"date", "definition_version"}
        if not isinstance(body, dict) or not fields <= set(body) or set(body) - fields - {"assumptions", "experiment"}:
            raise PublicRequestError("Provide the Eastern game date and experiment definition version.")
        version = body["definition_version"]
        if not isinstance(version, str) or not re.fullmatch(r"[0-9a-z-]{1,64}", version):
            raise PublicRequestError("Select an experiment definition version.")
        try:
            day = workspace.game_day(body["date"])
            values = workspace.assumptions(body.get("assumptions", {}))
            registration = workspace.experiment_registration(body["experiment"]) if "experiment" in body else None
        except workspace.SelectionError as exc:
            raise PublicRequestError(str(exc)) from None
        if version == mens_d1.DAILY:
            if values or registration:
                raise PublicRequestError("Daily coverage uses the published paper policy.")
            if active and not active.done():
                current = next(reversed(jobs.values()))
                if current["date"] != day:
                    raise web.HTTPServiceUnavailable(reason="A dated replay is running.", headers={"Retry-After": "5"})
                return web.json_response(current, headers=HEADERS, status=202)
            if len(jobs) >= 8:
                del jobs[next(iter(jobs))]
            identity = uuid4().hex
            job = jobs[identity] = dict(job_id=identity, status_url=f"{BASE}/mens-d1-jobs/{identity}",
                                        date=day, state="queued")
            active = asyncio.create_task(replay_scoped(job))
            return web.json_response(job, headers=HEADERS, status=202)
        return _response(await work(workspace.replay, day, version, values, registration=registration, read_only=False))

    async def replay_scoped(job):
        job["state"] = "running"
        try:
            saved = await work(workspace.replay, job["date"], mens_d1.DAILY, {},
                               read_only=False, timeout=None)
        except PublicRequestError as exc:
            job.update(state="failed", reason=str(exc))
        except web.HTTPException as exc:
            job.update(state="failed", reason=exc.reason)
        except Exception as exc:
            failure(__name__, "mens_d1_scoped_replay", exc)
            job.update(state="failed", reason="The dated replay could not be saved.")
        else:
            job.update(state="succeeded", run_id=saved["run"]["id"])

    async def replay_status(request):
        value = jobs.get(request.match_info["job_id"])
        if value is None:
            raise web.HTTPNotFound(reason="This replay job is unavailable. Select the date to retry.")
        return _response(value)

    async def drain_jobs(_app):
        if active:
            await active

    async def ticket(request):
        if request.query:
            raise PublicRequestError("The saved ticket takes no filters.")
        identity = _identity(request.match_info["run_id"])
        return _response(await work(workspace.ticket_detail, identity, _identity(request.match_info["ticket_id"])))

    async def evidence(request):
        query = dict(request.query)
        if query not in ({}, {"export": "1"}, {"raw": "1"}):
            raise PublicRequestError("Invalid research evidence view.")
        identity = _identity(request.match_info["run_id"])
        game = _identity(request.match_info["game_id"])
        if "raw" in query:
            digest, body = await work(workspace.raw_response, identity, game)
            return web.Response(body=body, content_type="application/json", headers={**HEADERS,
                "Content-Disposition": f'attachment; filename="predict-original-{digest}.json"'})
        value = await work(workspace.game_evidence, identity, game, export=bool(query))
        return _response(value, filename=f"predict-checkpoint-{game[:12]}.json" if query else None)

    if not campaigns_only:
        app.router.add_get(BASE, index)
        app.router.add_post(BASE + "/runs", replay)
    app.router.add_get(BASE + '/campaigns', campaigns)
    app.router.add_post(BASE + '/campaigns', campaigns)
    app.router.add_get(BASE + '/campaigns/{campaign_id}', campaign)
    app.router.add_get(BASE + '/campaigns/{campaign_id}/days/{game_date}', campaign_day)
    app.router.add_get(BASE + "/result-evidence/{result_id}", result_evidence)
    app.router.add_get(BASE + "/mens-d1-jobs/{job_id}", replay_status)
    app.router.add_get(BASE + "/runs/{run_id}", run)
    app.router.add_get(BASE + "/runs/{run_id}/results", results)
    app.router.add_get(BASE + "/runs/{run_id}/offers", offers)
    app.router.add_get(BASE + "/runs/{run_id}/tickets/{ticket_id}", ticket)
    app.router.add_get(BASE + "/runs/{run_id}/evidence/{game_id}", evidence)
    app.on_cleanup.append(drain_jobs)
