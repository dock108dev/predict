"""Declared bounded offline SOFTWARE workload; no provider or owner paths.

Run in one fresh, inherited CI-guarded process with an external 180-second
deadline. The script measures an authored workload, not indefinite stability.
"""
import argparse
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from fractions import Fraction
import json
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time

from app.collection.current_quota import QuotaLedger, QuotaStop
from app.collection.local_ownership import LocalOwnership
from app.comparison.current_dependencies import KINDS, encoded, profile, validate_profiles
from app.comparison.domain import UnknownValue
from app.comparison.metrics import snapshot_metrics
from app.comparison.net_arbs import ArbLimits, search_arbs
from app.comparison.payouts import bind_profile
from app.dashboard.current_contract import packed, quotes_of, serialize, snapshot_inputs, stamp, validate_snapshot
from app.dashboard.current_state import CurrentStore, SelectionError
from tests.current_fixture import InjectedTestProvider
from tests.comparison_fixture import software_fixture
from tests.test_comparison_lifecycle import AT as NATIVE_AT, AUTHORED, book, edges, selected
from tests.test_comparison_net_arbs import NetArbTests
from tests.test_current_incremental import catalog, changed
from tests.test_current_quota import WINDOW, quota

VERSION = "comparison-software-resource-1"
DECLARATION = dict(cycles=6, aggregate_events=30, groups=90, quotes=360,
                   controlled_catalog_sport="MLB", shared_profiles=128, profiles_maximum_bytes=2 * 1024 * 1024,
                   candidate_legs=34, per_group_candidate_pairs=256, per_group_allocation_evaluations=1024,
                   per_group_returned_results=128, points_per_leg=2,
                   latest_queue_capacity=1, subscribers=8, review_leases=8,
                   rss_ceiling_bytes=768 * 1024 * 1024, process_deadline_seconds=180,
                   provider_requests=0, scheduler_invocations=0,
                   typed_events=1, typed_groups=1, typed_quotes=2,
                   typed_no_transition_seconds=1, typed_optional_ceiling_usd="20",
                   typed_shared_profile_expiry_after_revision_seconds=10,
                   evidence_class="authored offline disposable fixed workload")


def crowded_profiles():
    values = {}
    # Bounded public padding exercises sharing near the 2 MiB cap. It is an
    # authored immutable metadata profile, not invented identity/fee authority.
    for index in range(DECLARATION["shared_profiles"]):
        key, item = profile(KINDS[index % len(KINDS)], dict(authored_metadata_index=index,
                 markers=[str(marker).zfill(3) + ":" + "x" * 96 for marker in range(150)]))
        values[key] = item
    validate_profiles(values)
    if len(encoded(values)) > DECLARATION["profiles_maximum_bytes"]:
        raise AssertionError("Declared profile byte cap exceeded")
    return values


def merge_delta(previous, response):
    if response["schema"] == "predict-current-1":
        return response
    state = deepcopy(response["snapshot"])
    events = {item["id"]: deepcopy(item) for item in previous["events"]}
    for key in response["removed_events"]:
        events.pop(key, None)
    for event in response["events"]:
        events[event["id"]] = deepcopy(event)
    state["events"] = sorted(events.values(), key=lambda item: item["id"])
    return state


def canonical_snapshot(value):
    value = deepcopy(value)
    value["events"].sort(key=lambda event: event["id"])
    return packed(value)


def exact_metric(value):
    if not value.get("eligible") or value.get("exact") is None:
        raise AssertionError("Authored typed metric unexpectedly unavailable")
    exact = value["exact"]
    return Fraction(int(exact["numerator"]), int(exact["denominator"]))


