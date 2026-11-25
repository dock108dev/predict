"""Read and export versioned sporting grades for one immutable paper run."""

import sqlite3
from urllib.parse import urlencode

from app.collection import original_receipts
from app.research import experiment, paper_campaigns, workspace
from app.storage import paper_result_queue
from app.storage.store import hashed
from .pipeline import serial

BASE = "/api/research/workspace"
SCHEMA = "predict-paper-results-view-1"
VARIANTS = ("best_venue", "all_venues")
EXPORTS = ("report", "games", "trades")


def read(db, run_id, *, variant, version_id, status_only):
    run = db.execute("""SELECT id, report_revision, game_date,
        public.paper_result_is_run(payload) AS paper
        FROM public.research_workspace_run WHERE id=%s""", (run_id,)).fetchone()
    if run is None or not run["paper"]:
        raise workspace.UnknownSelection("Unknown saved paper run.")
    try:
        state = paper_result_queue.read(db, run_id, result_id=version_id, status_only=status_only)
    except KeyError:
        raise workspace.UnknownSelection("Unknown result version for this paper run.") from None

    state = state or {}
    current = state.get("latest_result_id")
    version = state.get("version")
    report = state.get("report")
    stale = bool(current and (state.get("pending") or state.get("error")))
    if state.get("error"):
        status = "failed"
        reason = state["error"]
    elif state.get("pending"):
        status = "update_pending" if current else "collecting"
        reason = "Retained evidence is queued for automatic grading."
    else:
        status = state.get("state") or ("awaiting_results" if current else "collecting")
        reason = None
    links = {}
    quality = None
    if version:
        path = f"{BASE}/runs/{run_id}/results"
        links = {name: path + "?" + urlencode(dict(version=version["id"], variant=variant, export=name))
                 for name in EXPORTS}
    if report:
        config = db.execute("""SELECT c.payload FROM public.paper_campaign c
            JOIN public.research_workspace_definition d ON d.payload->>'campaign_id'=c.id
            JOIN public.research_workspace_run r ON r.definition_version=d.version
            WHERE r.id=%s""", (run_id,)).fetchone()
        if config:
            document = workspace._run(db, run_id)["payload"]
            tickets = paper_campaigns.analysis_tickets(document, report)
            quality = paper_campaigns.quality(tickets, config["payload"]["bucket_edges"], variant,
                                              inputs=version["id"])
    return serial(dict(schema=SCHEMA, run_id=run_id, date=run["game_date"],
        report_revision=run["report_revision"], variant=variant,
        status=dict(state=status, reason=reason, stale=stale, updated_at=state.get("updated_at"),
                    latest_version=current),
        version=version, versions=state.get("versions", []), report=report, quality=quality, links=links,
        provider_requests=0, orders_submitted=0))


def export(view, kind):
    """Use the persisted version and selected rows without including live queue state."""
    report = view["report"]
    variant = view["variant"]
    result = {name: view[name] for name in ("run_id", "date", "report_revision", "version",
                                            "provider_requests", "orders_submitted")}
    result.update(schema=SCHEMA, export=kind, variant=variant)
    if kind == "report":
        result["report"] = report
        if view.get("quality") is not None:
            result["quality"] = view["quality"]
    elif kind == "games":
        by_game = report["portfolios"][variant]["by_game"]
        result["rows"] = [dict(game, totals=by_game[game["game_id"]]) for game in report["games"]]
    else:
        result["rows"] = report["portfolios"][variant]["tickets"]
    result["manifest"] = dict(bundle_sha256=hashed(result))
    return result


def original_result(db, identity):
    row = db.execute("""SELECT 1 FROM public.ev_experiment_record r
        JOIN public.ev_experiment_game g ON g.id=r.game_id
        WHERE r.id=%s AND r.kind='outcome' AND g.provider='sportsgameodds'""", (identity,)).fetchone()
    digest = None
    if row is not None:
        index = experiment._closure(db, [identity])
        data = experiment._value(index[identity], index)["data"]
        digest = (data.get("source_result") or {}).get("receipt_sha256") or data.get("receipt_sha256")
    else:
        legacy = db.execute("""SELECT payload FROM public.research_record WHERE id=%s
            AND kind='sporting' AND public.paper_result_sgo_event(payload) IS NOT NULL""", (identity,)).fetchone()
        if legacy is not None:
            data = legacy["payload"]
            source = (data.get("data") or {}).get("source_result") or data.get("source_result") or {}
            digest = source.get("receipt_sha256")
    archive = original_receipts.lookup(digest)
    if archive.get("state") == "retained":
        capture = next(item for item in reversed(archive["captures"]) if item["state"] == "retained")
        try:
            metadata, body = original_receipts.read(capture["id"])
            if metadata["receipt_sha256"] == digest:
                return digest, body
        except (OSError, EOFError, ValueError, KeyError, sqlite3.Error):
            pass
    raise workspace.UnknownSelection("Original provider result response was not retained.")
