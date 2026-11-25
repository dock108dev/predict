"""Dated coverage preserves the difference between source, capture and paper evidence."""

import asyncio
from contextlib import nullcontext
from unittest import skipUnless
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from psycopg.errors import RaiseException
import pytest

from app.dashboard.mens_d1_coverage_api import BASE, _coverage_summary, _facets, _operational_schedule, _paper_usability, coverage_view, mount
from app.dashboard.request_guard import dashboard_guard
from app.research import experiment, issue_dispositions as issues
from app.research.apply_nov23_audit import apply_audit, audit, decision
from app.storage.store import stamp
from tests.latest_board_fixture import SOCKET
from tests.pregame_fixture import PregameFixture


DAY = "2026-11-23"
AS_OF = "2026-11-23T22:00:00Z"
RECEIPT = "d" * 64


def covered_game(game_id="source:cbbd:1", **overrides):
    game = dict(id=game_id, occurrence_id=game_id, title="Away at Home", source_game_id=game_id,
                day_applicability="on_date", eastern_game_date=DAY, scope_state="eligible",
                paper_eligible=True, research_scope="eligible", result_state="final", gender="men",
                capture=dict(state="missed", reason="checkpoint_window_missed", target_at="2026-11-23T21:50:00Z"),
                saved=dict(status="missed"))
    game.update(overrides)
    _operational_schedule(game)
    game["facets"] = _facets(game, game["paper_eligible"])
    game["paper_usability"] = _paper_usability(game, AS_OF, AS_OF)
    return game


def test_reconciled_facets_keep_other_date_and_original_clock_as_audit():
    clocks = dict(state="official_provider_clock_corroborated", evidence=[{"origin":"source", "starts_at":AS_OF}])
    evidence = dict(market_observed=True, starts_at=AS_OF)
    recovered = covered_game(capture=dict(state="refused"), match_state="schedule_conflict", occurrence_schedule=clocks,
        provider_evidence=evidence, saved=dict(status="reconstructed", qualifying=dict(all_venues=0), evaluated_offers=2))
    other = covered_game("source:cbbd:2", paper_eligible=False, research_scope="other_date", day_applicability="other_date",
        eastern_game_date="2026-11-24", match_state="schedule_conflict", occurrence_schedule=clocks,
        provider_evidence=evidence, provider_membership=dict(state="eligible"), retained_scope=dict(state="eligible"),
        provider_results=[dict(status="final")], saved=None)
    assert recovered["match_state"] == "matched"
    assert recovered["raw_occurrence_match_state"] == "schedule_conflict"
    assert recovered["occurrence_schedule"] == clocks
    assert {"expected", "final", "refused", "reconstructed", "zero_qualifiers", "schedule_corroborated"} <= set(recovered["facets"])
    assert "other_date" in other["facets"]
    assert not {"expected", "final", "provider_final", "result_ledger", "retained_eligible", "schedule_corroborated"}.intersection(other["facets"])
    report = dict(games=[recovered["saved"]], as_of=AS_OF)
    value = _coverage_summary(dict(date=DAY, as_of=AS_OF, occurrences=True, counts=dict(unresolved_membership=2,
        source_official_eastern_date_conflicts=1)), [recovered, other], True, report)
    assert value["population"]["raw_source_unresolved_membership"] == 2
    assert value["population"]["reconciled_eligible_games"] == 1
    assert value["population"]["schedule_disputes"] == value["population"]["date_disputes"] == 0
    assert value["reconciliation"]["games_without_qualifiers"] == 1
    assert value["reconciliation"]["original_capture_states"] == dict(refused=1)
    assert value["reconciliation"]["historical_gaps"] == 0


def test_audit_manifest_witnesses_bound_each_gap_and_requested_cell():
    plan = audit()
    gaps = [item for item in plan["issues"] if item.get("reason_code")]
    census = [item for item in plan["issues"] if item["kind"] == "venue_inventory"]
    assert len(gaps) == 7
    assert sum(item["reason_code"] == "late_discovery_no_pre_target_baseline" for item in gaps) == 2
    assert all(decision(item)[0] == issues.GAP for item in gaps)
    assert len({item["checkpoint_id"] for item in census}) == 26
    assert sum(item["requested_cells"] for item in census) == 2184
    assert sum(item["returned_cells"] for item in census) == 2035


