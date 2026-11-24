"""Retrospective raw evidence admission and separation from strict captures."""
from copy import deepcopy
from hashlib import sha256
import json
import sqlite3
from unittest import skipUnless
from unittest.mock import patch

import pytest

from app.research import experiment, paper, recovery, workspace
from app.storage.store import stamp
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.test_paper_experiments import linear, priced
from tests.test_paper_experiments_sql import ResearchWorkspaceSQL
from tests.test_sportsgameodds_adapter import response


def source():
    game = dict(id="game", schedule_id="schedule", event=dict(source_event_id="event",
        starts_at="2026-11-23T18:00:00Z"))
    checkpoint = dict(target_at="2026-11-23T17:50:00Z", deadline_at="2026-11-23T17:51:00Z")
    body = response()
    body["data"][0]["leagueID"] = "NCAAB"
    body["data"][0]["status"]["startsAt"] = game["event"]["starts_at"]
    books = body["data"][0]["odds"]["points-home-game-sp-home"]["byBookmaker"]
    books["kalshi"] = books.pop("book")
    books["kalshi"]["lastUpdatedAt"] = "2026-11-23T17:49:59Z"
    raw = json.dumps(body).encode()
    scope = dict(eventIDs="event", includeAltLines=True)
    details = dict(dispatch_at="2026-11-23T17:50:01Z", received_at="2026-11-23T17:50:02Z",
        known_at="2026-11-23T17:50:03Z", request_scope=scope, receipt_sha256=sha256(raw).hexdigest(),
        pull_id="pull", attempt_id="http-attempt")
    attempt = dict(schedule_id="schedule", dispatched=True, reason="research_retention_capacity", details=details)
    metadata = dict(id="raw-receipt", state="retained", provider="sportsgameodds", request_scope=scope,
        received_at=details["received_at"], receipt_sha256=details["receipt_sha256"])
    return game, checkpoint, attempt, metadata, raw


@pytest.mark.parametrize("field,value", [
    ("received_at", "2026-11-23T17:49:59Z"), ("received_at", "2026-11-23T17:51:01Z"),
    ("dispatch_at", "2026-11-23T17:49:59Z"), ("receipt_sha256", "wrong"),
])
def test_wrong_clock_or_hash_cannot_enter_recovery(field, value):
    game, checkpoint, attempt, metadata, _ = source()
    attempt["details"][field] = value
    assert not recovery.eligible_attempt(game, checkpoint, attempt, metadata)


def test_original_raw_bytes_rebuilt_without_current_fees_or_prices():
    game, checkpoint, attempt, metadata, raw = source()
    with patch("app.storage.current_pregame.CalculationContext", side_effect=AssertionError("current settings forbidden")):
        value = recovery.reconstruct(game, checkpoint, "attempt-record", attempt, metadata, raw)
    assert value["status"] == "reconstructed"
    assert value["source_kind"] == "retrospective_raw_t10"
    assert value["snapshot"]["receipt_sha256"] == metadata["receipt_sha256"]
    assert value["snapshot"]["fee_mode"]["enabled"] is False
    assert value["snapshot"]["offers"]
    assert value["recovery"]["attempt_id"] == "attempt-record"
    assert "not EV known" in value["recovery"]["calculation"]
    assert recovery.reconstruct(game, checkpoint, "attempt-record", attempt, metadata, raw) == value
    with pytest.raises(ValueError, match="receipt_mismatch"):
        recovery.reconstruct(game, checkpoint, "attempt-record", attempt, metadata, raw + b" ")


@pytest.mark.parametrize("rows,expected", [(1, True), (2, False), (0, False)])
def test_old_failure_requires_unique_exact_manifest_receipt(rows, expected):
    game, checkpoint, attempt, metadata, raw = source()
    attempt["details"] = dict(requested_at="2026-11-23T17:50:01Z", received_at=metadata["received_at"])
    manifest = sqlite3.connect(":memory:")
    manifest.row_factory = sqlite3.Row
    manifest.execute("CREATE TABLE receipt(received_at TEXT,metadata TEXT)")
    for _ in range(rows):
        manifest.execute("INSERT INTO receipt VALUES (?,?)", (metadata["received_at"],json.dumps(metadata)))
    # A nearby receipt must never stand in for the exact original time.
    manifest.execute("INSERT INTO receipt VALUES (?,?)", ("2026-11-23T17:50:04Z",json.dumps(metadata)))
    with patch.object(recovery.original_receipts, "readonly", return_value=manifest), patch.object(
            recovery.original_receipts, "read", return_value=(metadata,raw)):
        value = recovery.receipt_for_attempt(game, attempt, "immutable-attempt")
    assert bool(value) == expected
    if value:
        enriched, original, _ = value
        assert recovery.eligible_attempt(game, checkpoint, enriched, original)
        assert enriched["details"]["pull_id"].startswith("retrospective-single-response:")
        assert "pull_id" not in attempt["details"]