def check_typed_oracles(state, *, ceiling="100"):
    """Literal independent fixture targets; display/production is no oracle."""
    view = snapshot_metrics(state)
    rows = {row["venue"]: row for row in view["rows"]}
    if set(rows) != {"kalshi", "prophetx"} or len(view["pairs"]) != 1:
        raise AssertionError("Declared typed inventory/calculator count differs")
    if exact_metric(rows["kalshi"]["net_ev"]) != 50 or exact_metric(rows["prophetx"]["net_ev"]) != Fraction(-300, 11):
        raise AssertionError("Typed benchmark EV differs from literal oracle")
    pair = view["pairs"][0]
    # Authored complementary known-state receipts 100, funded cost 97 give
    # (100 - 97) / 97 * 100 = 300/97 percent; $20 selects one native unit.
    if pair["category"] != "conditional_known_states" or exact_metric(pair["buffered_minimum_return"]) != Fraction(300, 97):
        raise AssertionError("Typed conditional pair differs from literal oracle")
    if "noncompleted" not in pair["details"]["unknown_states"]:
        raise AssertionError("Unknown exceptional payout was promoted to an all-state result")
    expected = (Fraction("79.6"), Fraction("55"), Fraction("97")) if ceiling == "100" else (
        Fraction("0.4"), Fraction("0.55"), Fraction("0.97"))
    actual = (Fraction(rows["kalshi"]["net_ev"]["basis"]["capital_denominator"]),
              Fraction(rows["prophetx"]["net_ev"]["basis"]["capital_denominator"]),
              Fraction(pair["details"]["denominator_usd"]))
    if actual != expected:
        raise AssertionError("Typed actual deployed denominator differs from literal oracle")
    if view["acquisition_requests"] != 0:
        raise AssertionError("Read-only metric view acquired inputs")
    return view


