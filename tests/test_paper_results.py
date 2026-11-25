from copy import deepcopy
from fractions import Fraction
from hashlib import sha256

from app.research import paper, paper_results as results
from app.storage.store import encoded


START = "2026-11-23T17:30:00+00:00"
OBSERVED = "2026-11-24T10:30:00+00:00"
HOME = "league:home"
AWAY = "league:away"
ODDS_ID = "native-event"


def game(game_id="game", status="captured", league="NCAAB"):
    frozen = dict(source_event_id=ODDS_ID, league=league, home=HOME, away=AWAY,
                  title="Away at Home", starts_at=START)
    entry = dict(game_id=game_id, title=frozen["title"], status=status, starts_at=START,
                 schedule_id="frozen-schedule" if status == "captured" else None)
    return entry, frozen


def ticket(ticket_id, *, game_id="game", venue="novig", side="home", family="spread", line="-14.5",
           league="NCAAB", period="full_game"):
    identity = dict(event=game_id, family=family, line=line, outcome=side, period=period, provider="sportsgameodds",
                    settlement=dict(rules="sportsgameodds-unverified-1", outcome_cardinality=2,
                                    result_policy=f"sportsgameodds-unverified-1:{family}"))
    saved = dict(id=ticket_id, label="East Carolina", identity=identity, game_id=game_id, venue=venue,
                 posted_odds="+669", probability="5/32", ev="129/640", cash_commitment_usd="57921/769")
    source = dict(provider="sportsgameodds", native_event_id=ODDS_ID, native_line=line,
                  native_outcome_id=f"points-{'all' if family == 'total' else side}-game-{results.ODD_NAMES[family]}-{side}")
    calc = dict(source=source, game_key=game_id, league=league, period=period, family=family, side=side, kickoff=START,
                selection=dict(signed_line=line, participant={"home": HOME, "away": AWAY}.get(side)),
                raw=dict(net_ev="129/640"), reference=dict(probability="5/32"),
                fee=dict(committed_usd="57921/769",
                         cashflows=dict(win=dict(net_receipt_usd="579.21"), loss=dict(net_receipt_usd="0"))))
    return saved, dict(sized_calculation=calc)


def evidence(identity="first-result", *, home=76, away=77, source="cb", state="final"):
    return dict(id=identity, source=source, state=state, observed_at=OBSERVED, recorded_at=OBSERVED,
                overtime_periods=1, receipt_sha256=sha256(identity.encode()).hexdigest(),
                scores={HOME: home, AWAY: away} if state == "final" else {})


def context(entry, frozen, retained):
    return results._game_context(entry, {}, frozen, {}, None, retained), frozen


def run(*tickets, best=None, identity="frozen"):
    selections = [entry for entry, _ in tickets]
    return dict(id=identity, report_revision="original-run-revision", summary=dict(coverage=dict(expected_games=None)),
                payload=dict(witnesses={entry["id"]: witness for entry, witness in tickets},
                             report=dict(date="2026-11-23", policy=dict(execution="paper_only"),
                                portfolios=dict(best_venue=dict(tickets=selections if best is None else best),
                                                all_venues=dict(tickets=selections)))))


