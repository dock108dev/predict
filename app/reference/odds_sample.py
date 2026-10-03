"""Explicit bounded multi-book sample; offline rows are not executable contracts.

Uses the existing reference sport keys and decimal probability conversion. No
startup hook, credential discovery, recurring collection or native-feed mutation.
"""
import asyncio
from decimal import Decimal
import getpass
from hashlib import sha256
import json
import logging
from pathlib import Path
import os
import httpx
from app.reference.product import SPORT_KEYS, probability, time
from app.reference.pinnacle_sample import now, save

BOOKS = ('prophetx', 'novig', 'pinnacle', 'draftkings', 'betmgm')
MARKETS = ('h2h', 'spreads', 'totals')
PARAMS = dict(bookmakers=','.join(BOOKS), markets=','.join(MARKETS),
              oddsFormat='decimal', dateFormat='iso', includeLinks='true',
              includeSids='true', includeBetLimits='true')
LIMIT = 2 * 1024 * 1024
OUTPUT = Path(__file__).resolve().parents[2] / 'evidence/odds-api-five-books-20260929/live'


def normalize(body, sport, received_at, *, _event_object=False):
    """Preserve source identity/lines; implied probabilities are NOT fair value/EV."""
    time(received_at)
    events = json.loads(body, parse_float=str)
    if _event_object:
        events = [events]
    if not isinstance(events, list):
        raise ValueError('Expected events array')
    rows = []
    for event in events:
        if event['sport_key'] != SPORT_KEYS[sport]:
            raise ValueError('Unexpected sport')
        time(event['commence_time'])
        if not all(isinstance(event.get(k), str) and event[k] for k in ('id', 'home_team', 'away_team')):
            raise ValueError('Missing event identity')
        for book in event['bookmakers']:
            if book['key'] not in BOOKS:
                raise ValueError('Unexpected bookmaker')
            for market in book['markets']:
                from app.reference.odds_bindings import period_binding
                binding = period_binding(sport, market['key']) if _event_object else None
                if market['key'] not in MARKETS and binding is None:
                    raise ValueError('Unexpected market')
                base_market = binding['base'] if binding else market['key']
                source_at = market.get('last_update') or book.get('last_update')
                if source_at:
                    time(source_at)
                for outcome in market['outcomes']:
                    if not isinstance(outcome.get('name'), str) or not outcome['name']:
                        raise ValueError('Missing outcome name')
                    point = outcome.get('point')
                    if base_market not in ('h2h', 'h2h_3_way') and (point is None or not Decimal(str(point)).is_finite()):
                        raise ValueError('Missing or invalid line')
                    try:
                        implied = probability(outcome['price'], 'decimal_odds')
                        price_issue = None
                    except (ValueError, ArithmeticError):
                        implied = None
                        price_issue = 'Invalid decimal odds; retained as source data only'
                    rows.append(dict(
                        provider='the_odds_api', evidence_mode='observation', sport=sport,
                        source_event_id=event['id'], scheduled_start=event['commence_time'],
                        home_team=event['home_team'], away_team=event['away_team'],
                        bookmaker=book['key'],
                        role='aggregated_venue_observation' if book['key'] in ('prophetx', 'novig') else 'bookmaker_reference',
                        market=market['key'], outcome=outcome['name'],
                        point=None if point is None else str(point),
                        decimal_odds=str(outcome['price']),
                        raw_implied_probability=implied, price_issue=price_issue,
                        source_at=source_at, received_at=received_at,
                        source_fields=dict(event=({k:v for k,v in event.items() if k != 'bookmakers'} if _event_object else {k:event[k] for k in ('id','sport_key')}),
                                           book={k:v for k,v in book.items() if k != 'markets'},
                                           market={k:v for k,v in market.items() if k != 'outcomes'},
                                           outcome=outcome),
                        receipt_sha256=sha256(body).hexdigest(),
                        executable=False, settlement=None, fees=None, purchasable_depth=None,
                        source_delay_seconds=None, fair_probability=None, ev=None))
                    if binding:
                        rows[-1]['period'] = binding['period']
    return rows