async def typed_projection():
    """Real bound net/pair graphs, retained input clocks and shared expiry."""
    from app.comparison.current_metrics import calculate_quote, calculate_group_pairs
    started = time.monotonic()
    raw = software_fixture()
    ticks = [0]
    provider = InjectedTestProvider(raw)
    store = CurrentStore(provider, monotonic=lambda: ticks[0])
    try:
        initial = store.snapshot()
        initial_rows = store.index(initial)
        if len(initial["events"]) != 1 or len(initial["events"][0]["groups"]) != 1 or len(initial_rows) != 2:
            raise AssertionError("Typed fixture exceeds declared one-group inventory")
        validate_snapshot(initial, allow_synthetic=True)
        check_typed_oracles(initial)
        if packed(initial) != packed(serialize(raw, allow_synthetic=True)):
            raise AssertionError("Typed initial projection/full serializer diverged")
        original_clocks = {key: row["quote"]["times"]["source_at"] for key, row in initial_rows.items()}
        initial_bytes = len(packed(initial))

        # A clock-only tick updates age scalars, while calculation graphs and
        # state revision remain fixed. The delta carries the advancing clock;
        # changed-event equality is separately checked on each real transition.
        ticks[0] = DECLARATION["typed_no_transition_seconds"]
        no_transition = store.snapshot()
        validate_snapshot(no_transition, allow_synthetic=True)
        check_typed_oracles(no_transition)
        if no_transition["state_revision"] != initial["state_revision"]:
            raise AssertionError("One-second clock tick created a calculation revision")
        if packed(no_transition) != packed(serialize(snapshot_inputs(no_transition), allow_synthetic=True)):
            raise AssertionError("Typed one-second projection/full serializer diverged")
        tick_delta = json.loads(store.encoded_changes(initial["runtime_id"], initial["state_revision"]))
        if tick_delta["events"] or tick_delta["removed_events"] or tick_delta["snapshot"]["clock_at"] != no_transition["clock_at"]:
            raise AssertionError("No-transition cursor failed to retain a clock-only delta")
        for key, row in store.index(no_transition).items():
            if packed(row["quote"]["calculations"]) != packed(initial_rows[key]["quote"]["calculations"]):
                raise AssertionError("Unchanged price/dependency graphs changed on one-second tick")
        if packed(no_transition["events"][0]["groups"][0]["comparison_pairs"]) != packed(initial["events"][0]["groups"][0]["comparison_pairs"]):
            raise AssertionError("Unchanged pair graph changed on one-second tick")

        # This is the same snapshot-copy path as the optional Details ceiling
        # route, with no store commit or input acquisition.
        retained = packed(store._state)
        sized = deepcopy(no_transition)
        ceiling = DECLARATION["typed_optional_ceiling_usd"]
        for event in sized["events"]:
            for group in event["groups"]:
                for outcome in group["outcomes"]:
                    for quote in quotes_of(outcome):
                        quote["calculations"]["net_ev"], quote["calculations"]["conservative"] = calculate_quote(
                            quote, sized["comparison_profiles"], stamp(sized["clock_at"]), ceiling=ceiling,
                            event=event, group=group, outcome=outcome)
                group["comparison_pairs"], group["comparison_search"] = calculate_group_pairs(
                    group, sized["comparison_profiles"], stamp(sized["clock_at"]), ceiling=ceiling, event=event)
        sized_view = check_typed_oracles(sized, ceiling=ceiling)
        if packed(store._state) != retained or sized["state_revision"] != no_transition["state_revision"]:
            raise AssertionError("Optional ceiling recompute mutated retained current state")
        if any(row["net_ev"]["basis"]["size_basis"]["ceiling_usd"] != ceiling for row in sized_view["rows"]):
            raise AssertionError("Optional ceiling lost its explicit size basis")

        # Both quotes reference the same buffer envelope. A replacement retains
        # its predecessor and changes only shared dependency identity/expiry.
        updated = snapshot_inputs(no_transition)
        quotes = [quote for event in updated["events"] for group in event["groups"]
                  for outcome in group["outcomes"] for quote in quotes_of(outcome)]
        old_keys = {quote["comparison_input_refs"]["refs"]["buffer"] for quote in quotes}
        if len(old_keys) != 1:
            raise AssertionError("Authored buffer profile is not shared by both quotes")
        old_key = old_keys.pop()
        expires = stamp(no_transition["clock_at"]) + timedelta(seconds=DECLARATION["typed_shared_profile_expiry_after_revision_seconds"])
        new_key, new_profile = profile("buffer", deepcopy(updated["comparison_profiles"][old_key]["payload"]), expires_at=expires.isoformat())
        updated["comparison_profiles"][new_key] = new_profile
        for quote in quotes:
            quote["comparison_input_refs"]["refs"]["buffer"] = new_key
        updated["state_revision"] += 1
        if not store.commit(updated):
            raise AssertionError("Typed shared dependency revision failed commit")
        revised = store.snapshot()
        validate_snapshot(revised, allow_synthetic=True)
        revised_view = check_typed_oracles(revised)
        revised_delta_bytes = store.encoded_changes(no_transition["runtime_id"], no_transition["state_revision"])
        if canonical_snapshot(merge_delta(no_transition, json.loads(revised_delta_bytes))) != canonical_snapshot(revised):
            raise AssertionError("Typed dependency revision full/incremental output diverged")
        if packed(revised) != packed(serialize(updated, allow_synthetic=True)):
            raise AssertionError("Typed dependency revision full/rebuilt math diverged")
        if store.projection_metrics != dict(projected_groups=1, reused_groups=0):
            raise AssertionError("Typed dependency revision failed to invalidate its group")
        if old_key not in revised["comparison_profiles"] or new_key not in revised["comparison_profiles"]:
            raise AssertionError("Shared revision overwrote predecessor evidence")
        for row in revised_view["rows"]:
            if row["net_ev"]["basis"]["dependency_revisions"]["profiles"]["buffer"] != new_key:
                raise AssertionError("Net graph retained stale shared dependency revision")

        ticks[0] += DECLARATION["typed_shared_profile_expiry_after_revision_seconds"]
        expired = store.snapshot()
        validate_snapshot(expired, allow_synthetic=True)
        expired_view = snapshot_metrics(expired)
        if expired["state_revision"] != revised["state_revision"] + 1 or expired_view["pairs"]:
            raise AssertionError("Shared expiry failed to invalidate typed pair graph")
        if any(row["net_ev"]["eligible"] or "buffer_inputs_expired" not in row["net_ev"]["reason"] for row in expired_view["rows"]):
            raise AssertionError("Shared expiry failed to invalidate both typed net graphs")
        expired_delta_bytes = store.encoded_changes(revised["runtime_id"], revised["state_revision"])
        if canonical_snapshot(merge_delta(revised, json.loads(expired_delta_bytes))) != canonical_snapshot(expired):
            raise AssertionError("Typed shared expiry full/incremental output diverged")
        if packed(expired) != packed(serialize(snapshot_inputs(expired), allow_synthetic=True)):
            raise AssertionError("Typed shared expiry full/rebuilt math diverged")
        if any(row["quote"]["times"]["source_at"] != original_clocks[key] for key, row in store.index(expired).items()):
            raise AssertionError("Dependency revision/expiry refreshed original price clocks")
        check_typed_oracles(initial)
        return dict(events=1, groups=1, quotes=2, bound_profile_count=len(initial["comparison_profiles"]),
            bound_profile_bytes=len(encoded(initial["comparison_profiles"])), net_calculators_available=2,
            pair_calculators_available=1, literal_kalshi_ev_percent="50", literal_prophetx_ev_percent="-300/11",
            literal_conditional_pair_percent="300/97", unknown_exceptional_states_retained=True,
            initial_full_rebuild_equality=True, one_second_full_rebuild_equality=True,
            one_second_no_transition_math_equality=True, one_second_delta_clock_only=True,
            dependency_revision_full_incremental_equality=True, dependency_revision_full_rebuild_equality=True,
            shared_expiry_full_incremental_equality=True, shared_expiry_full_rebuild_equality=True,
            shared_profile_dependents=2, predecessor_profile_retained=True,
            shared_expiry_invalidated_net_calculators=2, shared_expiry_invalidated_pair_calculators=1,
            original_price_clocks_preserved=True, original_snapshot_math_preserved=True,
            optional_ceiling_usd=ceiling, optional_ceiling_read_only=True,
            optional_ceiling_literal_kalshi_ev_percent="50", optional_ceiling_literal_pair_percent="300/97",
            optional_ceiling_kalshi_deployed_usd="0.4", optional_ceiling_pair_deployed_usd="0.97",
            one_group_initial_snapshot_bytes=initial_bytes,
            one_group_largest_snapshot_bytes=max(initial_bytes, len(packed(revised)), len(packed(expired))),
            one_group_dependency_delta_bytes=len(revised_delta_bytes), one_group_expiry_delta_bytes=len(expired_delta_bytes),
            elapsed_seconds=round(time.monotonic() - started, 6), provider_requests=0, scheduler_invocations=0,
            evidence_class="authored typed bound profiles and disposable presentation state")
    finally:
        await store.close()
        if provider.close_count != 1:
            raise AssertionError("Typed disposable presentation provider did not close once")