def test_issue_write_requires_same_origin_and_rejects_outdated_evidence():
    payload = dict(date=DAY, id=RECEIPT, evidence_revision=RECEIPT, latest_decision_id=None,
                   status=issues.RESOLVED, reason="Retained evidence")

    class WriteConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def transaction(self):
            return nullcontext()

        def execute(self, sql):
            assert sql == "SET LOCAL statement_timeout='10s'"

    async def write_route():
        app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        mount(app)
        with patch('app.dashboard.mens_d1_coverage_api.connect', side_effect=WriteConnection), \
                patch('app.dashboard.mens_d1_coverage_api.decide_issue',
                      side_effect=[dict(status=issues.RESOLVED), issues.StaleDecision('Reload current evidence')]) as save:
            async with TestClient(TestServer(app)) as client:
                path = BASE + '/issues'
                no_origin = await client.post(path, json=payload)
                assert no_origin.status == 403 and not save.called
                origin = {"Origin": str(client.make_url('/')).rstrip('/')}
                invalid = await client.post(path, json=dict(payload, evidence_url="//example.test"), headers=origin)
                assert invalid.status == 422 and not save.called
                saved = await client.post(path, json=payload, headers=origin)
                assert saved.status == 200
                assert (await saved.json())["status"] == issues.RESOLVED
                stale = await client.post(path, json=payload, headers=origin)
                assert stale.status == 409

    asyncio.run(write_route())


def test_current_population_and_saved_offer_denominators_are_independent():
    current = [dict(provider_membership=dict(state="eligible"), capture=dict(state="captured"), facets=[]),
               dict(provider_membership=dict(state="eligible"), capture=dict(state="refused"), facets=[])]
    report = dict(as_of=AS_OF, games=[dict(status="reconstructed", observed_offer_count=7, evaluated_offers=3,
        exclusions=dict(reference_exact_pair_unavailable=2, price_withdrawn=2, below_minimum_ev=3))],
        portfolios={"all_venues": {"tickets": []}})
    value = _coverage_summary(dict(as_of="2026-11-24T11:50:00-05:00", counts=dict(expected=None)), current, True, report)
    assert value["population"]["expected_games"] is None
    assert value["capture"]["current_denominator"] == 2
    assert value["capture"]["current_refusals"] == 1
    assert value["capture"]["saved_denominator"] == value["capture"]["saved_reconstructed"] == 1
    assert value["reference"]["observed_offers"] == 7
    assert value["reference"]["evaluated_offers"] == 3
    assert value["reference"]["reference_gaps"] == 2
    assert value["trade"]["variants"]["all_venues"]["tickets"] == 0


def test_coverage_reads_and_downloads_do_not_dispatch():
    statements = []

    class ReadConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def transaction(self):
            return nullcontext()

        def execute(self, sql):
            statements.append(sql)

    async def read_routes():
        app = web.Application(middlewares=[dashboard_guard(None, logger=__name__)])
        mount(app)
        value = dict(date=DAY, source_state="disabled", population_revision=None, as_of=AS_OF,
                     coverage_summary={"trade": {}}, provider_requests=0, orders_submitted=0)
        with patch('app.dashboard.mens_d1_coverage_api.connect', side_effect=ReadConnection), \
                patch('app.dashboard.mens_d1_coverage_api.coverage_view', return_value=value) as read_coverage, \
                patch('app.dashboard.mens_d1_coverage_api.market_view', side_effect=[dict(checkpoint_id=RECEIPT),
                    (dict(receipt_sha256=RECEIPT), b'{"success":true}')]) as read_markets, \
                patch('app.storage.mens_d1_coverage.read_status', return_value=dict(state="disabled")), \
                patch('app.storage.mens_d1_coverage.read_receipt', return_value=dict(raw_html="<script>ignored</script>")), \
                patch('app.collection.sportsgameodds_transport.SportsgameoddsTransport.fetch', side_effect=AssertionError('provider transport')):
            async with TestClient(TestServer(app)) as client:
                invalid = await client.get(BASE, params=dict(date=DAY, collect="1"))
                assert invalid.status == 422
                assert not statements
                export = await client.get(BASE, params=dict(date=DAY, game="source:occurrence", export="1"))
                assert export.status == 200
                assert (await export.json()) == value
                assert export.headers['Content-Disposition'].endswith(f'"predict-mens-d1-{DAY}.json"')
                assert read_coverage.call_args.args[1:] == (DAY, None, 'source:occurrence')
                summary = await client.get(BASE, params=dict(date=DAY, summary="1"))
                assert (await summary.json())["coverage_summary"] == value["coverage_summary"]
                assert (await summary.json()).get("population_revision") is None
                request = dict(date=DAY, game="source:occurrence", run=RECEIPT, version="saved")
                malformed = await client.get(f'{BASE}/market-census', params=dict(request, collect="1"))
                assert malformed.status == 422
                census = await client.get(f'{BASE}/market-census', params=dict(request, export="1"))
                assert census.status == 200
                assert (await census.json())["checkpoint_id"] == RECEIPT
                assert read_markets.call_args.args[1:] == (DAY, RECEIPT, 'source:occurrence', 'saved', False)
                raw = await client.get(f'{BASE}/market-census', params=dict(request, raw="1"))
                assert await raw.read() == b'{"success":true}'
                assert raw.headers['Content-Disposition'].endswith(f'{RECEIPT}.json"')
                assert read_markets.call_args.args[1:] == (DAY, RECEIPT, 'source:occurrence', 'saved', True)
                source = await client.get(f'{BASE}/receipts/{RECEIPT}')
                assert source.headers['Content-Disposition'].startswith('attachment')
                assert source.content_type == 'application/json'
                assert (await source.json())['raw_html'] == '<script>ignored</script>'
                status = await client.get(BASE + '/status')
                assert (await status.json())['provider_requests'] == 0
        assert statements == ['SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY',
                              "SET LOCAL statement_timeout='10s'"] * 6

    asyncio.run(read_routes())