def test_grade_exact_frozen_trade_and_portfolios_reconcile():
    capture, frozen = game()
    best, other = ticket("selected-best"), ticket("selected-all", venue="kalshi", side="away", line="14.5")
    missing, missed_frozen = game("missing", status="missed")
    no_trade, zero_frozen = game("zero")
    saved = run(best, other, best=[best[0]])
    before = encoded(saved)
    contexts = [context(capture, frozen, [evidence()]), context(missing, missed_frozen, [evidence()]),
                context(no_trade, zero_frozen, [evidence()])]
    report = results.build_report(saved, contexts)
    assert results.build_report(saved, contexts) == report
    assert encoded(saved) == before
    assert report["coverage"] == dict(expected_games=None, known_games=3, missing_capture_games=1,
                                       zero_trade_games=1, final_games=3)
    best_view, all_view = (report["portfolios"][name] for name in results.VARIANTS)
    assert best_view["summary"]["tickets"] == 1 and all_view["summary"]["tickets"] == 2
    loss, win = all_view["tickets"]
    assert loss["grade"]["id"] == best_view["tickets"][0]["grade"]["id"]
    assert (loss["stake_usd"], loss["expected_profit_usd"], loss["pnl_usd"]) == ("75.32", "15.18", "-75.32")
    assert loss["grade"]["state"] == "loss" and win["grade"]["state"] == "win"
    assert "including overtime" in loss["grade"]["explanation"]
    assert all_view["by_game"]["missing"]["tickets"] == all_view["by_game"]["zero"]["tickets"] == 0
    for views in ("by_game", "by_venue", "by_capture"):
        for field in ("stake", "return", "pnl", "expected_profit"):
            key = field + "_exact_usd"
            assert sum(Fraction(v[key]) for v in all_view[views].values()) == Fraction(all_view["summary"][key])


def test_one_per_game_report_preserves_selected_proof_and_ignores_pending_candidates_in_status():
    selected = ticket("selected")
    unranked = ticket("unranked", game_id="unranked")
    selected[0]["portfolio_selection"] = dict(tier="nearby_alternate")
    unranked[0]["portfolio_selection"] = dict(tier="unranked", reason="main_line_anchor_unavailable")
    proof = dict(tier="main", ranked_quote_venue="prophetx", selected_quote_line_role="alternate")
    saved = run(selected, unranked, best=[dict(selected[0], portfolio_selection=proof)])
    saved["payload"]["report"]["policy"].update(sizing_mode="fixed_profit",
        portfolio_rule=paper.MAIN_FIRST_ONE_PER_GAME, portfolios=["best_venue"])
    capture, frozen = game()
    no_pick, other = game("unranked")
    report = results.build_report(saved, (context(capture, frozen, [evidence()]), context(no_pick, other, [])))
    assert report["status"] == "graded" and report["coverage"]["zero_trade_games"] == 1
    assert report["portfolios"]["best_venue"]["tickets"][0]["portfolio_selection"] == proof
    assert report["portfolios"]["all_venues"]["candidate_pool_only"]
    assert report["portfolios"]["all_venues"]["summary"]["unresolved"] == 1


def test_corrections_conflicts_and_reinstated_score_are_separate_grades():
    capture, frozen = game()
    saved = run(ticket("trade"))
    first = evidence()
    corrected = evidence("corrected", home=100)
    conflict = evidence("competing-provider", source="sgo")
    reinstated = evidence("third", home=76, away=77)
    reports = [results.build_report(saved, [context(capture, frozen, active)])
               for active in ([first], [corrected], [corrected, conflict], [reinstated])]
    states = [report["portfolios"]["best_venue"]["tickets"][0]["grade"]["state"] for report in reports]
    assert states == ["loss", "win", "conflicting", "loss"]
    assert len({report["evidence_revision"] for report in reports}) == 4
    assert reports[2]["portfolios"]["best_venue"]["tickets"][0]["pnl_usd"] is None
    assert not reports[2]["games"][0]["result"]["home_score"]
    assert reports[3]["result_observed_at"] == OBSERVED
    separate = results.build_report(run(ticket("trade"), identity="second-definition"), [context(capture, frozen, [first])])
    assert separate["portfolios"]["best_venue"]["tickets"][0]["grade"]["id"] != (
        reports[0]["portfolios"]["best_venue"]["tickets"][0]["grade"]["id"])


def test_partial_roi_uses_only_the_resolved_ticket_population():
    capture, frozen = game()
    outstanding, pending_frozen = game("pending")
    saved = run(ticket("one"), ticket("two", game_id="pending"))
    report = results.build_report(saved, [context(capture, frozen, [evidence()]),
                                          context(outstanding, pending_frozen, [])])
    portfolio = report["portfolios"]["all_venues"]
    summary = portfolio["summary"]
    assert report["status"] == "partially_graded"
    assert summary["roi"] == "-1" and summary["roi_denominator"] == "resolved_ticket_stake"
    assert summary["unresolved"] == 1
    assert summary["unresolved_stake_exact_usd"] == summary["roi_stake_exact_usd"] == "57921/769"
    assert 2 * Fraction(summary["resolved_expected_profit_exact_usd"]) == Fraction(summary["expected_profit_exact_usd"])
    assert portfolio["tickets"][1]["grade"]["state"] == "pending"
    assert portfolio["tickets"][1]["return_usd"] is None