def crowded_arbs():
    NetArbTests.setUpClass()
    factory = NetArbTests()
    templates = factory.pair(available="2", minimum="1", increment="1")
    legs = []
    for index in range(DECLARATION["candidate_legs"]):
        original = templates[index % 2]
        bound = original.bound_leg
        native = replace(bound.selection.native, instrument_id=bound.selection.native.instrument_id + ":authored:" + str(index))
        selection = replace(bound.selection, native=native, payout=None,
                            payout_unknown=UnknownValue("Authored instrument awaits exact profile attachment", ("profile",)))
        payout = replace(bound.profile, native_key=native.key)
        attached = bind_profile(selection, payout, at=factory.at, rule_revision=payout.rule_revision, context=bound.context)
        levels = tuple(replace(level, liquidity_id=level.liquidity_id + ":authored:" + str(index)) for level in original.depth_leg.levels)
        depth = replace(original.depth_leg, leg_id=original.depth_leg.leg_id + ":" + str(index), native_key=native.key, levels=levels)
        legs.append(replace(original, bound_leg=attached, depth_leg=depth))
    limits = ArbLimits(max_candidate_pairs=256, max_allocation_evaluations=1024, max_results=128, max_points_per_leg=2)
    started = time.monotonic()
    result = search_arbs(tuple(legs), at=factory.at, limits=limits)
    for field, ceiling in (("candidate_pairs", 256), ("allocation_evaluations", 1024), ("returned_results", 128)):
        if result[field] > ceiling:
            raise AssertionError("Declared arb limit exceeded: " + field)
    if result["theoretical_candidate_pairs"] != 289 or result["candidate_pairs"] != 256 or result["allocation_evaluations"] != 1024:
        raise AssertionError("Crowded authored workload failed to exercise declared search caps")
    if not result["truncated"] or any(row["global_optimum_established"] for row in result["results"]):
        raise AssertionError("Truncated workload claimed global optimality")
    if any(Fraction(row["denominator_usd"]) > 100 for row in result["results"] if row["denominator_usd"] is not None):
        raise AssertionError("Common prefunded ceiling exceeded")
    return dict(candidate_legs=len(legs), limits=result["limits"], candidate_pairs=result["candidate_pairs"],
                theoretical_candidate_pairs=result["theoretical_candidate_pairs"],
                allocation_evaluations=result["allocation_evaluations"], returned_results=result["returned_results"],
                truncated=result["truncated"], truncation=result["truncation"],
                largest_search_payload_bytes=len(packed(result)), elapsed_seconds=round(time.monotonic() - started, 6),
                global_optimum_claimed=False)


