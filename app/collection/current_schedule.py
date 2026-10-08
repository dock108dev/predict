"""Quarter-hour Eastern slots. UTC identities remain stable across DST."""
from datetime import timedelta
from zoneinfo import ZoneInfo
from app.dashboard.current_contract import stamp
from .current_aggregate_policy import POLICY
EASTERN=ZoneInfo(POLICY.timezone)

def schedule(at):
    utc=stamp(at);local=utc.astimezone(EASTERN)
    opened=POLICY.opens_at_hour<=local.hour<POLICY.closes_at_hour
    slot=local.replace(minute=local.minute//(POLICY.interval_seconds//60)*(POLICY.interval_seconds//60),second=0,microsecond=0)
    if opened:
        due=slot+timedelta(seconds=POLICY.interval_seconds)
        if due.hour>=POLICY.closes_at_hour:due=(local+timedelta(days=1)).replace(hour=POLICY.opens_at_hour,minute=0,second=0,microsecond=0)
    else:
        due=(local+timedelta(days=local.hour>=POLICY.closes_at_hour)).replace(hour=POLICY.opens_at_hour,minute=0,second=0,microsecond=0)
    return dict(open=opened,slot=slot.astimezone(utc.tzinfo).isoformat(),next_due_at=due.astimezone(utc.tzinfo).isoformat())
