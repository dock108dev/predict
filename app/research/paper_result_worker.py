"""Process paper results from PostgreSQL independently of the collector."""

from datetime import timedelta
import logging
import os
import signal
from threading import Event

from psycopg import Error

from app.research import market_census, paper_campaigns
from app.storage import paper_result_queue as queue
from app.storage.store import connect

LOG = logging.getLogger(__name__)
REPAIR_INTERVAL = timedelta(minutes=10)
POLL_SECONDS = 2


def run(stop, *, connector=connect):
    repair_at = queue.utc()
    census_priority = ()
    while not stop.is_set():
        try:
            with connector() as db:
                db.execute("SET application_name = 'predict-paper-result-grader'")
                while not stop.is_set():
                    now = queue.utc()
                    if not queue._late_capture_due(db, now):
                        if now >= repair_at:
                            queue.repair(db)
                            census_priority = market_census.campaign_checkpoints(db, now)
                            repair_at = now + REPAIR_INTERVAL
                        queue.dispatch(db)
                        if queue.process_one(db):
                            # A paired replay queues two grades. Give both a turn
                            # before starting the next potentially large replay.
                            queue.process_one(db)
                        paper_campaigns.tick(db)
                        market_census.tick(db, priority=census_priority)
                    stop.wait(POLL_SECONDS)
        except Error as error:
            LOG.warning("Paper result database temporarily unavailable (%s)", type(error).__name__)
            stop.wait(POLL_SECONDS)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.nice(10)
    stop = Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    run(stop)


if __name__ == "__main__":
    main()
