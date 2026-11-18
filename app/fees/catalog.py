"""Read and edit the current database fee rules without changing application code."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from app.storage.store import connect
from . import pricing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "seed", help="Import applicable reviewed schedules for unconfigured venues"
    )
    commands.add_parser("export", help="Export editable fee rules as JSON")
    load = commands.add_parser(
        "import", help="Validate and atomically apply an exported JSON file"
    )
    load.add_argument("path", type=Path)
    change = commands.add_parser(
        "set-rate", help="Change one configured rule coefficient"
    )
    change.add_argument("venue", choices=list(pricing.KEYS))
    change.add_argument("rule")
    change.add_argument("rate")
    args = parser.parse_args()
    with connect() as db, db.transaction():
        if args.command == "seed":
            print(
                json.dumps(dict(seeded=pricing.seed(db, at=datetime.now(timezone.utc))))
            )
        elif args.command == "export":
            print(
                json.dumps(
                    dict(schema=1, venues=pricing.read(db, include_blocked=True)),
                    indent=2,
                )
            )
        elif args.command == "import":
            if args.path.stat().st_size > 256 * 1024:
                raise ValueError("fee_catalog_file_too_large")
            document = json.loads(args.path.read_text())
            if (
                set(document) != {"schema", "venues"}
                or document["schema"] != 1
                or not isinstance(document["venues"], dict)
            ):
                raise ValueError("fee_catalog_schema")
            for venue, rules in document["venues"].items():
                if venue not in pricing.KEYS:
                    raise ValueError("fee_catalog_venue")
                pricing.validate(rules, venue)
            for venue, rules in document["venues"].items():
                pricing.write(db, venue, rules)
            print(json.dumps(dict(updated=list(document["venues"]))))
        else:
            rules = pricing.read(db, include_blocked=True)[args.venue]
            selected = [rule for rule in rules if rule["id"] == args.rule]
            if len(selected) != 1:
                raise ValueError("fee_catalog_rule_not_found")
            selected[0]["rate"] = args.rate
            pricing.write(db, args.venue, rules)
            print(json.dumps(dict(updated=args.venue, rule=args.rule, rate=args.rate)))


if __name__ == "__main__":
    main()
