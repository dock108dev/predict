"""Recovery and schedule changes for the ingestion-owned current calculations."""

import asyncio

from app.diagnostics import failure
from app.storage.store import connect


class PregameOwner:
    def __init__(self, service):
        self.service = service
        self.closed = False
        self.task = None
        self.error = None
        self.progress = {}
        self.wake = asyncio.Event()
        self.last_status = 0
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
            routes = configured_routes(db)
            db.execute(
                """INSERT INTO current_pregame_work(provider,native_event_id)
                SELECT DISTINCT e.provider,e.native_event_id FROM current_event e
                JOIN current_contract c ON c.event_id=e.id JOIN current_offer o ON o.contract_id=c.id
                LEFT JOIN current_pregame_calculation p ON p.contract_id=c.id
                WHERE e.expires_order>extract(epoch FROM clock_timestamp())
                  AND (c.venue||':'||e.provider)=ANY(%s)
                  AND (p.contract_id IS NULL OR p.version<>%s)
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
                db.execute("""INSERT INTO current_pregame_work(provider,native_event_id)
                    SELECT DISTINCT e.provider,e.native_event_id FROM current_pregame_calculation p
                    JOIN current_contract c ON c.id=p.contract_id JOIN current_event e ON e.id=c.event_id
                    WHERE p.valid_until<=clock_timestamp() AND p.start_at>clock_timestamp()
                      AND (p.reason IS NULL OR p.reason='fee_rule_no_current_schedule')
                    ON CONFLICT DO NOTHING""")
            from .background_work import BACKGROUND

            result = process(
                db,
                limit=8,
                can_continue=lambda: not BACKGROUND.critical_acquisition_pressure(),
            )
            from time import monotonic

            if result or monotonic() - self.last_status >= 5:
                state = operational(db)
                state = {
                    k: v.isoformat() if hasattr(v, "isoformat") else v
                    for k, v in state.items()
                }
                self.progress = dict(
                    current_rows=dict(**state, recent=result),
                    research=self.research.progress,
                )
                self.last_status = monotonic()

    async def run(self):
        while not self.closed:
            try:
                await asyncio.to_thread(self.turn)
                self.error = None
            except Exception as exc:
                failure(__name__, "current_pregame_recovery", exc)
                self.error = type(exc).__name__
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=0.25)
            except TimeoutError:
                pass
            self.wake.clear()

    async def close(self):
        self.closed = True
        self.wake.set()
        await self.research.close()
        if self.task:
            await self.task
