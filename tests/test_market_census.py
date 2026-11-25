"""Retained event proof and the background census projection."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import AsyncMock, patch

import pytest

from app.collection import original_receipts
from app.collection.current_policy import DEFAULT
from app.collection.sportsgameodds_adapter import Page, parse_page
from app.collection.sportsgameodds_collector import DiscoveryScopeMismatch
from app.collection.sportsgameodds_worker import SportsGameOddsWorker
from app.comparison import fee_mode
from app.dashboard.mens_d1_coverage_api import _coverage_summary
from app.research import ev_movement, experiment, market_census
from app.storage.store import encoded, stamp
from tests.latest_board_fixture import LatestBoardFixture, SOCKET
from tests.pregame_fixture import AT, page as market_page
from tests.sportsgameodds_fixtures import NOW, event as discovery_event


def captured_page(event):
    event_id = event["eventID"]
    source = dict(success=True, data=[event], nextCursor="another-page")
    scope = dict(eventIDs=event_id, bookmakerID="prophetx,fanduel,draftkings", limit=1,
                 oddID="points-home-game-sp-home,points-away-game-sp-away", includeAltLines=True)
    body = encoded(source)
    page = parse_page(body, AT)
    mode = fee_mode.state(False)
    context = SimpleNamespace(fee_mode=mode, price_routes={"prophetx": "sportsgameodds"},
        fee=lambda record, at: fee_mode.zero_fee(record, mode))
    snapshot = ev_movement.build_snapshot(None, page, request_scope=scope,
        dispatch_at=AT, known_at=AT, calculation_context=context)
    return dict(snapshot=snapshot, received_at=AT, known_at=AT), source, scope, body


@pytest.mark.parametrize(("flag", "present", "cell_state", "returned", "unreturned"), [
    (False, True, "no_provider_odds_observed", 0, 0),
    (True, True, "requested_but_unreturned", 0, 6),
    (None, True, "requested_but_unreturned", 0, 6),
    (False, False, "return_unverified", None, None),
])
def test_no_provider_odds_requires_affirmative_exact_return(monkeypatch, flag, present, cell_state, returned, unreturned):
    event = market_page()["data"][0]
    event["odds"] = {}
    if flag is not None:
        event["status"]["oddsPresent"] = flag
    checkpoint, source, _, _ = captured_page(event)
    if not present:
        source["data"] = []
    monkeypatch.setattr(market_census, "_original", lambda _: (dict(state="retained",
        request_scope_matches=True, request_clock_matches=True), source))
    result = market_census.from_checkpoint(checkpoint, "late")
    assert {cell["state"] for cell in result["request_cells"] if cell["requested"]} == {cell_state}
    assert result["summary"]["returned_cells"] == returned
    assert result["summary"]["unreturned_cells"] == unreturned
    assert result["summary"]["observed_offers"] == 0
    assert result["retrieval"]["venue_market_state"] == "unknown_completeness"


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class MarketCensusSQL(LatestBoardFixture):
    async def asyncSetUp(self):
        pass

    async def test_worker_reuses_original_evidence_across_reads_and_restarts(self):
        with self.connect() as db, TemporaryDirectory() as directory, \
                patch.object(original_receipts, "directory", return_value=Path(directory)), \
                patch.object(experiment, "_admit"), \
                patch("app.storage.paper_result_queue._admit"), \
                patch("app.storage.paper_result_queue._late_capture_due", return_value=False):
            event = market_page()["data"][0]
            event["leagueID"] = "NCAAB"
            # One scoped omission with the target event and cursor still returned.
            removed = next(iter(event["odds"].values()))
            removed["byBookmaker"].pop("draftkings")
            checkpoint, _, scope, body = captured_page(event)
            recorded = original_receipts.capture(scope, SimpleNamespace(status=200, body=body, received_at=AT))
            assert recorded["state"] == "retained"
            experiment.discover(db, [dict(provider="sportsgameodds", source_event_id=event["eventID"], league="NCAAB",
                event_id="canonical-game", title="Away at Home", starts_at=event["status"]["startsAt"],
                home="home", away="away", status={})], at=stamp(AT))
            game = db.execute("SELECT id FROM public.ev_experiment_game WHERE source_event_id=%s", (event["eventID"],)).fetchone()
            checkpoint_id, _ = experiment._write(db, "checkpoint", checkpoint, game_id=game["id"], checkpoint="late")
            original = experiment._get(db, checkpoint_id)["payload"]
            assert market_census.campaign_checkpoints(db, stamp(AT)) == []
            compact = dict(requested=dict(bookmakers=scope["bookmakerID"].split(","), odd_ids=scope["oddID"].split(",")))
            report = dict(games=[dict(checkpoint_id=checkpoint_id, status="reconstructed", coverage=compact)])
            coverage = dict(as_of=AT, counts=dict())
            before = _coverage_summary(coverage, [], True, report)["markets"]
            assert before["returned_cells"] is None
            assert before["saved_retrieval_states"] == {"unknown_completeness": 1}

            assert market_census.tick(db) == checkpoint_id
            detail = market_census.for_checkpoint(db, checkpoint_id)
            with self.connect() as resumed, patch.object(original_receipts, "read", side_effect=AssertionError("raw re-read")):
                assert market_census.tick(resumed) is None
                cached = market_census.read_summaries(resumed, [checkpoint_id])
                after = _coverage_summary(coverage, [], True, report, cached)["markets"]
            assert after["requested_cells"] == 6
            assert after["returned_cells"] == 5
            assert after["unreturned_cells"] == 1
            assert after["request_states"] == {"all_requested_events_returned": 1}
            assert after["traversal_states"] == {"cursor_unfollowed": 1}
            assert sum(after["offer_accounting"].values()) == detail["summary"]["observed_offers"]
            assert market_census.apply_summary(detail, cached[checkpoint_id])["summary"] == market_census.summarize_coverage(
                compact, derived=cached[checkpoint_id])
            assert market_census.for_checkpoint(db, checkpoint_id, include_rows=False) == cached[checkpoint_id]
            assert experiment._get(db, checkpoint_id)["payload"] == original
            assert original_receipts.read(recorded["id"])[1] == body

    async def test_durable_discovery_failure_and_exact_id_membership_keep_the_receipts(self):
        service = SimpleNamespace(config=deepcopy(DEFAULT), dispatch=True, globally_stopped=False, paused_sources=set())
        worker = SportsGameOddsWorker(service, now=lambda: NOW)
        worker._publish = AsyncMock()
        worker.state = AsyncMock()
        pages = iter([
            Page((discovery_event(1),), (), "next", "a" * 64),
            Page((discovery_event(1),), (), None, "b" * 64),
            Page((discovery_event(1),), (), "unused", "c" * 64),
        ])
        requests = []

        async def fetch(params, _):
            identity = worker.collector.pull_id
            requests.append((identity, params))
            if len(requests) == 2:
                raise DiscoveryScopeMismatch("fixture scope mismatch")
            return replace(next(pages), pull_id=identity, attempt_id=f"fixture-{len(requests)}", received_at=NOW.isoformat())

        worker.collector = SimpleNamespace(fetch=fetch)
        with patch("app.storage.store.connect", self.connect), patch.object(experiment, "_admit"):
            with pytest.raises(DiscoveryScopeMismatch, match="fixture scope mismatch"):
                await worker.cycle()
            assert worker.metrics["discovery_complete"]["NFL"] is False
            await worker.cycle()
            worker.events["e2"] = discovery_event(2)
            await worker._fetch(worker.params(event_ids=["e1", "e2"]))

        discovery, refresh = requests[0][0], requests[-1][0]
        assert requests[1][0] == requests[2][0] == discovery
        with self.connect() as db:
            cursor_pull = db.execute("SELECT state,details FROM public.market_pull WHERE pull_id=%s", (discovery,)).fetchone()
            assert cursor_pull["state"] == "partial"
            assert cursor_pull["details"]["last_failed_cursor_attempt"] == "DiscoveryScopeMismatch"
            assert cursor_pull["details"]["reason"] == "discovery_cursor_walk_unstable"
            scope = db.execute("SELECT details FROM public.market_pull WHERE pull_id=%s", (refresh,)).fetchone()
            retrieval = scope["details"]["event_retrieval"]
            assert retrieval["omitted_requested_event_ids"] == ["e2"]
            assert retrieval["returned_event_ids"] == ["e1"]
            receipts = db.execute("SELECT receipt_sha256 FROM public.market_pull_receipt WHERE pull_id=%s ORDER BY attempt_id",
                                  (discovery,)).fetchall()
            assert [row["receipt_sha256"] for row in receipts] == ["a" * 64, "b" * 64]
