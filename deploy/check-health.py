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
    from app.collection.runtime_status import RuntimeState
    from app.storage.store import stamp

    runtime = RuntimeState().read()
    if not runtime['healthy'] or runtime['service_state'] != 'running':
        return False
    if runtime['global_stopped'] or not runtime['config']['enabled']:
        return True
    progress = runtime['status'].get('background_work', {}).get('progress', {}).get('ordinary', {})
    last_success = progress.get('last_success_at')
    return (runtime['active'] and not progress.get('error') and bool(last_success)
            and abs((stamp(runtime['heartbeat_at']) - stamp(last_success)).total_seconds()) <= 180)


if __name__ == '__main__':
    try:
        healthy = {'web': web_health, 'collector': collector_health}[sys.argv[1]]()
    except Exception:
        healthy = False
    sys.exit(0 if healthy else 1)
