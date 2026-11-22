"""Passive experiment inspection/export and offline reproduction commands."""
import argparse
import json
from pathlib import Path

from app.storage.store import connect, encoded
from . import experiment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--all-games", action="store_true")
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--offset", type=int, default=0)
    for command in ("detail", "export"):
        item = commands.add_parser(command)
        item.add_argument("game_id")
        item.add_argument("--revision")
    reproduce = commands.add_parser("reproduce")
    reproduce.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    if args.command == "reproduce":
        value = experiment.reproduce_export(json.loads(args.file.read_bytes()))
    else:
        with connect() as db:
            if args.command == "list":
                with db.transaction():
                    db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    value = experiment.catalog(db, include_context=args.all_games,
                                               limit=args.limit, offset=args.offset)
            elif args.command == "detail":
                value = experiment.detail(db, args.game_id, revision=args.revision)
            else:
                value = experiment.export_game(db, args.game_id, revision=args.revision)
    print(encoded(value).decode())


if __name__ == "__main__":
    main()