def test_recovery_selects_final_response_before_calculating_any_ev():
    game, cp, attempt, metadata, raw = source()
    attempts = {key:dict(deepcopy(attempt), fixture_key=key) for key in ("initial", "final")}
    class DB:
        def execute(self, query, params):
            return [dict(game, event=dict(game["event"], title="Game"))] if "FROM public.ev_experiment_game" in query else [{"id":key} for key in attempts]
    def bound(_game, item, _identity):
        clock = "2026-11-23T17:50:02Z" if item["fixture_key"] == "initial" else "2026-11-23T17:50:03Z"
        return item, dict(metadata, received_at=clock), raw
    with patch.object(experiment, "_checkpoint_view", return_value=dict(cp, status="refused")), patch.object(
            experiment, "_closure", side_effect=lambda db, roots:{roots[0]:attempts[roots[0]]}), patch.object(
            experiment, "_value", side_effect=lambda row,index:row), patch.object(
            recovery, "receipt_for_attempt", side_effect=bound), patch.object(
            recovery, "eligible_attempt", return_value=True), patch.object(
            recovery, "reconstruct", return_value={"offers":[]}) as calculate:
        recovered, dispositions = recovery.prepare(DB(), "2026-11-23")
    assert recovered == {game["id"]:{"offers":[]}}
    assert dispositions[0]["status"] == "reconstructed"
    assert calculate.call_count == 1
    assert calculate.call_args.args[2] == "final"


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class RecoverySQL(LatestBoardFixture):
    asyncSetUp = ResearchWorkspaceSQL.asyncSetUp
    advance = ResearchWorkspaceSQL.advance
    game = ResearchWorkspaceSQL.game
    capture = ResearchWorkspaceSQL.capture

    async def test_recovery_is_separate_idempotent_and_does_not_grade_results(self):
        from psycopg.types.json import Jsonb
        from app.storage.store import encoded, hashed

        with self.connect() as db:
            game = self.game("retained-raw", "2026-11-23T18:00:00Z")
            experiment.discover(db, [game], at=self.at)
            self.capture(db, "early", game)
            self.advance(db, stamp("2026-11-23T17:50:00Z"))
            task = experiment.due(db, at=self.at)[0]
            original = db.execute("SELECT * FROM ev_experiment_game WHERE id=%s", (task["game_id"],)).fetchone()
            cp = experiment._checkpoint_view(db, original, "late")
            snapshot = dict(event=dict(title="Away at retained-raw", scheduled_start=game["starts_at"]),
                offers=[priced(), priced(ev=".05", venue="polymarket_us")], coverage=dict(incomplete=True))
            value = dict(status="reconstructed", source_kind="retrospective_raw_t10", schedule_id=original["schedule_id"],
                target_at=cp["target_at"], deadline_at=cp["deadline_at"], received_at="2026-11-23T17:50:02Z",
                recovery=dict(version=recovery.VERSION), snapshot=snapshot)
            with db.transaction():
                identity, _ = experiment._write(db, "checkpoint", value, game_id=original["id"], checkpoint="late")
                parent = workspace._definition(db, workspace.PILOT_VERSION)
                policy = dict(deepcopy(parent["policy"]), recovered_checkpoints={original["id"]:identity}, defer_results=True)
                payload = {k:v for k,v in parent.items() if k not in ("version","id","recorded_at","supersedes")}
                payload["policy"] = policy
                version = hashed(payload)
                db.execute("""INSERT INTO research_workspace_definition(version,id,payload_bytes,payload)
                    VALUES(%s,%s,%s,%s)""", (version,version,len(encoded(payload)),Jsonb(payload)))
            with patch.object(paper.math, "calculate", side_effect=linear):
                strict = workspace.replay(db, "2026-11-23", workspace.PILOT_VERSION, {})
                first = workspace.replay(db, "2026-11-23", version, {})
                second = workspace.replay(db, "2026-11-23", version, {})
            assert first["run"]["id"] == second["run"]["id"]
            assert strict["report"]["portfolios"]["all_venues"]["count"] == 0
            assert first["run"]["coverage"]["captured_games"] == 0
            assert first["run"]["coverage"]["reconstructed_games"] == 1
            assert first["report"]["portfolios"]["all_venues"]["count"] == 2
            assert first["report"]["portfolios"]["best_venue"]["count"] == 1
            assert first["report"]["portfolios"]["all_venues"]["resolved"] == 0
            assert first["report"]["games"][0]["outcome_id"] is None
            assert db.execute("SELECT late_id FROM ev_experiment_game WHERE id=%s", (original["id"],)).fetchone()["late_id"] is None
            ticket = first["report"]["portfolios"]["all_venues"]["tickets"][0]
            detail = workspace.ticket_detail(db, first["run"]["id"], ticket["id"])
            assert detail["evidence"]["checkpoint"]["source_kind"] == "retrospective_raw_t10"
            assert detail["ticket"]["grading"]["reason"] == "results_integration_deferred"
