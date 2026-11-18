"""Check the public read path or the collector's witnessed publication progress."""

import json
import sys
from urllib.request import urlopen


def web_health():
    url = 'http://127.0.0.1:8784/api/comparison-current?layout=desk&browse_odds=1&lines=main&summary=1&limit=1'
    with urlopen(url, timeout=4) as response:
        page = json.load(response)
        return (response.status == 200 and isinstance(page.get('rows'), list)
                and isinstance(page.get('generation'), int) and page.get('provider_requests') == 0)


def collector_health():
    from app.storage.store import connect, stamp

    with connect() as db, db.transaction():
        db.execute('SET TRANSACTION READ ONLY')
        runtime = db.execute('''SELECT state,dispatch,global_stopped,config->'enabled' AS enabled,
            status#>>'{background_calculations,board}' AS calculation,
            status#>'{background_work,progress,ordinary}' AS ordinary,
            status#>'{background_work,progress,unit_board}' AS unit_board,heartbeat_at,
            heartbeat_at BETWEEN clock_timestamp()-interval '8 seconds' AND clock_timestamp() AS healthy
            FROM data_runtime WHERE singleton=true''').fetchone()
        if not runtime or not runtime['healthy'] or runtime['state'] != 'running':
            return False
        if runtime['global_stopped'] or not runtime['enabled'] or runtime['calculation'] == 'stopped':
            return True
        board = db.execute('SELECT board_id,policy_id FROM pregame_unit_board WHERE unit_cents=10000').fetchone()
    progress = runtime['ordinary'] or {}
    unit_progress = runtime['unit_board'] or {}
    last_success = progress.get('last_success_at')
    if not board or not board['board_id'] or board['policy_id'] != unit_progress.get('policy_id'):
        return False
    return (runtime['dispatch'] and not progress.get('error') and bool(last_success)
            and abs((stamp(runtime['heartbeat_at']) - stamp(last_success)).total_seconds()) <= 180)


if __name__ == '__main__':
    try:
        healthy = {'web': web_health, 'collector': collector_health}[sys.argv[1]]()
    except Exception:
        healthy = False
    sys.exit(0 if healthy else 1)