@skipUnless(SOCKET, "Disposable PostgreSQL required")
class MensD1CoverageSQL(PregameFixture):
    async def test_audit_import_is_read_only_until_applied_and_never_replaces_a_decision(self):
        value = dict(date=DAY, as_of=AS_OF, expected_games=None)
        game = covered_game("source:cbbd:375251")
        identity = issues.issue_id(DAY, "capture", game["id"])

        def retained_view(db, *_):
            rows, _ = issues.list_issues(db, value, [game], None)
            return dict(run=dict(report_revision=RECEIPT), issues=rows, games=[game])

        with self.connect() as db, patch('app.research.apply_nov23_audit.coverage_view', side_effect=retained_view):
            case = next(item for item in retained_view(db)["issues"] if item["id"] == identity)
            retained = dict(game_id=game["id"], kind="capture", evidence_revision=case["evidence_revision"],
                            reason_code="checkpoint_window_missed", target_at=game["capture"]["target_at"])
            plan = dict(date=DAY, run_id=RECEIPT, run_report_revision=RECEIPT, issues=[retained])
            dry_run = apply_audit(db, plan)
            assert dry_run["decisions"] == {"ready":1, issues.GAP:1}
            assert not db.execute("SELECT 1 FROM public.research_issue_disposition WHERE issue_id=%s", (identity,)).fetchone()
            with db.transaction():
                issues.lock(db, identity)
                authored = issues.record(db, DAY, case, issues.GAP, "Signed-in decision", "owner")
            from_owner = apply_audit(db, plan, apply=True)
            assert from_owner["decisions"] == {"existing_history":1, issues.GAP:1}
            row = db.execute("SELECT id, actor FROM public.research_issue_disposition WHERE issue_id=%s", (identity,)).fetchall()
            assert row == [dict(id=authored["latest_decision_id"], actor="owner")]

    async def test_append_only_decisions_and_relevant_replacement_evidence(self):
        value = dict(date=DAY, as_of=AS_OF, expected_games=None)
        original = covered_game()
        identity = issues.issue_id(DAY, "capture", original["id"])

        def capture(db, game):
            rows, _ = issues.list_issues(db, value, [game], None)
            return next(row for row in rows if row["id"] == identity)

        with self.connect() as db, db.transaction():
            issues.lock(db, identity)
            first = capture(db, original)
            closed = issues.record(db, DAY, first, issues.GAP, "Original window missed", "owner")
            assert closed["status"] == issues.GAP
            assert issues.OPEN not in closed["allowed_statuses"]
            with pytest.raises(issues.StaleDecision):
                issues.require_current(closed, first)
            with pytest.raises(issues.InvalidDecision):
                issues.record(db, DAY, closed, issues.OPEN, "No authentic evidence", "owner")
            assert capture(db, original)["history"] == closed["history"]
            with pytest.raises(RaiseException), db.transaction():
                db.execute("UPDATE public.research_issue_disposition SET reason='rewritten' WHERE issue_id=%s", (identity,))

            genuine = covered_game(capture=dict(original["capture"], state="captured", frozen_id=RECEIPT))
            changed = capture(db, genuine)
            assert changed["status"] == issues.OPEN and changed["evidence_changed"]
            assert issues.GAP not in changed["allowed_statuses"]
            assert genuine["paper_usability"] == "missing"  # Original saved report remains pinned.
            resolved = issues.record(db, DAY, changed, issues.RESOLVED, "Original in-window receipt retained", "owner")
            reopened = issues.record(db, DAY, resolved, issues.OPEN, "Review clock alignment", "owner")
            assert [row["status"] for row in capture(db, genuine)["history"]] == [issues.GAP, issues.RESOLVED, issues.OPEN]
            assert reopened["history"][-1]["supersedes"] == resolved["latest_decision_id"]

    async def test_distinct_source_capture_and_saved_populations_with_exact_clock_links(self):
        with self.connect() as db, patch.object(experiment, '_admit', return_value=None):
            starts = "2026-11-23T20:00:00Z"
            experiment.discover(db, [dict(provider='sportsgameodds', source_event_id='provider-event', league='NCAAB',
                event_id='canonical-game', title='Away at Home', starts_at=starts, home='home', away='away', status={})],
                at=stamp("2026-11-23T14:00:00Z"))
            game = db.execute("SELECT * FROM public.ev_experiment_game WHERE source_event_id='provider-event'").fetchone()
            target, deadline = "2026-11-23T19:50:00Z", "2026-11-23T19:51:00Z"
            received = "2026-11-23T19:50:15Z"
            checkpoint, _ = experiment._write(db, "checkpoint", dict(schedule_id=game['schedule_id'], snapshot={},
                received_at=received, requested_at=target, known_at="2026-11-23T19:50:16Z", target_at=target, deadline_at=deadline,
                scope=dict(bookmakers=[f'fixture-book-{index}' for index in range(10)])),
                game_id=game['id'], checkpoint='late')
            assert db.execute("""SELECT payload#>>'{value,$ev_checkpoint_envelope,metadata,$ev_checkpoint_ref}' id
                FROM public.ev_experiment_record WHERE id=%s""", (checkpoint,)).fetchone()['id']
            db.execute("UPDATE public.ev_experiment_game SET late_id=%s WHERE id=%s", (checkpoint, game['id']))
            db.execute("UPDATE public.ev_experiment_task SET state='captured',result_id=%s WHERE game_id=%s AND checkpoint='late'",
                       (checkpoint, game['id']))
            scope = dict(as_of=AS_OF, population_revision='revision', result_only=[], provider_only=[
                dict(provider_event_id='provider-final', match_state='provider_only', result_state='provider_final',
                     starts_at=starts, provider_results=[dict(status='final')], retained_scope=dict(state='eligible')),
                dict(provider_event_id='provider-pending', match_state='provider_only', result_state='unresolved',
                     starts_at='2026-11-23T23:00:00Z', retained_scope=dict(state='eligible')),
                dict(provider_event_id='provider-unresolved', match_state='provider_only', result_state='unresolved',
                     starts_at=starts, retained_scope=dict(state='unresolved'))],
                games=[dict(source_game_id='source-captured', gender='men', scope_state='eligible',
                            match_state='matched', schedule=dict(starts_at=starts), result_state='final', provider_event_id='provider-event'),
                       dict(source_game_id='source-untracked', gender='men', scope_state='eligible',
                            match_state='source_only', schedule=dict(starts_at=starts), result_state='pending'),
                       dict(source_game_id='source-excluded', gender='women', scope_state='excluded',
                            match_state='excluded', schedule=dict(starts_at=starts))])
            run = dict(id='b' * 64)
            saved_report = dict(population=dict(games=[dict(source_game_id='source-captured', game_id=game['id'],
                provider_event_id='provider-event', scope_state='eligible', scope_reason='both_members')]),
                games=[dict(game_id=game['id'], status='captured', evaluated_offers=3, checkpoint_id=checkpoint)],
                portfolios={name:dict(tickets=[dict(game_id=game['id'], id='ticket',
                    times=dict(source_at='2026-11-23T19:45:00Z', received_at=received))])
                    for name in ('best_venue','all_venues')})
            with patch('app.storage.mens_d1_coverage.read_coverage', return_value=scope), \
                    patch('app.dashboard.mens_d1_coverage_api._saved', return_value=([run], run, saved_report)):
                data = coverage_view(db, DAY, None, 'source:source-captured')
        rows = {row['source_game_id']:row for row in data['games'] if 'source_game_id' in row}
        assert data['run'] is None
        assert data['analysis_run']['id'] == run['id']
        captured = rows['source-captured']
        assert captured['capture']['frozen_received_at'] == received
        assert captured['capture']['frozen_requested_at'] == target
        assert captured['capture']['frozen_known_at'] == "2026-11-23T19:50:16Z"
        assert captured['capture']['frozen_persisted_at'] is not None
        assert captured['capture']['state'] == 'captured'
        assert captured['checkpoint_export'].startswith('/api/research/experiment?export=1')
        clocks = captured['ticket_clocks']['best_venue'][0]['times']
        assert clocks['source_at'] != clocks['received_at']
        assert rows['source-untracked']['capture']['state'] == 'no_task'
        assert rows['source-untracked']['saved'] is None
        assert data['facets']['expected'] == 2
        assert data['facets']['frozen'] == data['facets']['final'] == data['facets']['excluded'] == 1
        assert data['facets']['provider_final'] == data['facets']['provider_pending'] == data['facets']['provider_result_unresolved'] == 1
        assert data['facets']['provider_scope_eligible'] == 2
        assert data['offer_counts'] == dict(evaluated=3, qualifying_best_venue=1, qualifying_all_venues=1)
