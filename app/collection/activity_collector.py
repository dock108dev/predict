"""One guarded SGO owner: independent Monitor and pregame Live collection clocks."""

import asyncio
from datetime import timedelta

from app.storage.store import connect, stamp
from . import activity_mode
from .bulk_checkpoint import owned_thread
from .current_policy import aggregate_scope, PregameWindowClosed
from .sportsgameodds_adapter import Traversal
from .sportsgameodds_collector import DailyObjectPacing, RejectedCursor


class ActivityBudgetDelayed(RuntimeError):
    def __init__(self, reason, retry_at):
        super().__init__(reason)
        self.retry_at = retry_at


def budget_admit(ledger, window_id, requested, at):
    """Read exposure, never alter or release a reservation/hold to fit a mode."""
    if ledger is None or window_id is None:
        return
    for seconds, ceiling in (
        (900, activity_mode.OBJECTS_PER_15_MINUTES),
        (86400, activity_mode.OBJECTS_PER_DAY),
    ):
        used = ledger.rolling_objects(window_id, since=at - timedelta(seconds=seconds))
        if used + requested > ceiling:
            expirations = ledger.rolling_expirations(window_id, now=at)
            deadlines = [
                when - timedelta(days=1) + timedelta(seconds=seconds)
                for when, _ in expirations
                if when - timedelta(days=1) + timedelta(seconds=seconds) > at
            ]
            raise ActivityBudgetDelayed(
                "operational_object_budget",
                min(deadlines, default=at + timedelta(seconds=60)),
            )


class ModeStore:
    def __init__(self, connector=connect):
        self.connector = connector

    def status(self, at):
        with self.connector() as db, db.transaction():
            activity_mode.expire(db, at=at)
            return activity_mode.read_status(db, at=at)

    def begin(self, kind, status, at):
        with self.connector() as db:
            return activity_mode.begin_run(db, kind, status, at=at)

    def update(self, run, **values):
        with self.connector() as db:
            activity_mode.update_run(db, run, **values)


