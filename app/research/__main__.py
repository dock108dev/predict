"""Operate general research without acquiring provider data or writing trades."""

import argparse
import json
from pathlib import Path

from app.storage.store import connect, stamp
from . import records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    declaration = commands.add_parser("declare")
    declaration.add_argument("file", type=Path, help="JSON: name, cases, horizons and optional designation")
    commands.add_parser("turn", help="Declare the daily population and record current known candidates")
    capture = commands.add_parser("capture")
    capture.add_argument("cohort")
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("cohort")
    evaluation.add_argument("--as-of", type=stamp)
    evaluation.add_argument("--save", action="store_true", help="Append a frozen evaluation; never replace prior results")
    outcome = commands.add_parser("outcome")
    outcome.add_argument("cohort")
    outcome.add_argument("case")
    outcome.add_argument("kind", choices=("sporting", "settlement"))
    outcome.add_argument("file", type=Path)
    outcome.add_argument("--supersedes")
    outcome.add_argument("--reason")
    export = commands.add_parser("export")
    export.add_argument("cohort")
    observation = commands.add_parser("observe")
    observation.add_argument("cohort")
    observation.add_argument("case")
    observation.add_argument("file", type=Path, help="JSON: payload, known_at and optional record/fee_input")
    replay = commands.add_parser("replay-market")
    replay.add_argument("root", type=Path)
    replay.add_argument("case_file", type=Path)
    replay.add_argument("--event", required=True)
    replay.add_argument("--from-day", required=True)
    replay.add_argument("--through-day", required=True)
    replay.add_argument("--as-of", required=True)
    replay.add_argument("--cohort", help="Append to an explicitly retrospective cohort")
    args = parser.parse_args()
    with connect() as db:
        if args.command == "list":
            result = dict(cohorts=records.list_cohorts(db), retention=records.status(db), provider_requests=0)
        elif args.command == "declare":
            definition = json.loads(args.file.read_text())
            result = records.declare(db, **definition)
        elif args.command == "turn":
            result = records.automatic_turn(db)
        elif args.command == "capture":
            result = records.capture_due(db, cohort_id=args.cohort)
        elif args.command == "evaluate":
            result = records.evaluate(db, args.cohort, as_of=args.as_of, persist=args.save)
        elif args.command == "outcome":
            result = records.annotate(db, args.cohort, args.case, args.kind,
                json.loads(args.file.read_text()), supersedes_id=args.supersedes, reason=args.reason)
        elif args.command == "observe":
            data = json.loads(args.file.read_text())
            if data.get("known_at"):
                data["known_at"] = stamp(data["known_at"])
            result = records.observe(db, args.cohort, args.case, **data)
        elif args.command == "replay-market":
            from .archive import replay
            case = json.loads(args.case_file.read_text())
            result = replay(args.root, event_id=args.event, case=case,
                first_day=args.from_day, last_day=args.through_day, as_of=args.as_of)
            if args.cohort:
                cohort = records._get(db, args.cohort, kind="cohort")
                if cohort["designation"] != "retrospective_replay":
                    raise ValueError("Historical replay requires a retrospective_replay cohort")
                result["observation"] = records.observe(db, args.cohort, case["case_key"],
                    result["payload"], known_at=stamp(args.as_of))
        else:
            result = records.detail(db, args.cohort)
        print(json.dumps(result, indent=2, default=str, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
