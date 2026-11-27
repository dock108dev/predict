"""Independent native discovery and paced, deduplicated Dashboard book refresh."""

import asyncio
from collections import Counter, defaultdict
from datetime import timedelta

from app.research.experiment import utc
from app.storage.store import connect, stamp

from .current_policy import aggregate_scope, native_markets
from .dashboard_kalshi import Catalog
from .dashboard_pmus import read as pmus
from .native_trading_novig import discover as novig_discover, bindings as novig_bindings
from .novig_experiment_depth import book_depth

DISCOVERY_SECONDS = 45
READ_SECONDS = 6
BOOKS_PER_TURN = {"novig": 3, "kalshi": 16, "polymarket_us": 6, "prophetx": 12}
MAX_BINDINGS = 32768
WRITE_BATCH = 24


class NativeTrading:
    def __init__(self, owner, *, connector=connect, now=utc):
        self.owner, self.connector, self.now = owner, connector, now
        self.catalog = Catalog()
        self.bindings = {}
        self.attempted = {}
        self.discovered = {}
        self.references = {}
        self.last_pruned = None
        self.prophetx = None
        self.progress = dict(
            state="starting",
            source_authority="official_venue_apis",
            access_gaps={"prophetx": "production_market_data_key_required"},
        )

    def enabled(self, venue=None):
        service = self.owner.service
        return (
            service.dispatch
            and not service.globally_stopped
            and (venue is None or venue not in service.paused_sources)
        )

    def protected(self):
        return self.owner._near_checkpoint()

    def products(self):
        from app.fees.product_schedules import read_all

        with self.connector() as db:
            return read_all(db)

    def write(self, observations):
        from app.storage.native_trading import publish
        from .mens_d1_jobs import _late_capture_due

        with self.connector() as db, db.transaction():
            db.execute("SELECT pg_advisory_xact_lock(901095)")
            from .runtime_status import AUTHORITY_LOCK

            db.execute("SELECT pg_advisory_xact_lock_shared(%s)", (AUTHORITY_LOCK,))
            runtime = db.execute(
                "SELECT runtime_id,dispatch,global_stopped,paused_sources FROM public.data_runtime WHERE singleton"
            ).fetchone()
            if runtime and (
                runtime["global_stopped"]
                or not runtime["dispatch"]
                or str(runtime["runtime_id"]) != self.owner.service.runtime_id
            ):
                return dict(state="deferred", reason="native_runtime_authority_changed")
            if (
                not self.enabled()
                or self.protected()
                or _late_capture_due(db, self.now())
            ):
                return dict(state="deferred", reason="protected_checkpoint")
            paused = set(runtime["paused_sources"]) if runtime else set()
            accepted = {
                key: value
                for key, value in observations.items()
                if self.enabled(value["venue"]) and value["venue"] not in paused
            }
            at = self.now()
            prune = self.last_pruned is None or at - self.last_pruned >= timedelta(
                minutes=1
            )
            result = publish(db, accepted, at=at, prune=prune)
            if prune:
                self.last_pruned = at
            return result

    async def save(self, observations):
        values = list(observations.items())
        for start in range(0, len(values) or 1, WRITE_BATCH):
            if not self.enabled() or self.protected():
                return
            result = await asyncio.to_thread(
                self.write, dict(values[start : start + WRITE_BATCH])
            )
            self.references.update(result.pop("references", {}))
            if result.get("state") == "deferred":
                self.progress.update(result)
                return
        self.progress.update(
            state="ready", reason=None, last_publication=self.now().isoformat()
        )

    async def discovery(self, novig, native):
        leagues = aggregate_scope(self.owner.service.config)
        families = set(native_markets(self.owner.service.config))
        # Two-hour windows bound the larger college slate. The first window
        # is revisited before remote windows; native inventory never depends
        # on a represented trading quote in the aggregate feed.
        index = 0
        while True:
            at = self.now()
            if not self.enabled() or self.protected():
                await asyncio.sleep(1)
                continue
            windows = [(league, block) for block in range(13) for league in leagues]
            pool = [key for key in windows if (key[1] == 0) == (index % 2 == 0)]
            scope = min(
                pool,
                key=lambda k: (
                    self.discovered.get(k, at - timedelta(days=1)),
                    k[1],
                    k[0],
                ),
            )
            league, block = scope
            anchor = at.replace(minute=0, second=0, microsecond=0)
            start = max(at, anchor + timedelta(hours=2 * block))
            end = min(at + timedelta(hours=24), anchor + timedelta(hours=2 * block + 2))
            cutoff = at + timedelta(seconds=READ_SECONDS)
            if (
                at - self.discovered.get(scope, at - timedelta(days=1))
            ).total_seconds() < DISCOVERY_SECONDS:
                index += 1
                await asyncio.sleep(1)
                continue
            self.discovered[scope] = at
            if start >= end:
                index += 1
                continue
            products = await asyncio.to_thread(self.products)

            async def find(venue):
                if not self.enabled(venue):
                    return {}
                if venue == "novig":
                    results, reasons = await novig_discover(
                        novig, league, start, end, cutoff=cutoff
                    )
                    self.progress["novig_discovery_reasons"] = dict(
                        Counter(r for r in reasons if r)
                    )
                    return results
                if venue == "kalshi":
                    return await self.catalog.read(
                        native,
                        league,
                        {},
                        cutoff=cutoff,
                        products=products,
                        discover_window=(start, end),
                    )
                if venue == "prophetx":
                    if self.prophetx is None:
                        return {}
                    result, reason = await self.prophetx.discover(
                        league, start, end, cutoff
                    )
                    if reason:
                        self.progress["access_gaps"]["prophetx"] = reason
                    else:
                        self.progress["access_gaps"].pop("prophetx", None)
                    return result
                return await pmus(
                    native,
                    league,
                    {},
                    at=at,
                    cutoff=cutoff,
                    products=products,
                    discover_window=(start, end),
                )

            for venue, found in zip(
                ("novig", "kalshi", "polymarket_us", "prophetx"),
                await asyncio.gather(
                    *(
                        find(venue)
                        for venue in ("novig", "kalshi", "polymarket_us", "prophetx")
                    ),
                    return_exceptions=True,
                ),
                strict=True,
            ):
                if isinstance(found, Exception):
                    from app.diagnostics import failure

                    failure(__name__, "native_discovery_" + venue, found)
                    continue
                found = {
                    cid: b
                    for cid, b in found.items()
                    if b["contract"]["family"] in families
                }
                for cid, binding in found.items():
                    if cid in self.bindings or len(self.bindings) < MAX_BINDINGS:
                        self.bindings[cid] = binding
                # Novig's catalog itself is an official top-of-book receipt.
                if found:
                    await self.save(found)
            self.bindings = {
                cid: b
                for cid, b in self.bindings.items()
                if b.get("_record")
                and self.now()
                < stamp(b["_record"]["event"]["scheduled_start"])
                <= self.now() + timedelta(hours=24)
            }
            self.references = {
                cid: value
                for cid, value in self.references.items()
                if cid in self.bindings
            }
            index += 1
            self.progress.update(
                discovery_cycles=index,
                inventory=len(self.bindings),
                last_scope=[league, block],
                public_requests=dict(native.requests),
            )
            await asyncio.sleep(1)

    def _book_plan(self, venue_filter):
        at = self.now()
        by_venue = defaultdict(dict)
        for cid, binding in self.bindings.items():
            if binding["venue"] != venue_filter:
                continue
            venue = binding["venue"]
            key = venue, binding["event_id"], binding["market_id"]
            by_venue[venue].setdefault(key, {})[cid] = binding
        self.attempted = {
            key: value
            for key, value in self.attempted.items()
            if key[0] != venue_filter or key in by_venue[venue_filter]
        }

        def rank(item):
            key, bindings = item
            starts = min(
                stamp(b["_record"]["event"]["scheduled_start"])
                for b in bindings.values()
            )
            due = self.attempted.get(key, at - timedelta(days=1))
            exact_ref = any(
                self.references.get(cid) and self.references[cid] > at
                for cid in bindings
            )
            hot = exact_ref and starts <= at + timedelta(hours=2)
            due += timedelta(seconds=3 if hot else 30)
            return due, starts, key, hot, bindings

        result, hot_pmus = {}, {}
        for venue, groups in by_venue.items():
            due = sorted(
                ranked for item in groups.items() if (ranked := rank(item))[0] <= at
            )
            hot = [row for row in due if row[3]]
            background = [row for row in due if not row[3]]
            limit = BOOKS_PER_TURN[venue]
            reserve = max(1, limit // 4) if background else 0
            first = min(len(hot), limit - reserve)
            background_size = min(len(background), limit - first)
            selected = hot[: limit - background_size] + background[:background_size]
            for _, _, key, hot_book, bindings in selected:
                self.attempted[key] = at
                result.update(bindings)
            if venue == "polymarket_us":
                # Keep the websocket cohort stable across turns. REST still
                # rotates through the rest of the league and alternate slate.
                subscribed = sorted(
                    map(rank, groups.items()),
                    key=lambda row: (not row[3], row[1], row[2]),
                )
                for _, _, _, hot_book, bindings in subscribed[:32]:
                    if hot_book:
                        hot_pmus.update(bindings)
        return result, hot_pmus

    def synchronized(self, bindings, cutoff):
        from .native_experiment_depth import synchronized_native

        with self.connector() as db:
            return synchronized_native(db, bindings, at=self.now(), cutoff=cutoff)

    async def read_exchanges(self, native, stream, plan, hot_pmus, cutoff):
        bindings = {
            cid: b
            for cid, b in plan.items()
            if b["venue"] in ("kalshi", "polymarket_us")
        }
        results = (
            await asyncio.to_thread(self.synchronized, bindings, cutoff)
            if bindings
            else {}
        )
        if stream is not None:
            results.update(await stream.read(hot_pmus, cutoff))
        pending = {cid: b for cid, b in bindings.items() if cid not in results}
        results.update(await native.read_native(pending, cutoff, batch=True))
        return results

    async def read_prophetx(self, plan, cutoff):
        if self.prophetx is None or not self.enabled("prophetx"):
            return {}
        events = {b["event_id"] for b in plan.values() if b["venue"] == "prophetx"}
        found, reason = await self.prophetx.refresh(events, cutoff)
        if reason:
            self.progress["access_gaps"]["prophetx"] = reason
        return {cid: book for cid, book in found.items() if cid in self.bindings}

    async def read_novig(self, novig, plan, cutoff):
        def revoke(proof, reason, bindings):
            received = proof["received_at"]
            for cid, binding in bindings.items():
                results[cid] = dict(
                    binding,
                    reason=reason,
                    levels=[],
                    complete=False,
                    received_at=received,
                    valid_until=received,
                    receipts=[proof],
                )

        grouped = defaultdict(set)
        for b in plan.values():
            if b["venue"] == "novig":
                grouped[b["event_id"]].add(b["market_id"])
        results = {}
        for eid, wanted in grouped.items():
            if results:
                await self.save(results)
                results = {}
            if self.protected() or not self.enabled("novig") or self.now() >= cutoff:
                break
            (event, proof, reason), inventory = await asyncio.gather(
                novig.read_event_metadata(eid, cutoff, lifecycle=True),
                novig.read_event(eid, cutoff, moneyline=True),
            )
            if (
                reason == "native_market_withdrawn"
                or event
                and event["status"] != "OPEN_PREGAME"
            ):
                revoke(
                    proof,
                    reason or "native_market_halted",
                    {
                        cid: b
                        for cid, b in self.bindings.items()
                        if b["venue"] == "novig" and b["event_id"] == eid
                    },
                )
                continue
            if reason:
                continue
            if inventory.reason:
                continue
            refreshed = novig_bindings(event, inventory.markets, proof, at=self.now())
            for cid, binding in refreshed.items():
                if cid in self.bindings or len(self.bindings) < MAX_BINDINGS:
                    self.bindings[cid] = binding
            results.update(refreshed)
            for mid in sorted(wanted):
                if (
                    self.protected()
                    or not self.enabled("novig")
                    or self.now() >= cutoff
                ):
                    break
                sides = {
                    cid: b for cid, b in refreshed.items() if b["market_id"] == mid
                }
                if not sides:
                    _, witness, unavailable = await novig.read_market_metadata(
                        eid, mid, cutoff
                    )
                    from app.comparison.native_observation import WITHDRAWALS

                    if unavailable in WITHDRAWALS:
                        revoke(
                            witness,
                            unavailable,
                            {
                                cid: b
                                for cid, b in plan.items()
                                if b["venue"] == "novig"
                                and b["event_id"] == eid
                                and b["market_id"] == mid
                            },
                        )
                    continue
                detail = await novig.read_book(mid, cutoff)
                for cid, base in sides.items():
                    book = book_depth(
                        base["_binding"], detail, self.now(), catalog=base
                    )
                    if not book.get("reason"):
                        results[cid] = dict(book, _record=base["_record"])
        return results

    async def books(self, novig, native, venue, stream=None):
        while True:
            if not self.enabled(venue) or self.protected():
                if stream is not None:
                    await stream.read({}, self.now())
                await asyncio.sleep(1)
                continue
            plan, hot_pmus = self._book_plan(venue)
            cutoff = self.now() + timedelta(seconds=READ_SECONDS)
            if venue == "novig":
                results = await self.read_novig(novig, plan, cutoff)
            elif venue == "prophetx":
                results = await self.read_prophetx(plan, cutoff)
            else:
                results = await self.read_exchanges(
                    native, stream, plan, hot_pmus, cutoff
                )
            if results:
                await self.save(results)
            elif venue == "novig" and (
                self.last_pruned is None
                or self.now() - self.last_pruned >= timedelta(minutes=1)
            ):
                await self.save({})
            await asyncio.sleep(2)

    def reference_changes(self, previous):
        """Replay only retained hot books when independent SGO inputs advance."""
        from app.comparison.fee_mode import read as read_fee_mode

        with self.connector() as db, db.transaction():
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            latest = db.execute("""SELECT p.started_order,r.received_at FROM public.market_pull p
                JOIN public.market_pull_receipt r USING(pull_id)
                ORDER BY p.started_order DESC,r.received_at DESC LIMIT 1""").fetchone()
            cursor = latest, read_fee_mode(db)
            if previous == cursor:
                return cursor, {}
            at = self.now()
            rows = db.execute(
                """SELECT id,book,record FROM public.native_trading_offer
                WHERE active AND starts_at>%s AND starts_at<=%s AND book_valid_until>%s
                ORDER BY starts_at,id""",
                (at, at + timedelta(hours=24), at),
            ).fetchall()
            return cursor, {
                row["id"]: dict(row["book"], _record=row["record"]) for row in rows
            }

    async def references_loop(self, *_):
        previous = None
        while True:
            if self.enabled() and not self.protected():
                cursor, books = await asyncio.to_thread(
                    self.reference_changes, previous
                )
                if books:
                    await self.save(books)
                if self.enabled() and not self.protected():
                    previous = cursor
            await asyncio.sleep(5)

    async def run(self, novig, native):
        from .native_trading_prophetx import MarketData, credentials
        from .native_trading_pmus_stream import DashboardMarketStream

        stream = DashboardMarketStream(
            now=self.now,
            allowed=lambda: self.enabled("polymarket_us") and not self.protected(),
        )

        try:
            config = await asyncio.to_thread(credentials)
            self.prophetx = MarketData(
                config,
                now=self.now,
                allowed=lambda: self.enabled("prophetx"),
                requests=self.owner.service.config["requests_per_source"],
                bytes_limit=self.owner.service.config["source_bytes"],
            )
            _, _, reason = await self.prophetx.get(
                "/affiliate/get_tournaments", {}, self.now() + timedelta(seconds=3)
            )
            if reason:
                self.progress["access_gaps"]["prophetx"] = reason
        except ValueError as error:
            self.progress["access_gaps"]["prophetx"] = str(error)

        async def supervise(name, work, *args):
            while True:
                try:
                    await work(novig, native, *args)
                except Exception as error:
                    from app.diagnostics import failure

                    failure(__name__, name, error)
                    self.progress.update(state="degraded", reason=type(error).__name__)
                    await asyncio.sleep(5)

        try:
            async with asyncio.TaskGroup() as tasks:
                tasks.create_task(supervise("native_discovery", self.discovery))
                for venue in BOOKS_PER_TURN:
                    tasks.create_task(
                        supervise(
                            "native_books_" + venue,
                            self.books,
                            venue,
                            stream if venue == "polymarket_us" else None,
                        )
                    )
                tasks.create_task(supervise("native_references", self.references_loop))
        finally:
            await stream.close()
            if self.prophetx is not None:
                await self.prophetx.close()