class ActivityCollector:
    """One page per turn lets Live interleave without replacing Monitor's clock."""

    def __init__(self, worker, *, store=None):
        self.worker = worker
        self.store = store or ModeStore()
        self.monitor = None
        self.live = None
        self.monitor_due = None
        self.last_monitor_slot = None
        self.live_due = None
        self.retry_at = None
        self.initialized = False
        self.settings_revision = None
        self.previous_settings = None
        self.previous_mode = None
        self.next_kind = "live"

    async def status(self):
        return await owned_thread(self.store.status, self.worker.now())

    async def save(self, job, *, state="running", reason=None):
        progress = dict(
            league_index=job.get("league_index", 0),
            cursor=job.get("traversal").next_cursor if job.get("traversal") else None,
            remaining_events=job.get("remaining", []),
        )
        if job["run"].get("monitor_slot_at"):
            progress["monitor_slot_at"] = job["run"]["monitor_slot_at"]
        await owned_thread(
            self.store.update,
            job["run"],
            state=state,
            reason=reason,
            event_count=len(job["seen"]),
            progress=progress,
            at=self.worker.now(),
        )

    async def new_job(self, kind, status):
        run = await owned_thread(self.store.begin, kind, status, self.worker.now())
        if kind == "monitor":
            run.setdefault(
                "monitor_slot_at",
                activity_mode.monitor_schedule(
                    status["settings"], at=self.worker.now()
                )["current_slot_at"],
            )
            self.last_monitor_slot = stamp(run["monitor_slot_at"])
        return dict(
            run=run,
            seen=set(),
            league_index=0,
            traversal=None,
            leagues=aggregate_scope(self.worker.service.config),
            remaining=None,
            alternate_remaining=None,
            alternate_done=set(),
        )

    async def dispatch(self, job, params, status):
        worker = self.worker
        if status.get("retention", {}).get("staged_bytes", 0) >= 32 * 1024 * 1024:
            raise ActivityBudgetDelayed(
                "archive_backlog", worker.now() + timedelta(seconds=30)
            )
        budget_admit(worker.ledger, worker.window_id, params["limit"], worker.now())
        previous = getattr(worker, "collection_run", None)
        worker.collection_run = job["run"]
        worker.activity_status = status
        try:
            page = await worker._fetch(params)
        finally:
            worker.collection_run = previous
        start = stamp(job["run"]["scope_start_at"])
        end = stamp(job["run"]["scope_end_at"]) if job["run"]["scope_end_at"] else None
        if any(
            stamp(event["starts_at"]) < start
            or (end and stamp(event["starts_at"]) > end)
            for event in page.events
        ):
            raise ValueError("returned_event_outside_collection_window")
        job["seen"].update(event["event_id"] for event in page.events)
        return page

    async def monitor_turn(self, status):
        job = self.monitor
        worker = self.worker
        end = stamp(job["run"]["scope_end_at"]) if job["run"]["scope_end_at"] else None
        selected = activity_mode.eligible(
            list(worker.events.values()), status, at=worker.now(), kind="monitor"
        )
        near = worker.now() + timedelta(
            seconds=status["settings"]["live_window_seconds"]
        )
        priority = sorted(
            (
                event
                for event in selected
                if event["event_id"] not in job["alternate_done"]
                and event.get("league") in job["leagues"]
                and (end is None or stamp(event["starts_at"]) <= end)
                and (
                    job["league_index"] >= len(job["leagues"])
                    or stamp(event["starts_at"]) <= near
                )
            ),
            key=lambda event: (stamp(event["starts_at"]), event["event_id"]),
        )
        if priority:
            event_id = priority[0]["event_id"]
            try:
                await self.dispatch(
                    job,
                    worker.params(event_ids=[event_id], include_alternates=True),
                    status,
                )
            except PregameWindowClosed:
                pass
            job["alternate_done"].add(event_id)
            await self.save(job)
            return
        if job["league_index"] >= len(job["leagues"]):
            if job["alternate_remaining"] is None:
                job["alternate_remaining"] = sorted(
                    job["seen"] - job["alternate_done"],
                    key=lambda eid: (
                        stamp(worker.events[eid]["starts_at"])
                        if eid in worker.events
                        else worker.now(),
                        eid,
                    ),
                )
            while job["alternate_remaining"]:
                event_id = job["alternate_remaining"][0]
                event = worker.events.get(event_id)
                end = (
                    stamp(job["run"]["scope_end_at"])
                    if job["run"]["scope_end_at"]
                    else None
                )
                if (
                    event is None
                    or not activity_mode.eligible(
                        [event], status, at=worker.now(), kind="monitor"
                    )
                    or (end and stamp(event["starts_at"]) > end)
                ):
                    job["alternate_remaining"].pop(0)
                    continue
                try:
                    await self.dispatch(
                        job,
                        worker.params(event_ids=[event_id], include_alternates=True),
                        status,
                    )
                except PregameWindowClosed:
                    pass
                job["alternate_remaining"].pop(0)
                if not job["alternate_remaining"]:
                    await self.save(job, state="complete")
                    self.monitor = None
                else:
                    await self.save(job)
                return
            await self.save(job, state="complete")
            self.monitor = None
            return
        league = job["leagues"][job["league_index"]]
        if job["traversal"] is None:
            job["traversal"] = Traversal(max_pages=worker.max_discovery_pages)
        walk = job["traversal"]
        params = worker.params(
            league=league,
            starts_after=job["run"]["scope_start_at"],
            cursor=walk.next_cursor,
        )
        params.update(started=False, live=False)
        if job["run"]["scope_end_at"]:
            params["startsBefore"] = job["run"]["scope_end_at"]
        page = await self.dispatch(job, params, status)
        walk.add(walk.next_cursor, page)
        # Traversal keeps identities and bounded metadata, not large page bodies.
        walk.pages[-1] = None
        if walk.complete:
            job["league_index"] += 1
            job["traversal"] = None
        await self.save(job)

    async def live_turn(self, status):
        worker = self.worker
        job = self.live
        if job["remaining"] is None:
            selected = activity_mode.eligible(
                list(worker.events.values()), status, at=worker.now()
            )
            job["remaining"] = [
                event["event_id"]
                for event in sorted(
                    selected,
                    key=lambda event: (stamp(event["starts_at"]), event["event_id"]),
                )
            ]
        while job["remaining"]:
            event_id = job["remaining"][0]
            selected = activity_mode.eligible(
                [worker.events[event_id]] if event_id in worker.events else [],
                status,
                at=worker.now(),
            )
            if not selected:
                job["remaining"].pop(0)
                continue
            try:
                await self.dispatch(
                    job,
                    worker.params(event_ids=[event_id], include_alternates=True),
                    status,
                )
            except PregameWindowClosed:
                await self.save(job, state="partial", reason="live_scope_revoked")
                self.live = None
                return
            job["remaining"].pop(0)
            if not job["remaining"]:
                await self.save(job, state="complete")
                self.live = None
            else:
                await self.save(job)
            return
        await self.save(job, state="complete")
        self.live = None

    async def tick(self):
        status = await self.status()
        at = self.worker.now()
        if not self.initialized:
            # A former process's partial captures remain inspectable. Starting a
            # new run does not pretend its missing pages were ever observed.
            for prior in status.get("runs", {}).values():
                if prior["state"] in ("running", "budget_delayed"):
                    await owned_thread(
                        self.store.update,
                        prior,
                        state="partial",
                        reason="runtime_restarted",
                        event_count=prior["event_count"],
                        at=at,
                    )
            self.initialized = True
            latest = status.get("runs", {}).get("monitor", {}).get("monitor_slot_at")
            initial = activity_mode.monitor_schedule(
                status["settings"], at=at, last_slot=latest
            )
            self.last_monitor_slot = stamp(latest) if latest else None
            if not initial["due"]:
                slot = stamp(initial["current_slot_at"])
                self.last_monitor_slot = (
                    max(self.last_monitor_slot, slot)
                    if self.last_monitor_slot
                    else slot
                )
            self.monitor_due = stamp(initial["next_monitor_at"])
            self.live_due = at
        restart_monitor = False
        if self.previous_settings is not None:
            for kind, keys in (
                ("monitor", ("monitor_horizon_seconds",)),
                ("live", ("live_interval_seconds", "live_window_seconds")),
            ):
                if any(
                    self.previous_settings[k] != status["settings"][k] for k in keys
                ):
                    job = getattr(self, kind)
                    if job:
                        await self.save(job, state="partial", reason="settings_changed")
                        setattr(self, kind, None)
                    setattr(self, kind + "_due", at)
                    if kind == "monitor":
                        restart_monitor = True
        if status["mode"] == "live" and self.previous_mode != "live":
            self.live_due = at
        self.settings_revision = status["revision"]
        self.previous_settings = dict(status["settings"])
        self.previous_mode = status["mode"]
        self.worker.metrics["activity_mode"] = status
        if status["mode"] != "live" and self.live:
            await self.save(
                self.live, state="partial", reason="monitor_selected_or_inactivity"
            )
            self.live = None
        if self.retry_at and at < self.retry_at:
            return
        if self.worker.controls()["stopped"] or self.worker.controls()["source_paused"]:
            return
        settings = status["settings"]
        schedule = activity_mode.monitor_schedule(
            settings, at=at, last_slot=self.last_monitor_slot, catch_up=True
        )
        self.monitor_due = stamp(schedule["next_monitor_at"])
        if self.monitor is None and (schedule["due"] or restart_monitor):
            self.monitor = await self.new_job("monitor", status)
            self.monitor_due = stamp(
                activity_mode.monitor_schedule(
                    settings, at=at, last_slot=self.last_monitor_slot
                )["next_monitor_at"]
            )
        if status["mode"] == "live" and self.live is None and at >= self.live_due:
            self.live = await self.new_job("live", status)
            self.live_due = at + timedelta(seconds=settings["live_interval_seconds"])
        # On constrained capacity, the waiting kind owns the next released slot.
        # A fast Live loop cannot repeatedly consume Monitor's budget headroom.
        order = (self.next_kind, "monitor" if self.next_kind == "live" else "live")
        for kind in order:
            job = getattr(self, kind)
            if job is None:
                continue
            try:
                if kind == "live":
                    await self.live_turn(status)
                else:
                    await self.monitor_turn(status)
            except (ActivityBudgetDelayed, DailyObjectPacing) as exc:
                self.next_kind = kind
                self.retry_at = max(at + timedelta(seconds=1), exc.retry_at)
                await self.save(job, state="budget_delayed", reason=str(exc))
                self.worker.metrics["activity_budget"] = dict(
                    activity_mode.operating_budget(),
                    retry_at=self.retry_at.isoformat(),
                    reason=str(exc),
                    account_guards="also_required",
                )
                return
            except RuntimeError as exc:
                waits = (
                    "rate",
                    "object allowance",
                    "account usage",
                    "account reset",
                    "reservation",
                )
                if any(word in str(exc) for word in waits):
                    self.next_kind = kind
                    self.retry_at = at + timedelta(seconds=60)
                    await self.save(
                        job, state="budget_delayed", reason="account_or_rate_guard"
                    )
                    return
                await self.save(job, state="partial", reason=type(exc).__name__)
                setattr(self, kind, None)
                self.retry_at = at + timedelta(seconds=60)
                return
            except (ValueError, RejectedCursor) as exc:
                await self.save(job, state="partial", reason=type(exc).__name__)
                setattr(self, kind, None)
                self.retry_at = at + timedelta(seconds=60)
                return
            self.next_kind = "monitor" if kind == "live" else "live"
        self.retry_at = None

    async def run(self):
        try:
            while (
                not self.worker.controls()["stopped"]
                and not self.worker.controls()["source_paused"]
            ):
                if (
                    self.worker.ledger is not None
                    and self.worker.now()
                    >= self.worker.ledger.status(self.worker.window_id)["reset_at"]
                ):
                    await self.worker.initialize()
                await self.tick()
                await asyncio.sleep(1)
        finally:
            for kind in ("live", "monitor"):
                job = getattr(self, kind)
                if job:
                    await self.save(
                        job, state="partial", reason="source_stopped_or_paused"
                    )
