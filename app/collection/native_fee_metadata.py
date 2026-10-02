"""Bounded, exact-scope public fee observations; never account qualification."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from .odds_http import BudgetStop
from .native_payload import RESPONSE_CAP_REASONS


def context(series, changes, events, series_id, event_id, observed_at):
    """Bind API facts into the existing as-of fee resolver, from receipt time."""
    if series.get('ticker') != series_id:
        raise ValueError('fee_series_identity_mismatch')
    if events.get('cursor') != '':
        raise ValueError('fee_event_history_incomplete')
    series_rows = deepcopy(changes['series_fee_change_arr'])
    event_rows = deepcopy(events['event_fee_changes'])
    for row in series_rows:
        if row.get('series_ticker') != series_id:
            raise ValueError('fee_series_history_identity_mismatch')
    for row in event_rows:
        if row.get('series_ticker') != series_id or row.get('event_ticker') != event_id:
            raise ValueError('fee_event_history_identity_mismatch')
    # Current series facts start at their receipt; no retrospective baseline is
    # invented from an empty or future-only change history.
    baseline=dict(series_ticker=series_id, scheduled_ts=observed_at,
                  fee_type=series['fee_type'], fee_multiplier=str(series['fee_multiplier']))
    for row in series_rows:
        row['fee_multiplier']=str(row['fee_multiplier'])
        Decimal(row['fee_multiplier'])
    for row in event_rows:
        if row.get('fee_multiplier_override') is not None:
            row['fee_multiplier_override']=str(row['fee_multiplier_override'])
            Decimal(row['fee_multiplier_override'])
    # Future changes supersede the observed baseline. Earlier history remains
    # raw provenance, not an asserted baseline before this acquisition.
    from app.fees.engine import stamp
    future=[r for r in series_rows if stamp(r['scheduled_ts'])>stamp(observed_at)]
    value=dict(source='complete scoped Kalshi series/current and fee-change API receipts',
               series_id=series_id,event_id=event_id,series_changes=[baseline]+future,
               event_changes=event_rows,event_history_complete=True,
               observed_at=observed_at,historical_series_changes=series_rows)
    from app.fees.engine import kalshi_terms
    kalshi_terms(dict(series_id=series_id,event_id=event_id,kalshi_metadata=value),observed_at)
    return value


async def collect(discovery, series_id, event_id, ceiling):
    """One selected current event, once per session; all ordinary budgets apply."""
    from .continuous import endpoints_for
    import aiohttp
    client=discovery.clients['kalshi'];responses=[]
    routes=[('/trade-api/v2/series/'+series_id,{}),
            ('/trade-api/v2/series/fee_changes',dict(series_ticker=series_id,show_historical='true')),
            ('/trade-api/v2/events/fee_changes',dict(event_ticker=event_id,limit=100,cursor=''))]
    for path,params in routes:
        if client.requests>=ceiling or 'kalshi' in discovery.source_stops:
            discovery.session.emit('kalshi',dict(type='native_fee_metadata',event_id=event_id,
                series_id=series_id,status='not_reached_source_or_generation_allowance',qualification='UNKNOWN'))
            return
        try:
            response=await client.get(endpoints_for(discovery.session)['kalshi']['rest']+path,params)
            if response.status_code!=200:raise ValueError('fee_metadata_http_'+str(response.status_code))
            responses.append(response.json())
        except (ValueError,TimeoutError,aiohttp.ClientError,BudgetStop) as exc:
            if isinstance(exc,BudgetStop) and str(exc) not in RESPONSE_CAP_REASONS and 'kalshi' not in discovery.source_stops:raise
            discovery.session.emit('kalshi',dict(type='native_fee_metadata',event_id=event_id,
                series_id=series_id,status='query_failed',path=path,reason=str(exc),qualification='UNKNOWN'))
            return
    at=datetime.now(timezone.utc).isoformat()
    try:
        bound=context(responses[0]['series'],responses[1],responses[2],series_id,event_id,at)
        status='scoped_current_terms_bound';reason=None
    except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
        bound=None;status='unbound';reason=str(exc)
    discovery.session.emit('kalshi',dict(type='native_fee_metadata',event_id=event_id,
        series_id=series_id,status=status,reason=reason,observations=responses,context=bound,
        observed_at=at,qualification='CONDITIONAL; account precision, applicable rounding and mandatory charges remain independent',
        routes=[dict(path=p,params=q) for p,q in routes]))