def test_scoring_scope_push_void_and_contract_binding_are_explicit():
    capture, frozen = game()
    correct = ticket("trade", family="total", side="under", line="153")
    unresolved = []
    unresolved.append((correct, [evidence()], "push_refund_unverified"))
    unresolved.append((correct, [evidence(state="cancelled")], "void_refund_unverified"))
    unresolved.append((ticket("period", period="first_half"), [evidence()], "unsupported_period"))
    regulation_only = deepcopy(correct)
    regulation_only[0]["identity"]["settlement"]["overtime_evidence"] = ["excluded"]
    unresolved.append((regulation_only, [evidence()], "unsupported_scoring_terms"))
    wrong_line = deepcopy(correct)
    wrong_line[1]["sized_calculation"]["selection"]["signed_line"] = "154"
    unresolved.append((wrong_line, [evidence()], "frozen_contract_binding_unverified"))
    wrong_team = ticket("team", side="home", line="-1")
    wrong_team[1]["sized_calculation"]["selection"]["participant"] = AWAY
    unresolved.append((wrong_team, [evidence()], "frozen_contract_binding_unverified"))
    for selected, retained, reason in unresolved:
        report = results.build_report(run(selected), [context(capture, frozen, retained)])
        trade = report["portfolios"]["all_venues"]["tickets"][0]
        assert trade["grade"]["state"] == "unsupported"
        assert trade["grade"]["reason"] == reason
        assert trade["pnl_usd"] is None


def test_hockey_winner_can_use_the_final_but_line_needs_a_shootout_score_basis():
    capture, frozen = game(league="NHL")
    winner = ticket("winner", league="NHL", family="moneyline", side="away", line=None)
    spread = ticket("spread", league="NHL", side="away", line="1.5")
    report = results.build_report(run(winner, spread), [context(capture, frozen, [evidence(home=2, away=3)])])
    winner_grade, spread_grade = (row["grade"] for row in report["portfolios"]["all_venues"]["tickets"])
    assert winner_grade["state"] == "win"
    assert spread_grade["reason"] == "shootout_score_basis_unverified"


def test_canonical_participant_binding_can_use_reversed_source_display_order():
    capture, frozen = game()
    native_home, native_away = frozen["home"], frozen["away"]
    retained_away, retained_home = "ncaa:away", "ncaa:home"
    teams = [dict(role="away", original_canonical_id=native_away, canonical_id=retained_away),
             dict(role="home", original_canonical_id=native_home, canonical_id=retained_home)]
    occurrence = dict(occurrence_id="verified-occurrence", provider_evidence=dict(teams=teams),
                      occurrence_schedule=dict(starts_at=START), source_records=[
                dict(id="score", source="college_basketball_data", kind="results", revision="results-1",
                     source_game_id="cbbd:1", status="final", receipt_id="receipt", observed_at=OBSERVED,
                     recorded_at=OBSERVED, teams=[dict(canonical_id=retained_away, score=77, display_role="home"),
                                                 dict(canonical_id=retained_home, score=76, display_role="away")])])
    source = results._source_evidence(occurrence, START, {"receipt": "digest"})
    context = results._game_context(capture, {}, frozen, {}, occurrence, source)
    score = context["result"]
    assert (score["home_id"], score["away_id"], score["home_score"], score["away_score"]) == (
        retained_home, retained_away, 76, 77)
    assert score["evidence"][0]["receipt_sha256"] == "digest"
    assert results._source_evidence(occurrence, "2026-11-23T18:30:00+00:00", {}) == []
    assert results.build_report(run(ticket("trade")), [(context, frozen)])["status"] == "graded"