async def bounded_request(client, folder, key, endpoint, params, *,
                          body_limit=LIMIT, timeout_seconds=25, clock=now, before_dispatch=None,
                          receipt_name='result.json', reserved_credits=3):
    """Single dispatch, no redirect/retry; retain bounded bytes even on cancellation.

    A durable reservation precedes transport. An absent result means uncertain
    consumption, never permission to retry. Exceptions are retained by type only.
    """
    from urllib.parse import unquote
    folder.mkdir()
    save(folder, 'attempt.json', dict(started_at=clock(), endpoint=endpoint, params=params,
         attempt_consumed=True, dispatch_state='reserved_dispatch_uncertain', retries=0,
         body_limit=body_limit, timeout_seconds=timeout_seconds,
         reserved_credits=reserved_credits))
    # Persist directory entries as well as the reservation file before dispatch.
    for directory in (folder.parent, folder):
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    result = dict(status=None, headers={}, outcome='interrupted', body_complete=False)
    body = bytearray()
    try:
        async with asyncio.timeout(timeout_seconds):
            if before_dispatch is not None:
                before_dispatch()
            from app.collection.shared_odds_guard import before_request, reconcile
            shared=before_request(endpoint,params,reserved_credits,client)
            async with client.stream('GET', endpoint, params=dict(params, apiKey=key),
                                     headers={'Accept-Encoding':'identity'}) as response:
                reconcile(shared,list(response.headers.multi_items()))
                result.update(status=response.status_code, headers={k:v for k,v in response.headers.items()
                              if k in ('x-requests-last','x-requests-used','x-requests-remaining','date')})
                async for chunk in response.aiter_bytes():
                    remaining = body_limit - len(body)
                    body.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        result['outcome'] = 'oversize'
                        break
                else:
                    result['body_complete'] = True
                    result['outcome'] = 'received' if response.status_code == 200 else 'http_failure'
    except Exception as exc:
        result.update(outcome='transport_failure', error_type=type(exc).__name__)
    finally:
        result.update(received_at=clock(), body_bytes=len(body), body_sha256=sha256(body).hexdigest())
        # Withhold echoes, including JSON/URL escaped forms and keyed URLs. Never
        # retain arbitrary headers, redirect locations, exceptions or request URLs.
        text = body.decode('utf-8', errors='replace')
        try:
            decoded = json.dumps(json.loads(text), ensure_ascii=False)
        except (ValueError, RecursionError):
            decoded = text
        candidates = [text, decoded, *result['headers'].values()]
        unsafe = False
        for value in candidates:
            for _ in range(3):
                if key in value or 'apikey' in value.lower() or 'api_key' in value.lower():
                    unsafe = True
                value = unquote(value)
        if unsafe:
            result.update(outcome='credential_echo_not_retained', headers={}, body_retained=False)
        else:
            with (folder/'response.json').open('xb') as f:
                f.write(body); f.flush(); os.fsync(f.fileno())
            result['body_retained'] = True
        save(folder, receipt_name, result)
    return result


async def request(client, folder, key, sport):
    url = f'https://api.the-odds-api.com/v4/sports/{SPORT_KEYS[sport]}/odds'
    result = await bounded_request(client, folder, key, url, PARAMS, receipt_name='transport.json')
    rows = []
    if result['outcome'] == 'received':
        try:
            rows = normalize((folder/'response.json').read_bytes(), sport, result['received_at'])
            save(folder, 'observations.json', rows)
        except Exception as exc:
            result.update(outcome='parse_failure', error_type=type(exc).__name__)
    result['observations'] = len(rows)
    result['book_counts'] = {b:sum(x['bookmaker']==b for x in rows) for b in BOOKS}
    result['events'] = len({x['source_event_id'] for x in rows})
    save(folder, 'result.json', result)
    return result


from app.collection.shared_odds_guard import shared_capture

@shared_capture
async def capture(folder, key, *, transport=None, sports=None):
    if not key or len(key) < 16:
        raise ValueError('Missing credential')
    sports = tuple(SPORT_KEYS) if sports is None else tuple(sports)
    if not sports or len(set(sports)) != len(sports) or any(s not in SPORT_KEYS for s in sports):
        raise ValueError('Invalid sport scope')
    folder.mkdir()  # exclusive: consumed even if interrupted; never reuse allowance
    save(folder, 'authorization.json', dict(started_at=now(), sports={s:SPORT_KEYS[s] for s in sports},
         bookmakers=BOOKS, markets=MARKETS, maximum_requests=len(sports), maximum_credits=3*len(sports),
         authorization='Owner supplied key and requested initial live data across six sports and five books',
         plan='free per owner; no purchase', retries=0, recurring=False))
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    results = {}
    try:
        async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False, timeout=25) as client:
            for sport in sports:
                result = await request(client, folder/sport, key, sport)
                results[sport] = result
                # Stop on failures or uncertain/unexpected billing. No hidden retries.
                try:
                    cost = int(result['headers']['x-requests-last'])
                    remaining = int(result['headers']['x-requests-remaining'])
                    quota_ok = 0 <= cost <= 3 and remaining >= 3
                except (KeyError, ValueError):
                    quota_ok = False
                if result['outcome'] != 'received' or not quota_ok:
                    break
    finally:
        logging.disable(previous_logging)
    save(folder, 'summary.json', dict(finished_at=now(), results=results,
         unattempted=[s for s in sports if s not in results],
         reported_credits=sum(int(r['headers'].get('x-requests-last',0)) for r in results.values()
                              if str(r['headers'].get('x-requests-last','')).isdigit())))
    return results


def main():
    os.umask(0o077)
    key = getpass.getpass('Odds API key (hidden, used only for this sample): ')
    try:
        results = asyncio.run(capture(OUTPUT, key))
    except Exception:
        raise SystemExit('Sample stopped. Inspect retained evidence; do not retry.') from None
    print(json.dumps({s:dict(outcome=r['outcome'], events=r['events'], books=r['book_counts'], quota=r['headers'])
                      for s,r in results.items()}, indent=2))


if __name__ == '__main__':
    main()
