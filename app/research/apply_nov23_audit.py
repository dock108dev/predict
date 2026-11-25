"""Apply the reviewed November 23 decisions to matching production evidence."""

from argparse import ArgumentParser
from collections import Counter
from pathlib import Path
import json

from app.dashboard.mens_d1_coverage_api import coverage_view
from app.storage.store import connect, stamp
from app.storage.mens_d1_coverage import EASTERN

from . import issue_dispositions as review


ACTOR = "engineering:november-23-audit"


def audit():
    return json.loads(Path(__file__).with_name("nov23_audit.json").read_text())


def decision(item, game=None):
    if item["kind"] == "capture":
        code = item.get("reason_code")
        if code == "late_discovery_no_pre_target_baseline":
            return review.GAP, ("The first retained provider schedule receipt arrived at 10:51:25.921 AM Eastern, "
                "after the 10:51 AM capture deadline. Earlier upstream visibility is unknown. The final remains in the cohort. "
                "Review again only upon qualifying original in-window evidence.")
        if code == "checkpoint_window_missed":
            target = stamp(item["target_at"]).astimezone(EASTERN).strftime("%I:%M %p").lstrip("0")
            return review.GAP, (f"An early baseline was retained. The original task and receipt review found no late claim "
                f"or request at the {target} Eastern target. The final remains in the cohort. Review again only upon "
                "qualifying original in-window evidence.")
        return review.RESOLVED, ("The retained in-window response supports the saved retrospective reconstruction. "
            "The original refusal or late persistence remains part of capture reliability.")
    if item["kind"] == "membership":
        if game["research_scope"] == "excluded":
            return review.EXCLUDED, "The dated schedule and season membership records place a participant outside men's Division I."
        return review.RESOLVED, "The retained official box score identifies both Division I participants in the original source placeholder."
    if item["kind"] == "schedule":
        if game["research_scope"] == "other_date":
            return review.OTHER_DATE, ("UC San Diego Athletics and the retained odds-provider schedule corroborate midnight Eastern "
                "on November 24. The original November 23 source row stays in the audit.")
        return review.RESOLVED, ("The retained official and odds-provider clocks corroborate the operational start. "
            "The original CBBD clock and T−10 task target are preserved.")
    if item["kind"] == "venue_inventory":
        missing = item["requested_cells"] - item["returned_cells"]
        return review.LIMIT, (f"The retained target-event response returned {item['returned_cells']} of "
            f"{item['requested_cells']} requested venue/outcome cells. Historical offering is unknown for {missing} unreturned cells. "
            "Event pagination and venue-wide market inventory are separate observations.")
    if item["kind"] == "reference":
        return review.LIMIT, ("The retained original and normalized census found no projection loss. The frozen method excludes "
            "offers missing trusted exact book, side and line pairs or enough trusted books. Inspect the census for each missing input.")
    if item["kind"] == "slate":
        return review.LIMIT, ("The named November 23 Eastern cohort has 33 reviewed men's Division I games. The retained schedule "
            "sources do not establish an independently exhaustive slate.")
    raise ValueError("Unrecognized audited issue kind.")


def matches(item, issue, game):
    if item["kind"] != "venue_inventory":
        return item["evidence_revision"] == issue["evidence_revision"]
    market = (game.get("saved") or {}).get("market_summary") or {}
    return (item["checkpoint_id"] == issue.get("checkpoint_id") and market.get("evidence_revision")
            and market.get("basis") == "verified_original_response"
            and market.get("retrieval_state") == "complete_requested_event_response"
            and market.get("requested_cells") == item["requested_cells"]
            and market.get("returned_cells") == item["returned_cells"])


def apply_audit(db, plan, *, apply=False):
    day, run_id = plan["date"], plan["run_id"]
    identities = {review.issue_id(day, item["kind"], item["game_id"]):item for item in plan["issues"]}
    with db.transaction():
        if apply:
            for identity in sorted(identities):
                review.lock(db, identity)
        else:
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        view = coverage_view(db, day, run_id, None)
        if view["run"]["report_revision"] != plan["run_report_revision"]:
            raise ValueError("The selected run report differs from the audited report.")
        current = {issue["id"]:issue for issue in view["issues"]}
        games = {game["id"]:game for game in view["games"]}
        counts, deferred = Counter(), []
        for identity, item in identities.items():
            issue = current.get(identity)
            game = games.get(item["game_id"])
            if issue is None or not issue["active"] or not matches(item, issue, game):
                deferred.append(dict(kind=item["kind"], game_id=item["game_id"], detail="missing or changed audit evidence"))
                continue
            status, reason = decision(item, game)
            if issue["latest_decision_id"]:
                counts["existing_history"] += 1
                status = issue["status"]
            elif status not in issue["allowed_statuses"]:
                deferred.append(dict(kind=item["kind"], game_id=item["game_id"], detail="decision conflicts with current evidence"))
                continue
            elif apply:
                review.record(db, day, issue, status, reason, ACTOR)
                counts["recorded"] += 1
            else:
                counts["ready"] += 1
            counts[status] += 1
        return dict(date=day, run_id=run_id, decisions=dict(counts), deferred=deferred,
                    provider_requests=0, orders_submitted=0)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Save matching decisions. Defaults to a read-only review.")
    options = parser.parse_args()
    with connect() as db:
        result = apply_audit(db, audit(), apply=options.apply)
    print(json.dumps(result, indent=2))
    return 1 if result["deferred"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
