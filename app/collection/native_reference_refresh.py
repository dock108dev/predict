"""Paced reference refreshes for exact upcoming Dashboard games."""

from datetime import timedelta

from app.storage.native_trading import PRIORITY_WINDOW, REFERENCE_AGE
from app.storage.store import connect, stamp
from .activity_collector import ActivityBudgetDelayed, admit_dispatch
from .bulk_checkpoint import owned_thread
from .current_policy import PregameWindowClosed
from .experiment_acquisition import late_protection_until
from .sportsgameodds_collector import DailyObjectPacing

REQUEST_SPACING = timedelta(seconds=15)
# Leave one third of the source-age window for provider quote lag, queueing,
# and checkpoints on the shared request lane.
REFRESH_MARGIN = REFERENCE_AGE / 3
REFRESH_PERIOD = REFERENCE_AGE - REFRESH_MARGIN


def targets(db, *, at, until):
    return db.execute(
        """SELECT game_link->>'sgo_event_id' event_id,min(starts_at) starts_at,
        max(book_valid_until) book_until,max(reference_valid_until) reference_until
        FROM public.native_trading_offer
        WHERE active AND starts_at>%s AND starts_at<=%s AND game_link->>'status'='matched'
        GROUP BY 1""",
        (at, until),
    ).fetchall()


class NativeReferenceRefresh:
    def __init__(self, worker, *, connector=connect):
        self.worker = worker
        self.connector = connector
        self.attempted = {}
        self.next_scan = None

    def plan(self, at, horizon):
        worker = self.worker
        until = (
            at + min(PRIORITY_WINDOW, timedelta(seconds=horizon))
            if horizon
            else at + PRIORITY_WINDOW
        )
        with self.connector() as db:
            candidates = targets(db, at=at, until=until)
        self.attempted = {
            eid: when
            for eid, when in self.attempted.items()
            if at - when < REFRESH_PERIOD
        }
        ranked = []
        for target in candidates:
            eid = target["event_id"]
            event = worker.events.get(eid)
            if (
                eid in self.attempted
                or event is None
                or not worker.event_in_scope(event, at)
                or not at < stamp(event["starts_at"]) <= until
            ):
                continue
            receipt = stamp(event.get("last_polled_at", event["received_at"]))
            due = receipt + REFRESH_PERIOD
            if target["reference_until"]:
                due = max(
                    receipt + REFRESH_MARGIN,
                    min(due, target["reference_until"] - REFRESH_MARGIN),
                )
            if due <= at:
                ranked.append(
                    (
                        not (target["book_until"] and target["book_until"] > at),
                        due,
                        target["starts_at"],
                        eid,
                    )
                )
        return min(ranked)[-1] if ranked else None

    async def __call__(self, status):
        """Use one ordinary request turn while preserving the next monitor page."""
        worker = self.worker
        at = worker.now()
        controls = worker.controls()
        if (
            controls["stopped"]
            or controls["source_paused"]
            or (self.next_scan and at < self.next_scan)
        ):
            return False
        self.next_scan = at + REQUEST_SPACING
        if worker.experiment_late_waiting or late_protection_until(worker, at=at):
            return False
        from app.diagnostics import failure
        from psycopg import Error as DatabaseError

        try:
            eid = await owned_thread(
                self.plan, at, status["settings"]["monitor_horizon_seconds"]
            )
            if eid is None:
                return False
            admit_dispatch(
                worker, status, 1, extra_objects=worker.page_limit, extra_requests=1
            )
        except ActivityBudgetDelayed as exc:
            self.next_scan = max(self.next_scan, exc.retry_at)
            worker.metrics["dashboard_reference_refresh"] = dict(
                state="deferred", reason=str(exc)
            )
            return False
        except DatabaseError as exc:
            failure(__name__, "native_reference_candidates", exc)
            return False

        self.attempted[eid] = at
        # The established exact-event scope preserves the event frame's venue
        # links and supports the same alternate-line omission policy as before.
        params = worker.params(event_ids=[eid], include_alternates=True)
        try:
            page = await worker._fetch(params)
        except (ActivityBudgetDelayed, DailyObjectPacing) as exc:
            self.attempted.pop(eid, None)
            self.next_scan = max(self.next_scan, exc.retry_at)
            worker.metrics["dashboard_reference_refresh"] = dict(
                state="deferred", reason=str(exc)
            )
            return False
        except PregameWindowClosed:
            return False
        except (RuntimeError, ValueError, DatabaseError) as exc:
            failure(__name__, "native_reference_refresh", exc)
            worker.metrics["dashboard_reference_refresh"] = dict(
                state="unavailable", reason=type(exc).__name__
            )
        else:
            worker.metrics["dashboard_reference_refresh"] = dict(
                state="ready",
                received_at=page.received_at,
                returned_events=len(page.events),
                reference_rows=len(page.quotes),
            )
        return True
