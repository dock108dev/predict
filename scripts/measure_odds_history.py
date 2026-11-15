"""Measure retained odds evidence and replay Parquet locally without provider requests."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from time import perf_counter
import gzip
import json
import re
import subprocess
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

schema = pa.schema(
    [
        ("feed", pa.string()),
        ("venue", pa.string()),
        ("event", pa.string()),
        ("market", pa.string()),
        ("outcome", pa.string()),
        ("side", pa.string()),
        ("period", pa.string()),
        ("line", pa.string()),
        ("price", pa.string()),
        ("price_units", pa.string()),
        ("size", pa.string()),
        ("size_units", pa.string()),
        ("state", pa.string()),
        ("source_at", pa.timestamp("us", tz="UTC")),
        ("received_at", pa.timestamp("us", tz="UTC")),
        ("sequence", pa.string()),
        ("revision", pa.string()),
        ("evidence_id", pa.string()),
        ("change_id", pa.binary(32)),
        ("definition_id", pa.binary(32)),
        ("record_kind", pa.string()),
    ]
)
definition_schema = pa.schema(
    [
        ("definition_id", pa.binary(32)),
        ("event", pa.string()),
        ("definition", pa.string()),
    ]
)
escape = re.compile(r"\\([bfnrtv\\]|[0-7]{1,3}|x[0-9a-fA-F]{1,2}|.)")
escape_chars = dict(zip("bfnrtv\\", "\b\f\n\r\t\v\\"))


def copy_value(value):
    if value == r"\N":
        return None

    def plain(match):
        literal = match[1]
        if literal in escape_chars:
            return escape_chars[literal]
        if literal.startswith("x"):
            return chr(int(literal[1:], 16))
        if literal[0].isdigit():
            return chr(int(literal, 8))
        return literal

    return escape.sub(plain, value) if "\\" in value else value


def copy_rows(filename, selected):
    table, columns = "", None
    with filename.open() as stream:
        for raw in stream:
            if raw.startswith("COPY "):
                table = raw.split()[1].split(".")[-1]
                columns = (
                    raw.split(" (")[1].split(") FROM")[0].split(", ")
                    if selected(table)
                    else None
                )
                continue
            if raw == "\\.\n":
                columns = None
            if columns is not None:
                fields = raw.rstrip("\n").split("\t")
                assert len(fields) == len(columns), (table, len(fields), len(columns))
                yield table, dict(zip(columns, map(copy_value, fields), strict=True))


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=as_json,
    )


def as_json(value):
    return value.hex() if isinstance(value, bytes) else value.isoformat()


def key_of(value):
    return sha256(canonical(value).encode()).digest()


def stamp(value):
    return datetime.fromisoformat(value).astimezone(timezone.utc) if value else None


def decimal_key(value):
    if value is None:
        return None
    return Decimal(value)


def parquet_size(rows, schema):
    output = BytesIO()
    pq.write_table(
        pa.Table.from_pylist(rows, schema=schema),
        output,
        compression="zstd",
        compression_level=3,
        row_group_size=4096,
        write_statistics=True,
    )
    return output.getvalue()


def gzip_rows(rows):
    raw = "\n".join(map(canonical, rows)).encode()
    return gzip.compress(raw, compresslevel=6, mtime=0)


def measure(root):
    events = {}
    native_books = []
    ladders = {}
    metadata_refs = set()
    native_bodies = set()
    contract_fields = defaultdict(dict)
    quote_observations = defaultdict(list)
    context = {}
    history_state = {}
    sgo_quotes = {}
    sgo_frames = []
    history_count = Counter()
    frame_witness = Counter()
    head_count = Counter()
    witness_receipts = defaultdict(set)
    witness_receive_times = defaultdict(list)
    confirmations = defaultdict(list)
    audit_days = defaultdict(Counter)

    for name, row in copy_rows(
        root / "metadata.sql",
        lambda name: name.startswith(
            ("current_contract_p", "current_native_market_recovery_p")
        ),
    ):
        if name.startswith("current_native_market_recovery"):
            if row["metadata_id"]:
                metadata_refs.add(row["metadata_id"][2:])
            continue
        if row["venue"] not in ("kalshi", "polymarket_us"):
            continue
        k = (
            row["venue"],
            row["event_id"],
            row["native_market_id"],
            row["native_outcome_id"],
        )
        facts = json.loads(row["facts"])
        contract_fields[k][row["native_side"]] = {
            f: facts.get(f)
            for f in (
                "market_identity",
                "comparison_source_metadata",
                "settlement",
                "canonical_outcome",
                "resolution_identity",
                "canonical_contract",
                "verified",
            )
            if f in facts
        }

    def add_sgo(facts, revision, evidence_kind):
        identity = (
            "sportsgameodds",
            facts["venue"],
            facts["event_id"],
            facts["market"],
            facts["odd_id"],
            facts["side"],
            facts["period"],
            facts["line"],
        )
        recv = stamp(facts["received_at"])
        ref = {
            field: facts.get(field)
            for field in (
                "aliases",
                "bookmaker_market_link",
                "league",
                "teams",
                "starts_at",
                "period",
                "market",
                "opposing_odd_id",
                "side",
                "line",
                "settlement",
                "alternate",
            )
        }
        context[identity] = ref
        state = (
            "available" if facts["available"] else "unavailable",
            facts["provider_available"],
            facts["unavailable_reason"],
        )
        row = dict(
            zip(
                (
                    "feed",
                    "venue",
                    "event",
                    "market",
                    "outcome",
                    "side",
                    "period",
                    "line",
                ),
                identity,
            )
        )
        row.update(
            price=facts["price_american"],
            price_units="american_odds",
            size=None,
            size_units=None,
            state=state[0],
            source_at=stamp(facts["source_at"]),
            received_at=recv,
            sequence=None,
            revision=revision,
            evidence_id=facts["receipt_sha256"],
        )
        material = decimal_key(row["price"]), None, state
        quote_observations[identity].append((material, row, evidence_kind))
        witness_receipts["sportsgameodds"].add(facts["receipt_sha256"])
        witness_receive_times["sportsgameodds"].append(recv)

    for name, row in copy_rows(
        root / "extract.sql", lambda name: name != "current_native_market_recovery_p00"
    ):
        if name == "current_event":
            events[row["id"]] = dict(
                native_event_id=row["native_event_id"], facts=json.loads(row["facts"])
            )
        elif name == "current_native_market_body":
            native_bodies.add(row["id"][2:])
        elif name == "native_book_revision":
            native_books.append(row)
        elif name == "native_ladder_revision":
            levels = json.loads(row["levels"])
            if levels:
                ladders[row["id"]] = levels[0]
        elif name == "current_sgo_history":
            history_count[row["kind"]] += 1
            facts = json.loads(row["facts"])
            if row["kind"] == "reference":
                add_sgo(facts, row["revision"], "historical")
                sgo_quotes[row["identity"], row["revision"]] = facts
            else:
                frame_witness["prior"] += 1
                sgo_frames.append(("prior", facts))
        elif name == "sgo_quote_revision":
            head_count["sgo_quote_" + row["is_current"]] += 1
            facts = json.loads(row["facts"])
            add_sgo(
                facts,
                row["revision"],
                "head" if row["is_current"] == "t" else "historical",
            )
            sgo_quotes[row["id"], row["revision"]] = facts
        elif name == "sgo_event_evidence":
            if row["kind"] == "history_state":
                history_state = {
                    k: int(row[k])
                    for k in (
                        "recorded",
                        "skipped_capacity",
                        "skipped_runway",
                        "evicted_capacity",
                    )
                }
            elif row["kind"] == "frame":
                frame_witness["head"] += 1
                sgo_frames.append(("head", json.loads(row["facts"])))

    for name, row in copy_rows(
        root / "acquisition.sql",
        lambda name: name.startswith("current_acquisition_market_p"),
    ):
        if row["metadata_id"]:
            metadata_refs.add(row["metadata_id"][2:])

    replay_ranges = defaultdict(list)
    for name, row in copy_rows(
        root / "replay.sql",
        lambda name: name.startswith(
            ("current_acquisition_image_p", "comparison_snapshot_p")
        ),
    ):
        if name.startswith("current_acquisition_image_p"):
            replay_ranges[row["source"], row["disposition"]].append(
                stamp(row["received_at"])
            )
        else:
            replay_ranges[
                "comparison_snapshot",
                "automatic" if row["automatic"] == "t" else "manual",
            ].append(stamp(row["captured_at"]))
    frame_reconciliation = Counter()
    selection = None
    for kind, frame in sgo_frames:
        pairs = [tuple(x) for x in frame["members"]]
        present = sum(pair in sgo_quotes for pair in pairs)
        frame_reconciliation[kind + " frames"] += 1
        frame_reconciliation[kind + " members"] += len(pairs)
        frame_reconciliation[kind + " matched members"] += present
        if pairs and present == len(pairs):
            frame_reconciliation[kind + " complete nonempty frames"] += 1
            if selection is None or len(pairs) > selection["members"]:
                selection = dict(
                    event=frame["event_id"],
                    received_at=frame["received_at"],
                    members=len(pairs),
                    kind=kind,
                    unique_markets=len(
                        {
                            (
                                sgo_quotes[pair]["market"],
                                sgo_quotes[pair]["period"],
                                sgo_quotes[pair]["line"],
                            )
                            for pair in pairs
                        }
                    ),
                )

    seen_native_sides = defaultdict(set)
    for book in sorted(
        native_books, key=lambda row: (stamp(row["received_at"]), row["id"])
    ):
        feed = book["venue"]
        event = events[book["event_id"]]
        received = stamp(book["received_at"])
        source = stamp(book["source_at"])
        witness_receive_times[feed].append(received)
        witness_receipts[feed].add(book["id"])
        head_count[feed + "_" + book["is_current"]] += 1
        refs = json.loads(book["ladder_refs"])
        confirm = json.loads(book["confirmation"]) if book["confirmation"] else None
        event_market = (feed, event["native_event_id"], book["native_market_id"])
        sides = seen_native_sides[event_market]
        sides.update(
            (outcome, side) for outcome, values in refs.items() for side in values
        )
        for outcome, side in sorted(sides):
            revid = refs.get(outcome, {}).get(side)
            level = ladders[revid] if revid else (None, None, None, None)
            contract = contract_fields.get(
                (feed, book["event_id"], book["native_market_id"], outcome)
            )
            facts = next(iter(contract.values())) if contract else {}
            market_identity = facts.get("market_identity") or {}
            identity = (
                feed,
                feed,
                event["native_event_id"],
                book["native_market_id"],
                outcome,
                side,
                market_identity.get("period"),
                market_identity.get("line"),
            )
            context[identity] = {"event": event["facts"], "side_contracts": contract}
            active = book["state"] == "active" and book["sync"] == "synchronized"
            state = "available" if active and revid else "unavailable"
            row = dict(
                zip(
                    (
                        "feed",
                        "venue",
                        "event",
                        "market",
                        "outcome",
                        "side",
                        "period",
                        "line",
                    ),
                    identity,
                )
            )
            row.update(
                price=level[0],
                price_units=level[1],
                size=level[2],
                size_units=level[3],
                state=state,
                source_at=source,
                received_at=received,
                sequence=book["sequence"] if book["sequence"] != "None" else None,
                revision=book["revision"],
                evidence_id=book["id"],
            )
            material = decimal_key(row["price"]), decimal_key(row["size"]), state
            quote_observations[identity].append(
                (material, row, "head" if book["is_current"] == "t" else "historical")
            )
        if confirm:
            confirmations[feed, received.date().isoformat()].append(
                dict(
                    event=event["native_event_id"],
                    market=book["native_market_id"],
                    sequence=book["sequence"],
                    confirmed_at=confirm["confirmed_at"],
                    received_at=confirm["received_at"],
                    proof_hash=confirm["sha256"],
                    basis=confirm["basis"],
                    generation=confirm["generation"],
                )
            )

    changes = defaultdict(list)
    definitions = defaultdict(dict)
    origins = defaultdict(Counter)
    for identity, observations in quote_observations.items():
        second_or_later = False
        previous = object()
        seen = set()
        for material, row, origin in sorted(
            observations,
            key=lambda v: (v[1]["received_at"], v[1]["revision"], v[1]["evidence_id"]),
        ):
            k = row["received_at"], row["revision"]
            if k in seen:
                continue
            seen.add(k)
            group = row["feed"], row["received_at"].date().isoformat()
            audit_days[group]["witnesses"] += 1
            origins[group][origin] += 1
            if previous == material:
                audit_days[group]["unchanged"] += 1
                continue
            previous = material
            first_or_change = "material_change" if second_or_later else "first_seen"
            second_or_later = True
            row["record_kind"] = first_or_change
            row["definition_id"] = key_of(context[identity])
            row["change_id"] = key_of(
                [identity, row["received_at"], row["revision"], row["evidence_id"]]
            )
            if row["period"] is not None:
                row["period"] = str(row["period"])
            if row["line"] is not None:
                row["line"] = str(row["line"])
            changes[group].append(row)
            definitions[group][row["definition_id"]] = dict(
                definition_id=row["definition_id"],
                event=row["event"],
                definition=canonical(context[identity]),
            )
            audit_days[group][first_or_change] += 1

    reports = {}
    largest_sgo_day = max(
        (group for group in changes if group[0] == "sportsgameodds"),
        key=lambda group: len(changes[group]),
        default=None,
    )
    for group, rows in sorted(changes.items()):
        rows.sort(
            key=lambda row: (
                row["event"],
                row["venue"],
                row["market"],
                row["outcome"],
                row["side"],
                row["received_at"],
            )
        )
        side = list(definitions[group].values())
        normalized = parquet_size(rows, schema)
        compressed_json = gzip_rows(rows)
        dim = parquet_size(side, definition_schema)
        event = Counter(row["event"] for row in rows).most_common(1)[0][0]
        target = [r for r in rows if r["event"] == event]
        cutoff = sorted(r["received_at"] for r in target)[len(target) // 2]
        started = perf_counter()
        selected = pq.read_table(
            BytesIO(normalized),
            filters=[("event", "=", event), ("received_at", "<=", cutoff)],
        ).to_pylist()
        read_seconds = perf_counter() - started
        started = perf_counter()
        json_replay = []
        for serialized in gzip.decompress(compressed_json).splitlines():
            row = json.loads(serialized)
            if row["event"] == event and stamp(row["received_at"]) <= cutoff:
                json_replay.append(row["change_id"])
        json_read_seconds = perf_counter() - started
        if Counter(json_replay) != Counter(r["change_id"].hex() for r in selected):
            raise ValueError("Archive witness replay mismatch")
        latest = {}
        for quote in sorted(selected, key=lambda r: r["received_at"]):
            ident = tuple(
                quote[k]
                for k in ("venue", "market", "outcome", "side", "period", "line")
            )
            latest[ident] = quote
        compression = dict(
            gzip=len(compressed_json),
            parquet=len(normalized),
            definitions_gzip=len(gzip_rows(side)),
            definitions_parquet=len(dim),
        )
        variants = {}
        if group == largest_sgo_day:
            for label, predicate in (
                ("winner_only", lambda row: row["market"] == "moneyline"),
                (
                    "identified_execution_books_or_pinnacle_circa",
                    lambda row: (
                        row["venue"]
                        in (
                            "novig",
                            "prophetx",
                            "pinnacle",
                            "circa",
                            "kalshi",
                            "polymarket",
                        )
                    ),
                ),
                (
                    "all_material_changes_after_first",
                    lambda row: row["record_kind"] == "material_change",
                ),
            ):
                subset = [row for row in rows if predicate(row)]
                dim_ids = {row["definition_id"] for row in subset}
                variants[label] = dict(
                    rows=len(subset),
                    quotes_parquet=len(parquet_size(subset, schema)),
                    definitions_parquet=len(
                        parquet_size(
                            [d for d in side if d["definition_id"] in dim_ids],
                            definition_schema,
                        )
                    ),
                )
        reports[" / ".join(group)] = dict(
            variants=variants,
            counts=audit_days[group],
            origins=origins[group],
            definitions=len(side),
            confirmation_count=len(confirmations[group]),
            confirmations_gzip=len(gzip_rows(confirmations[group])),
            within_day=(
                min(r["received_at"] for r in rows),
                max(r["received_at"] for r in rows),
            ),
            bytes=compression,
            replay_rows=len(selected),
            asof_sides=len(latest),
            replay_ms=read_seconds * 1000,
            json_replay_ms=json_read_seconds * 1000,
            replay_event=event,
            replay_cutoff=cutoff,
            replay_ids_sha256=sha256(
                b"".join(sorted(r["change_id"] for r in selected))
            ).hexdigest(),
        )

    result = dict(
        notes=[
            "Daily groups are UTC by original receipt. First observed is per retained dataset; historical change means an observed difference from the preceding surviving state. These are lower bounds on traffic, with biased latest survivors and rotations. Definitions are latest surviving context attributed for size only, never version reconstruction.",
            "SGO all bookmaker originals. Native top level per exact outcome and side after ladder join. Native timestamps are book clocks; the measurement does not pretend disconnected/stale intervals are reconstructible.",
        ],
        receipts={feed: len(value) for feed, value in witness_receipts.items()},
        receipt_windows={
            feed: [min(times), max(times)]
            for feed, times in witness_receive_times.items()
        },
        head_and_history_counts=head_count,
        frame_witness=frame_witness,
        sgo_history_counts=history_count,
        sgo_rotation=history_state,
        metadata_bodies=len(native_bodies),
        metadata_references=len(metadata_refs),
        orphaned_native_bodies=len(native_bodies - metadata_refs),
        native_contract_dimensions=len(contract_fields),
        replay_ranges={
            " / ".join(k): [len(v), min(v), max(v)] for k, v in replay_ranges.items()
        },
        frame_reconciliation=frame_reconciliation,
        selected_reconciled_frame=selection,
        reports=reports,
    )
    return result


def extract(pg_restore, dump, root):
    listing = subprocess.run(
        [pg_restore, "--list", dump],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ).stdout.splitlines()
    tables = {
        "extract": re.compile(
            r"current_event|current_native_market_body|current_sgo_history|native_book_revision|"
            r"native_ladder_revision|sgo_event_evidence|sgo_quote_revision"
        ),
        "metadata": re.compile(r"current_(?:contract|native_market_recovery)_p[0-9]+"),
        "acquisition": re.compile(r"current_acquisition_market_p[0-9]+"),
        "replay": re.compile(
            r"current_acquisition_image_p[0-9]+|comparison_snapshot_p[0-9]+"
        ),
    }
    for target, pattern in tables.items():
        entries = []
        for entry in listing:
            match = re.search(r" TABLE DATA public ([^ ]+) ", entry)
            if match and pattern.fullmatch(match[1]):
                entries.append(entry)
        if not entries:
            raise ValueError(f"Empty retained relation group {target}")
        include = root / f"{target}.list"
        include.write_text("\n".join(entries) + "\n")
        subprocess.run(
            [
                pg_restore,
                "--data-only",
                "--use-list",
                include,
                "--file",
                root / f"{target}.sql",
                dump,
            ],
            check=True,
            stderr=subprocess.DEVNULL,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        type=Path,
        help="PostgreSQL custom dump or its extracted COPY directory",
    )
    parser.add_argument(
        "--pg-restore",
        default="pg_restore",
        help="pg_restore matching the dump version",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Write aggregate results to this JSON file",
    )
    args = parser.parse_args()
    try:
        if args.source.is_dir():
            report = measure(args.source)
        else:
            with TemporaryDirectory(prefix="predict-history-measure-") as directory:
                root = Path(directory)
                extract(args.pg_restore, args.source, root)
                report = measure(root)
        args.output.write_text(json.dumps(report, indent=2, default=as_json) + "\n")
    except subprocess.CalledProcessError:
        parser.exit(
            1,
            "pg_restore failed. Use the matching major version and check the retained dump.\n",
        )
    except (AssertionError, ArithmeticError, LookupError, OSError, ValueError) as exc:
        parser.exit(
            1, f"Retained evidence measurement failed ({type(exc).__name__}).\n"
        )


if __name__ == "__main__":
    main()
