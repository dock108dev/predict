"""Independent native discovery and paced, deduplicated Dashboard book refresh."""

import asyncio
from collections import Counter, defaultdict
from datetime import timedelta

from app.comparison.native_observation import adopt
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
IDENTITY_RECHECK_LEAD = timedelta(seconds=18)
IDENTITY_RETRY_WAIT = timedelta(seconds=15)


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
        self.stream = None
        self.progress = dict(
            state="starting",
            source_authority="official_venue_apis",
            access_gaps={"prophetx": "production_market_data_key_required"},
            league_access_gaps={"prophetx": {}},
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
        from psycopg.errors import LockNotAvailable

        from app.research.records import LOCK as STORAGE_ADMISSION_LOCK
        from app.storage.native_trading import PUBLICATION_LOCK, publish
        from .mens_d1_jobs import _late_capture_due
        from .runtime_status import AUTHORITY_LOCK

        with self.connector() as db:
            # Take the session locks before the snapshot so waiters see the
            # preceding native commit and the latest runtime authority.
            # The dedicated connection releases both locks when it closes.
            try:
                db.execute("SELECT pg_advisory_lock(%s)", (PUBLICATION_LOCK,))
                db.execute("SELECT pg_advisory_lock_shared(%s)", (AUTHORITY_LOCK,))
            except LockNotAvailable:
                return dict(state="deferred", reason="native_publication_lock_timeout")
            if self.protected() or _late_capture_due(db, self.now()):
                return dict(state="deferred", reason="protected_checkpoint")
            # Protected claims and their storage writes use this same research
            # lock. Optional native work yields if admission is already active.
            if not db.execute(
                "SELECT pg_try_advisory_lock(%s) acquired", (STORAGE_ADMISSION_LOCK,)
            ).fetchone()["acquired"]:
                return dict(state="deferred", reason="native_storage_admission_busy")
            with db.transaction():
                db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
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
                if observations and not accepted:
                    return dict(state="deferred", reason="native_source_paused")
                at = self.now()
                prune = self.last_pruned is None or at - self.last_pruned >= timedelta(
                    minutes=1
                )
                result = publish(db, accepted, at=at, prune=prune)
            if prune:
                self.last_pruned = at
            return result

    async def save(self, observations):
        from .bulk_checkpoint import owned_thread

        values = list(observations.items())
        for start in range(0, len(values) or 1, WRITE_BATCH):
            if not self.enabled() or self.protected():
                return False
            result = await owned_thread(
                self.write, dict(values[start : start + WRITE_BATCH])
            )
            self.references.update(result.pop("references", {}))
            # The writer has exited its transaction. A partial admission can
            # commit rows before reporting that the remaining work deferred.
            if result.get("published", 0):
                self.progress["last_publication"] = self.now().isoformat()
            if result.get("state") == "deferred":
                self.progress.update(result)
                return False
        self.progress.update(state="ready", reason=None)
        return True

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
                    league_gaps = self.progress["league_access_gaps"]["prophetx"]
                    if reason and reason.startswith("prophetx_tournament_"):
                        league_gaps[league] = reason
                    elif reason and reason != "deferred":
                        self.progress["access_gaps"]["prophetx"] = reason
                    elif not reason:
                        league_gaps.pop(league, None)
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
            due = binding.get("terms_valid_until")
            if venue_filter in ("kalshi", "polymarket_us") and (
                not due or stamp(due) <= at
            ):
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
            near = starts <= at + timedelta(hours=2)
            hot = exact_ref and near
            due += timedelta(seconds=3 if hot else 30)
            return due, starts, key, hot, near, bindings

        result, hot_pmus = {}, {}
        for venue, groups in by_venue.items():
            due = sorted(
                ranked for item in groups.items()
                if (ranked := rank(item))[0] <= at < ranked[1]
            )
            hot = [row for row in due if row[3]]
            near = [row for row in due if row[4] and not row[3]]
            distant = [row for row in due if not row[4]]
            limit = BOOKS_PER_TURN[venue]
            share = max(1, limit // 4)
            distant_reserve = min(len(distant), share)
            near_reserve = min(len(near), share)
            hot_count = min(len(hot), limit - near_reserve - distant_reserve)
            near_count = min(len(near), limit - hot_count - distant_reserve)
            selected = hot[:hot_count] + near[:near_count] + distant[: limit - hot_count - near_count]
            for _, _, key, _, _, bindings in selected:
                self.attempted[key] = at
                result.update(bindings)
            if venue == "polymarket_us":
                # Keep the websocket cohort stable across turns. REST still
                # rotates through the rest of the league and alternate slate.
                subscribed = sorted(
                    map(rank, groups.items()),
                    key=lambda row: (not row[3], row[1], row[2]),
                )
                for _, _, _, hot_book, _, bindings in subscribed[:32]:
                    if hot_book:
                        hot_pmus.update(bindings)
        return result, hot_pmus

    def _identity_scope(self, venue, attempted):
        at = self.now()
        scopes = {}
        for cid, binding in self.bindings.items():
            if binding["venue"] != venue:
                continue
            event = binding["_record"]["event"]
            start = stamp(event["scheduled_start"])
            key = event["competition"], start
            if not at < start <= at + timedelta(hours=2):
                continue
            deadline = binding.get("terms_valid_until")
            if deadline and stamp(deadline) > at + IDENTITY_RECHECK_LEAD:
                continue
            if key in attempted and at - attempted[key] < IDENTITY_RETRY_WAIT:
                continue
            exact = bool(self.references.get(cid) and self.references[cid] > at)
            scopes[key] = exact or scopes.get(key, False)
        return min(
            scopes,
            key=lambda key: (
                not scopes[key],
                attempted.get(key, at - timedelta(days=1)),
                key[1],
            ),
            default=None,
        )

    async def refresh_identity(self, _, native, venue):
        """Renew identity for known priority occurrences independently of depth."""
        attempted = {}
        while True:
            if not self.enabled(venue) or self.protected():
                await asyncio.sleep(1)
                continue
            scope = self._identity_scope(venue, attempted)
            if scope is None:
                await asyncio.sleep(1)
                continue
            at = self.now()
            attempted = {key: prior for key, prior in attempted.items() if key[1] > at}
            attempted[scope] = at
            league, start = scope
            window = start, start + timedelta(milliseconds=1)
            products = await asyncio.to_thread(self.products)
            if not self.enabled(venue) or self.protected():
                continue
            cutoff = self.now() + timedelta(seconds=READ_SECONDS)
            if venue == "kalshi":
                found = await Catalog().read(
                    native,
                    league,
                    {},
                    cutoff=cutoff,
                    products=products,
                    discover_window=window,
                )
            else:
                found = await pmus(
                    native,
                    league,
                    {},
                    at=at,
                    cutoff=cutoff,
                    products=products,
                    discover_window=window,
                )
            if self.enabled(venue) and not self.protected():
                for cid, binding in found.items():
                    if cid in self.bindings and binding.get("terms_valid_until"):
                        current = self.bindings[cid].get("terms_valid_until")
                        if not current or stamp(binding["terms_valid_until"]) > stamp(
                            current
                        ):
                            self.bindings[cid] = binding
            await asyncio.sleep(1)

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
            for cid, book in (await stream.read(hot_pmus, cutoff, new_only=True)).items():
                results[cid] = adopt(results.get(cid), book)
        pending = {cid: b for cid, b in bindings.items() if cid not in results}
        results.update(await native.read_native(pending, cutoff, batch=True))
        return results

    async def read_prophetx(self, plan, cutoff):
        if self.prophetx is None or not self.enabled("prophetx"):
            return {}
        events = {b["event_id"] for b in plan.values() if b["venue"] == "prophetx"}
        found, reason = await self.prophetx.refresh(events, cutoff)
        if reason and reason != "deferred":
            self.progress["access_gaps"]["prophetx"] = reason
        elif found:
            self.progress["access_gaps"].pop("prophetx", None)
        return {cid: book for cid, book in found.items() if cid in self.bindings}

    async def read_novig(self, novig, plan, cutoff):
        if not plan:
            return False
        batches = asyncio.Queue(maxsize=BOOKS_PER_TURN["novig"])

        async def publish_batches():
            while (batch := await batches.get()) is not None:
                await self.save(batch)

        queued = False
        # A turn contains at most one batch per planned event. The writer
        # stays serial while Novig's paced reads use their remaining cutoff.
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(publish_batches())
            async for batch in self._novig_batches(novig, plan, cutoff):
                await batches.put(batch)
                queued = True
            await batches.put(None)
        return queued

    async def _novig_batches(self, novig, plan, cutoff):
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
        for eid, wanted in grouped.items():
            if self.protected() or not self.enabled("novig") or self.now() >= cutoff:
                break
            results = {}
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
                if results:
                    yield results
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
            if results:
                yield results

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
                results = {}
                queued = await self.read_novig(novig, plan, cutoff)
                if not queued and (
                    self.last_pruned is None
                    or self.now() - self.last_pruned >= timedelta(minutes=1)
                ):
                    await self.save({})
            elif venue == "prophetx":
                results = await self.read_prophetx(plan, cutoff)
            else:
                results = await self.read_exchanges(
                    native, stream, plan, hot_pmus, cutoff
                )
            if results:
                await self.save(results)
            await asyncio.sleep(2)

    def reference_changes(self, previous):
        """Revalue retained books against committed SGO ingress, by league."""
        from app.comparison.fee_mode import read as read_fee_mode

        with self.connector() as db, db.transaction():
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            # The admission clock is written in the current-reference transaction.
            # A later page of an earlier started pull can advance it independently
            # of checkpoints, which retain their own frozen acquisition evidence.
            admissions = {
                row["league"]: row["admitted_at"]
                for row in db.execute("""SELECT league,max(admitted_at) admitted_at
                    FROM public.current_sgo_delivery_clock WHERE admitted_at IS NOT NULL
                    GROUP BY league""")
            }
            fee_revision = read_fee_mode(db)["revision"]
            cursor = admissions, fee_revision
            changed = None
            if previous is not None and previous[1] == fee_revision:
                changed = [league for league, admitted in admissions.items()
                           if previous[0].get(league) != admitted]
            if changed == []:
                return cursor, {}
            at = self.now()
            rows = db.execute(
                """SELECT id,book,record FROM public.native_trading_offer
                WHERE active AND starts_at>%s AND starts_at<=%s AND book_valid_until>%s
                AND (%s::text[] IS NULL OR league=ANY(%s))
                ORDER BY starts_at,id""",
                (at, at + timedelta(hours=24), at, changed, changed),
            ).fetchall()
            return cursor, {
                row["id"]: dict(row["book"], _record=row["record"]) for row in rows
            }

    async def references_loop(self, *_):
        previous = None
        while True:
            if self.enabled() and not self.protected():
                previous = await self.revalue_references(previous)
            await asyncio.sleep(5)

    async def revalue_references(self, previous):
        cursor, books = await asyncio.to_thread(self.reference_changes, previous)
        if books and not await self.save(books):
            return previous
        return cursor

    async def run(self, novig, native):
        from .native_trading_prophetx import MarketData, credentials
        from .native_trading_pmus_stream import DashboardMarketStream

        self.stream = stream = DashboardMarketStream(
            now=self.now,
            allowed=lambda: self.enabled("polymarket_us") and not self.protected(),
        )

        async def supervise(name, work, *args):
            while True:
                try:
                    await work(novig, native, *args)
                except Exception as error:
                    from app.diagnostics import failure

                    failure(__name__, name, error)
                    self.progress.update(state="degraded", reason=type(error).__name__)
                else:
                    self.progress.update(state="degraded", reason=name + "_exited")
                await asyncio.sleep(5)

        try:
            try:
                config = await asyncio.to_thread(credentials)
                self.prophetx = MarketData(
                    config,
                    now=self.now,
                    allowed=lambda: self.enabled("prophetx"),
                    requests=self.owner.service.config["requests_per_source"],
                    bytes_limit=self.owner.service.config["source_bytes"],
                )
                self.progress["access_gaps"].pop("prophetx", None)
            except ValueError as error:
                self.progress["access_gaps"]["prophetx"] = str(error)

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
                for venue in ("kalshi", "polymarket_us"):
                    tasks.create_task(
                        supervise(
                            "native_identity_" + venue, self.refresh_identity, venue
                        )
                    )
                tasks.create_task(supervise("native_references", self.references_loop))
        finally:
            try:
                await stream.close()
            finally:
                self.stream = None
                if self.prophetx is not None:
                    client, self.prophetx = self.prophetx, None
                    await client.close()
