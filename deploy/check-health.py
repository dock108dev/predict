"""Check bounded SQL read availability and the collector's liveness and failed work."""

import json
import sys
from urllib.request import urlopen


def web_health():
    with urlopen('http://127.0.0.1:8784/api/health', timeout=4) as response:
        return response.status == 200 and json.load(response).get('read_available') is True


def collector_health():
    from app.storage.store import connect

    with connect() as db, db.transaction():
        db.execute('SET TRANSACTION READ ONLY')
        runtime = db.execute("""SELECT state,dispatch,global_stopped,config->'enabled' AS enabled,
            heartbeat_at BETWEEN clock_timestamp()-interval '8 seconds' AND clock_timestamp() AS healthy
            FROM data_runtime WHERE singleton=true""").fetchone()
        if not runtime or not runtime['healthy'] or runtime['state'] != 'running':
            return False
        if runtime['global_stopped'] or not runtime['enabled']:
            return True
        failure = db.execute("SELECT 1 FROM current_pregame_work WHERE error IS NOT NULL LIMIT 1").fetchone()
        return bool(runtime['dispatch']) and not failure


if __name__ == '__main__':
    try:
        healthy = {'web': web_health, 'collector': collector_health}[sys.argv[1]]()
    except Exception:
        healthy = False
    sys.exit(0 if healthy else 1)
