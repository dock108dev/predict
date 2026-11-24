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
from tests.latest_board_fixture import SOCKET
from tests.test_paper_experiments import linear, priced
from tests.test_paper_experiments_sql import ResearchWorkspaceFixture
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


def test_shared_receipt_reconstructs_only_the_claimed_member():
    game, checkpoint, attempt, metadata, raw = source()
    body = json.loads(raw)
    sibling = deepcopy(body["data"][0])
    sibling["eventID"] = "other"
    body["data"].append(sibling)
    raw = json.dumps(body).encode()
    details = attempt["details"]
    details["request_scope"].update(limit=1, bookmakerID="kalshi")
    physical = dict(details["request_scope"], eventIDs="event,other,unreturned", limit=3)
    details.update(receipt_sha256=sha256(raw).hexdigest(),
                   batch=dict(request_scope=physical, size=3, response_event_ids=["event", "other"]))
    metadata.update(request_scope=physical, receipt_sha256=details["receipt_sha256"])

    recovered = recovery.reconstruct(game, checkpoint, "attempt-record", attempt, metadata, raw)
    snapshot = recovered["snapshot"]
    assert snapshot["source_event"]["event_id"] == "event"
    assert {quote["event_id"] for quote in snapshot["raw_quotes"]} == {"event"}
    assert snapshot["request_scope"]["eventIDs"] == "event"
    assert snapshot["acquisition"]["batch"]["request_scope"]["eventIDs"] == "event,other,unreturned"

    different_filter = deepcopy(attempt)
    different_filter["details"]["request_scope"]["bookmakerID"] = "novig"
    assert not recovery.eligible_attempt(game, checkpoint, different_filter, metadata)
    not_returned = deepcopy(attempt)
    not_returned["details"]["batch"]["response_event_ids"] = ["other"]
    assert not recovery.eligible_attempt(game, checkpoint, not_returned, metadata)
    contradictory = deepcopy(attempt)
    contradictory["details"]["batch"]["response_event_ids"].append("unreturned")
    with pytest.raises(ValueError, match="receipt_mismatch"):
        recovery.reconstruct(game, checkpoint, "attempt-record", contradictory, metadata, raw)


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
class DatedD1RecoverySQL(ResearchWorkspaceFixture):
    async def test_dated_d1_recovery_keeps_failed_task_and_uses_exact_receipt(self):
        from app.research import mens_d1

        _, _, attempt, metadata, raw = source()
        identity = metadata['id'] = 'e' * 64
        details = dict(attempt['details'], original_response={'id':identity})
        day = '2026-11-23'
        game = self.game('event', '2026-11-23T18:00:00Z')
        population = dict(kind='reconciled_occurrences', revision='dated-slate', membership_version='season',
                          games=[dict(provider_event_id='event', occurrence_id='source:cbbd:game', scope_state='eligible')])
        with self.connect() as db, patch.object(mens_d1, 'daily_population',
                side_effect=lambda db, day: deepcopy(population)), patch.object(recovery.original_receipts,
                'read', return_value=(metadata, raw)):
            experiment.discover(db, [game], at=self.at)
            self.capture(db, 'early', game)
            self.advance(db, stamp('2026-11-23T17:50:00Z'))
            task = experiment.due(db, at=self.at)[0]
            self.advance(db, stamp('2026-11-23T17:51:01Z'))
            failed = experiment.fail_checkpoint(db, task['game_id'], 'late', 'experiment_checkpoint_window_missed',
                token=task['token'], at=self.at, dispatched=True, details=details)
            assert failed['state'] == 'missed'
            assert recovery.record_d1(db, day, 'f' * 64)['eligible_recoveries'] == 0
            preview = recovery.record_d1(db, day, identity)
            assert preview['eligible_recoveries'] == 1 and not preview['checkpoint_ids']
            before = workspace.replay(db, day, mens_d1.DAILY, {})
            retained = recovery.record_d1(db, day, identity, commit=True)
            assert recovery.record_d1(db, day, identity, commit=True) == retained
            after = workspace.replay(db, day, mens_d1.DAILY, {})
            assert after['run']['supersedes'] == before['run']['id']
            recovered = after['report']['games'][0]
            assert (recovered['status'], recovered['original_capture_status']) == ('reconstructed', 'missed')
            assert recovered['checkpoint_id'] == retained['checkpoint_ids'][task['game_id']]
            assert recovered['recovery']['receipt_id'] == identity
            assert db.execute('SELECT late_id FROM ev_experiment_game WHERE id=%s', (task['game_id'],)).fetchone()['late_id'] is None
            assert workspace.replay(db, day, mens_d1.DAILY, {})['run']['id'] == after['run']['id']


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class RecoverySQL(ResearchWorkspaceFixture):
    async def test_recovery_is_separate_idempotent_and_does_not_grade_results(self):
        from psycopg.types.json import Jsonb
        from app.storage.store import encoded, hashed

        with self.connect() as db:
            game = self.game("retained-raw", "2026-11-23T18:00:00Z")
            experiment.discover(db, [game], at=self.at)
            self.capture(db, "early", game)
            self.advance(db, stamp("2026-11-23T17:50:00Z"))
            task = experiment.due(db, at=self.at)[0]
            db.execute("UPDATE ev_experiment_task SET state='refused',last_reason='research_retention_capacity' WHERE game_id=%s AND checkpoint='late'", (task['game_id'],))
            db.commit()
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
                policy = dict(deepcopy(parent["policy"]), recovered_checkpoints={original["id"]:identity},
                              defer_results=True, recovery_version=recovery.VERSION)
                payload = {k:v for k,v in parent.items() if k not in ("version","id","recorded_at","supersedes")}
                payload["policy"] = policy
                payload["designation"] = "retrospective_raw_recovery"
                version = hashed(payload)
                db.execute("""INSERT INTO research_workspace_definition(version,id,payload_bytes,payload)
                    VALUES(%s,%s,%s,%s)""", (version,version,len(encoded(payload)),Jsonb(payload)))
            with patch.object(paper.math, "calculate", side_effect=linear):
                strict = workspace.replay(db, "2026-11-23", workspace.PILOT_VERSION, {})
                first = workspace.replay(db, "2026-11-23", version, {})
                with patch.object(paper, "report", side_effect=AssertionError("unchanged evidence must reopen without quote decoding")):
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
            db.commit()
            definition = workspace._definition(db,version)
            for query in (
                "UPDATE ev_experiment_task SET state='missed' WHERE game_id=%s AND checkpoint='late'",
                "UPDATE ev_experiment_task SET target_at=target_at+interval '1 second' WHERE game_id=%s AND checkpoint='late'",
                "UPDATE ev_experiment_game SET event=jsonb_set(event,'{title}',to_jsonb('Changed title'::text)) WHERE id=%s",
            ):
                with db.transaction(force_rollback=True):
                    db.execute(query,(original['id'],))
                    assert workspace._unchanged_recovery_run(db,'2026-11-23',definition) is None
            db.commit()
            with db.transaction():
                experiment._write(db, "attempt", dict(at="2026-11-23T17:50:10Z",reason="new_evidence"),
                                  game_id=original["id"], checkpoint="late")
            with patch.object(paper.math, "calculate", side_effect=linear):
                changed = workspace.replay(db, "2026-11-23", version, {})
            assert changed["run"]["id"] != first["run"]["id"]
            assert changed["report"]["games"][0]["attempt_ids"] != first["report"]["games"][0]["attempt_ids"]