async def recovery():
    """Actual isolated ledger, lifecycle and locks; no worker/scheduler startup."""
    from app.comparison.lifecycle import LifecycleOwner
    with tempfile.TemporaryDirectory(prefix="predict-software-recovery-authored-") as directory:
        root = Path(directory)
        at = ["2026-10-03T12:00:00+00:00"]
        owner = LocalOwnership(root / "owner.lock")
        owner.acquire("AUTHORED-SOFTWARE-runtime")
        try:
            ledger = QuotaLedger(root / "quota", clock=lambda: at[0])
            ledger.bind_window(WINDOW)
            bootstrap = ledger.reserve(owner, "AUTHORED-SOFTWARE-candidate", {"authored_accounting": True}, 0, bootstrap=True)
            ledger.dispatched(bootstrap, owner)
            ledger.reconcile(bootstrap, quota(20))
            confirmed = ledger.reserve(owner, "AUTHORED-SOFTWARE-candidate", {"authored_accounting": True}, 3)
            ledger.dispatched(confirmed, owner)
            ledger.reconcile(confirmed, quota(23, 3))
            due = ledger.snapshot()["next_due_at"]
            at[0] = due
            uncertain = ledger.reserve(owner, "AUTHORED-SOFTWARE-candidate", {"authored_uncertain_charge": True}, 3)
            ledger.dispatched(uncertain, owner)
            before = ledger._read()
            lock_before = (root / "owner.lock").read_bytes()
            lifecycle = LifecycleOwner("kalshi", "AUTHORED-SOFTWARE-runtime", attempt_id=uncertain, links=edges())
            lifecycle.reconcile([selected("A"), selected("B")], NATIVE_AT)
            lifecycle.begin_connection(1)
            original = lifecycle.admit_book(book(), generation=1)
            lifecycle.begin_connection(2)
            try:
                lifecycle.admit_book(book(), generation=1)
                raise AssertionError("Reconnect accepted stale generation")
            except ValueError:
                pass
            later = book(source=AUTHORED["expected"]["unchanged_confirmation_clock"], received="2026-10-08T20:00:21Z")
            restored = lifecycle.admit_book(later, generation=2)
            if restored["raw"]["exchange_at"] != original["raw"]["exchange_at"]:
                raise AssertionError("Reconnect refreshed original price clock")
            closed = []
            async def close_market(mid, token):
                if lifecycle.dispatch or owner.file is None:
                    raise AssertionError("Stop did not revoke before owned cleanup")
                closed.append(mid)
            await lifecycle.stop(close_market)
            after_stop = ledger._read()
            if after_stop != before or lifecycle.attempt_id != uncertain or closed != ["A", "B"]:
                raise AssertionError("Stop changed consumed accounting or ownership")
            reopened = QuotaLedger(root / "quota", clock=lambda: at[0])
            if reopened._read() != before or (root / "owner.lock").read_bytes() != lock_before:
                raise AssertionError("Read-only reopen reset accounting or owner identity")
            try:
                reopened.reserve(owner, "AUTHORED-SOFTWARE-candidate", {"authored_only": True}, 3)
                raise AssertionError("Uncertain charge reopened dispatch authority")
            except QuotaStop:
                pass
            preserved = reopened._read()
            for key in ("attempts", "observation", "next_due_at", "bootstrap_due_at", "rotation", "window", "windows"):
                if preserved[key] != before[key]:
                    raise AssertionError("Refused repeat changed accounting: " + key)
            return dict(reconnect_generation_rejection=True, original_price_clock_preserved=True,
                        stop_revokes_before_cleanup=True, consumed_attempt_preserved=True,
                        observed_used_credits=23, uncertain_reserved_credits=3,
                        attempts=len(before["attempts"]), original_due_at_preserved=True,
                        ledger_reopen_equality=True, ownership_identity_preserved=True,
                        uncertain_charge_repeat_refused=True, closed_markets=len(closed), provider_requests=0,
                        scheduler_invocations=0, evidence_class="actual disposable authored state and injected accounting headers")
        finally:
            owner.release()


