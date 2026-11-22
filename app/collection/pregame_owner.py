"""Recovery and schedule changes for the ingestion-owned current calculations."""

import asyncio

from app.diagnostics import failure
from app.storage.store import connect


class PregameOwner:
    def __init__(self, service):
        self.service = service
        self.closed = False
        self.task = None
        self.journal_task = None
        self.error = None
        self.progress = {}
        self.wake = asyncio.Event()
        self.last_status = 0
        self.last_research_capture = 0
        self.cohort_progress = {}
        self.fee_account_identity = object()
        from app.storage.ordinary_owner import OrdinaryOwner

        self.research = OrdinaryOwner(service)

    @property
    def last_coverage(self):
        return self.research.last_coverage

    @property
    def coverage_error(self):
        return self.research.coverage_error

    async def start(self):
        await asyncio.to_thread(self.seed)
        await self.research.start()
        self.task = asyncio.create_task(
            self.run(), name="predict-current-pregame-recovery"
        )

    def seed(self):
        from app.comparison.current_pregame import VERSION
        from app.storage.current_pregame import configured_routes

        with connect() as db, db.transaction():
            db.execute("SELECT pg_advisory_xact_lock(901095)")
            from app.storage.sgo_line_presence import retire_superseded_mains

            retire_superseded_mains(db, [r['event_id'] for r in db.execute(
                "SELECT event_id FROM sgo_event_evidence WHERE kind='frame' AND expires_at>clock_timestamp()")])
            routes = configured_routes(db)
            db.execute(
                """INSERT INTO current_pregame_work(provider,native_event_id)
                SELECT DISTINCT e.provider,e.native_event_id FROM current_event e
                JOIN current_contract c ON c.event_id=e.id JOIN current_offer o ON o.contract_id=c.id
                LEFT JOIN current_pregame_calculation p ON p.contract_id=c.id
                WHERE e.expires_order>extract(epoch FROM clock_timestamp())
                  AND (c.venue||':'||e.provider)=ANY(%s)
                  AND (p.contract_id IS NULL OR p.version<>%s
                    OR c.venue='polymarket_us' AND e.provider='sportsgameodds'
                      AND p.reason IS DISTINCT FROM 'provider_venue_fee_applicability_unestablished')
                ON CONFLICT DO NOTHING""",
                (
                    [venue + ":" + provider for venue, provider in routes.items()],
                    VERSION,
                ),
            )

    def turn(self):
        from app.storage.current_pregame import process, operational

        with connect() as db:
            from app.storage.current_pregame import account_identity, configured_routes

            with db.transaction():
                db.execute("SELECT pg_advisory_xact_lock(901095)")
                identity = account_identity()
                if identity != self.fee_account_identity:
                    db.execute(
                        """INSERT INTO current_pregame_work(provider,native_event_id)
                        SELECT DISTINCT e.provider,e.native_event_id FROM current_event e
                        JOIN current_contract c ON c.event_id=e.id
                        WHERE c.venue='kalshi' AND e.provider=%s
                          AND e.expires_order>extract(epoch FROM clock_timestamp())
                        ON CONFLICT DO NOTHING""",
                        (configured_routes(db)["kalshi"],),
                    )
                    self.fee_account_identity = identity
                # Effective fee deadlines enqueue only the affected source events.
                from app.storage.current_pregame import enqueue_due

                enqueue_due(db)
            from .background_work import BACKGROUND

            result = process(
                db,
                limit=8,
                can_continue=lambda: not BACKGROUND.critical_acquisition_pressure(),
            )
            from time import monotonic

            # Cohorts/cutoffs are independent of the optional positive-arb
            # journal sampler. Scheduling reads issue no provider requests.
            if monotonic() - self.last_research_capture >= 30 and not BACKGROUND.critical_acquisition_pressure():
                self.last_research_capture = monotonic()
                try:
                    from app.research.records import automatic_turn

                    self.cohort_progress = automatic_turn(db)
                except Exception as exc:
                    failure(__name__, "prospective_research_capture", exc)
                    self.cohort_progress = dict(state="unavailable", reason=str(exc)[:160])

            if result or monotonic() - self.last_status >= 5:
                state = operational(db)
                state = {
                    k: v.isoformat() if hasattr(v, "isoformat") else v
                    for k, v in state.items()
                }
                self.progress = dict(
                    current_rows=dict(**state, recent=result),
                    research=self.research.progress,
                    cohorts=self.cohort_progress,
                )
                self.last_status = monotonic()

    async def run(self):
        while not self.closed:
            try:
                await asyncio.to_thread(self.turn)
                self.error = None
                self.sample_journal()
            except Exception as exc:
                failure(__name__, "current_pregame_recovery", exc)
                self.error = type(exc).__name__
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=0.25)
            except TimeoutError:
                pass
            self.wake.clear()

    def sample_journal(self):
        # Journal scans read committed prices and may take seconds. Keep one
        # owned scan off the recovery path so it cannot stall affected games.
        from .background_work import BACKGROUND
        from app.dashboard.bet_journal_monitor import poll

        if self.journal_task is not None:
            if not self.journal_task.done():
                return
            try:
                self.journal_task.result()
            except Exception as exc:
                failure(__name__, 'personal_journal_task', exc)
            self.journal_task = None
        if not self.closed and not BACKGROUND.critical_acquisition_pressure():
            self.journal_task = asyncio.create_task(
                asyncio.to_thread(poll), name='predict-journal-sample')

    async def close(self):
        self.closed = True
        self.wake.set()
        await self.research.close()
        if self.task:
            await self.task
        if self.journal_task:
            await self.journal_task
