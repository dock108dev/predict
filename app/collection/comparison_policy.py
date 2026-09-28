"""Fresh ordinary-app observation policy; historical 90-second policy remains sealed."""
from copy import deepcopy
VERSION='live-comparison-nfl-1'


def specification(start_after,start_before,attempt_id,mode='real'):
    from .two_source_policy import specification as previous
    s=previous(start_after,start_before,attempt_id,mode)
    s.update(duration=180,cleanup='Stop intake at 179 seconds; external supervisor terminates unclosed collection at 180 seconds; preserve incomplete prefix',
        capture_authorization='Pending separate live approval: one three-minute read-only ordinary Predict comparison; no trading or additional spend')
    s['two_source_qualification'].update(version=VERSION,target_stop_seconds=180,cleanup_start_seconds=179,hard_deadline_seconds=180)
    s['native_sources']['novig'].update(selected=False,state='unselected')
    s['native_sources']['prophetx'].update(selected=False,state='unselected')
    return s


def multi_specification(start_after,start_before,attempt_id,mode='real'):
    s=specification(start_after,start_before,attempt_id,mode)
    s['two_source_qualification'].update(version='live-comparison-nfl-multi-1',events_selected=4,
        markets_per_venue=8,rest_attempts={'kalshi':20,'polymarket_us':18})
    for v in ('kalshi','polymarket_us'):
        s['native_sources'][v].update(event_cap=4,market_cap=8)
    return s
