"""Check the dashboard or the current collector heartbeat without source calls."""

import sys
from urllib.request import urlopen


def web_health():
    from app.storage.store import connect

    with connect() as db:
        db.execute('SELECT version FROM schema_migration LIMIT 1')
    with urlopen('http://127.0.0.1:8784/', timeout=4) as response:
        return response.status == 200 and bool(response.read(256))


def collector_health():
    from app.collection.runtime_status import RuntimeState
    return RuntimeState().read()['healthy']


if __name__ == '__main__':
    try:
        healthy = {'web': web_health, 'collector': collector_health}[sys.argv[1]]()
    except Exception:
        healthy = False
    sys.exit(0 if healthy else 1)