async def workload():
    started = time.monotonic()
    raw = catalog(DECLARATION["aggregate_events"])
    # This transport stress fixture intentionally uses independent padding
    # profiles, rather than source-adapter refs from the catalog helper.
    for event in raw['events']:
        for group in event['groups']:
            for outcome in group['outcomes']:
                for quote in quotes_of(outcome):
                    quote.pop('comparison_input_refs',None)
                    quote.pop('comparison_input_status',None)
    raw["comparison_profiles"] = crowded_profiles()
    provider = InjectedTestProvider(raw)
    store = CurrentStore(provider, monotonic=lambda: 0)
    full_sizes, delta_sizes, projected, reused = [], [], [], []
    held = []
    for _ in range(DECLARATION["subscribers"]):
        store.subscribers.add(asyncio.Queue(maxsize=1))
    first = store.snapshot()
    rows = list(store.index(first).values())
    if len(first["events"]) != 30 or sum(len(event["groups"]) for event in first["events"]) != 90 or len(rows) != 360:
        raise AssertionError("Declared inventory count differs from authored input")
    for index, row in enumerate(rows[:DECLARATION["review_leases"]]):
        held.append(store.create(dict(schema=first["schema"], runtime_id=first["runtime_id"], state_revision=first["state_revision"],
                   quote_id=row["quote"]["id"], quote_revision=row["quote"]["revision"], client_id="authored-client-" + str(index))))
    try:
        ninth = rows[8]
        try:
            store.create(dict(schema=first["schema"], runtime_id=first["runtime_id"], state_revision=first["state_revision"],
                quote_id=ninth["quote"]["id"], quote_revision=ninth["quote"]["revision"], client_id="authored-client-nine"))
            raise AssertionError("Review lease cap exceeded")
        except SelectionError as error:
            if error.status != 429:
                raise
        current = first
        for cycle in range(DECLARATION["cycles"]):
            previous = current
            raw = changed(raw, cycle, cycle + 2)
            if not store.commit(raw):
                raise AssertionError("Authored revision failed commit")
            current = store.snapshot()
            full = store.encoded_snapshot()
            delta = store.encoded_changes(previous["runtime_id"], previous["state_revision"])
            merged = merge_delta(previous, json.loads(delta))
            if canonical_snapshot(merged) != canonical_snapshot(current):
                raise AssertionError("Full/incremental output diverged")
            if packed(current) != packed(serialize(raw, allow_synthetic=True)):
                raise AssertionError("Incremental/rebuilt math diverged")
            validate_snapshot(current, allow_synthetic=True)
            if any(queue.qsize() != 1 for queue in store.subscribers) or len(store.leases) != 8:
                raise AssertionError("Queue or held review bounds changed")
            full_sizes.append(len(full)); delta_sizes.append(len(delta))
            projected.append(store.projection_metrics["projected_groups"])
            reused.append(store.projection_metrics["reused_groups"])
        old_cursor = json.loads(store.encoded_changes("authored-old-runtime", 1))
        if old_cursor["schema"] != "predict-current-1" or canonical_snapshot(old_cursor) != canonical_snapshot(current):
            raise AssertionError("Old-cursor full recovery failed")
        reopen_raw = snapshot_inputs(current)
        reopened = CurrentStore(InjectedTestProvider(reopen_raw), monotonic=lambda: 0)
        try:
            if canonical_snapshot(reopened.snapshot()) != canonical_snapshot(current):
                raise AssertionError("Read-only projection reopen changed state")
        finally:
            await reopened.close()
        typed = await typed_projection()
        arbs = crowded_arbs()
        accounting = await recovery()
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
        if peak > DECLARATION["rss_ceiling_bytes"]:
            raise AssertionError("Unchanged outer memory ceiling exceeded")
        result = dict(version=VERSION, status="PASS", declaration=DECLARATION, peak_rss_bytes=peak,
                peak_rss_ceiling_bytes=DECLARATION["rss_ceiling_bytes"], profile_count=len(raw["comparison_profiles"]),
                profile_bytes=len(encoded(raw["comparison_profiles"])), largest_snapshot_bytes=max(full_sizes),
                largest_changed_event_payload_bytes=max(delta_sizes), cycle_snapshot_bytes=full_sizes,
                cycle_changed_payload_bytes=delta_sizes, projected_groups_per_cycle=projected, reused_groups_per_cycle=reused,
                full_incremental_equality=True, rebuilt_projection_equality=True, old_cursor_full_recovery=True,
                read_only_projection_reopen_equality=True, retained_leases=len(held), subscribers=len(store.subscribers),
                queue_capacity=1, typed_projection_workload=typed, crowded_arb_workload=arbs, recovery=accounting, provider_requests=0,
                scheduler_invocations=0, elapsed_seconds=round(time.monotonic() - started, 6),
                indefinite_stability_established=False, evidence_class=DECLARATION["evidence_class"])
        return result
    finally:
        await store.close()
        if store.leases or provider.close_count != 1:
            raise AssertionError("Controlled presentation cleanup failed")
        store.subscribers.clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--candidate-source-digest")
    args = parser.parse_args()
    print(json.dumps(dict(declared_before_execution=DECLARATION), sort_keys=True), flush=True)
    result = asyncio.run(workload())
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    result.update(candidate_head=head, candidate_source_digest=args.candidate_source_digest,
                  candidate_binding="final frozen candidate" if args.candidate_source_digest else "preliminary working candidate; lead must rebind and rerun after freeze",
                  inherited_ci_guards=True)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
