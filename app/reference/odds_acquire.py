"""One separately authorized NFL H1 acquisition; no startup or credential discovery.

Run --describe offline to obtain the candidate identity. Execution requires an
explicit candidate-bound authorization file and hidden manual credential input.
"""
import argparse
import asyncio
import getpass
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import re
import time as monotonic_time

import httpx
from app.reference.odds_sample import bounded_request, LIMIT
from app.reference.odds_bindings import acquisition_plan, select_event, normalize_event
from app.reference.aggregate_import import import_event_response
from app.reference.pinnacle_sample import now, save
from app.reference.product import time

ROOT = Path(__file__).resolve().parents[2]
PROPOSAL = ROOT/'evidence/source-bindings-20260929/proposal.json'
SPEC_SHA256 = '0b02505ff046fb40ed6d44dd57b6dcee1621a206901d0cf8ed0c4c46814ce769'
OUTPUT = ROOT/'evidence/source-bindings-20260929/acquisition'
BASE = 'https://api.the-odds-api.com'


def identity():
    spec = PROPOSAL.read_bytes()
    if sha256(spec).hexdigest() != SPEC_SHA256:
        raise ValueError('Proposal changed; requalify package')
    files = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
             for p in sorted((ROOT/'app').rglob('*'))
             if p.is_file() and p.suffix in ('.py','.json','.js','.html','.css','.sql')}
    for name in ('tests/test_odds_acquire.py', 'tests/test_odds_sample.py',
                 'tests/test_odds_bindings.py', 'tests/test_aggregate_ingestion.py'):
        files[name] = sha256((ROOT/name).read_bytes()).hexdigest()
    files['pyproject.toml'] = sha256((ROOT/'pyproject.toml').read_bytes()).hexdigest()
    return dict(spec_sha256=SPEC_SHA256,
                source_sha256=sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(), files=files)


def authorize(authorization, folder):
    candidate = identity()
    expected = dict(authorized=True, source_sha256=candidate['source_sha256'],
                    spec_sha256=SPEC_SHA256, attempt_path=str(folder.resolve()),
                    maximum_requests=2, maximum_credits=3)
    if authorization != expected:
        raise ValueError('Separate exact candidate authorization required')
    if folder.exists():
        raise FileExistsError('Attempt consumed or uncertain; never retry')
    return candidate


def strict_json(body):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('Nonfinite JSON')
    return json.loads(body, object_pairs_hook=pairs, parse_constant=invalid)


def quota(result, maximum_cost):
    headers = result['headers']
    values = []
    for key in ('x-requests-last', 'x-requests-remaining', 'x-requests-used'):
        value = headers.get(key, '')
        if not re.fullmatch(r'[0-9]{1,12}', value):
            raise ValueError('Missing or malformed quota')
        values.append(int(value))
    cost, remaining, used = values
    if cost > maximum_cost:
        raise ValueError('Unexpected provider charge')
    return dict(cost=cost, remaining=remaining, used=used)


def validate_odds(event, selected):
    if not isinstance(event, dict) or any(event.get(k) != selected[k] for k in
            ('id', 'sport_key', 'commence_time', 'home_team', 'away_team')):
        raise ValueError('Odds event differs from selected discovery identity')
    if not isinstance(event.get('bookmakers'), list):
        raise ValueError('Missing bookmakers list')
    books = set()
    for book in event['bookmakers']:
        if book['key'] not in ('novig','prophetx','pinnacle','draftkings','betmgm') or book['key'] in books:
            raise ValueError('Unexpected or duplicate book')
        books.add(book['key'])
        if not isinstance(book.get('markets'), list):
            raise ValueError('Missing markets list')
        markets = set()
        for market in book['markets']:
            if market['key'] not in ('h2h_h1','spreads_h1','totals_h1') or market['key'] in markets:
                raise ValueError('Unexpected or duplicate market')
            markets.add(market['key'])
            if not isinstance(market.get('outcomes'), list):
                raise ValueError('Missing outcomes list')


async def capture(folder, key, authorization, *, transport=None, clock=now,
                  monotonic=monotonic_time.monotonic):
    folder = Path(folder)
    candidate = authorize(authorization, folder)
    if not isinstance(key, str) or len(key) < 16 or not key.isascii() or not key.isalnum():
        raise ValueError('Invalid credential format')
    folder.mkdir(parents=True, exist_ok=False)
    # Reservation is final even if process dies before dispatch or writing result.
    save(folder, 'attempt.json', dict(authorization=authorization, candidate=candidate,
         started_at=clock(), consumed=True, state='reserved_no_resume', maximum_requests=2,
         maximum_credits=3, retries=0, limits=dict(body_bytes=LIMIT,total_bytes=2*LIMIT,
         request_seconds=20,wall_seconds=45)))
    summary = dict(outcome='interrupted', requests_reserved=0, credits_reserved=0,
                   consumed=True, results={})
    start = monotonic()
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        async with asyncio.timeout(45):
            async with httpx.AsyncClient(transport=transport, trust_env=False,
                    follow_redirects=False, timeout=20) as client:
                async def dispatch(name, endpoint, params, credits, before_dispatch=None):
                    remaining = 45 - (monotonic() - start)
                    if remaining <= 0:
                        raise TimeoutError('Wall limit')
                    if summary['requests_reserved'] >= 2 or summary['credits_reserved'] + credits > 3:
                        raise ValueError('Request or credit cap')
                    summary['stage'] = name + '_response'
                    summary['requests_reserved'] += 1
                    summary['credits_reserved'] += credits
                    result = await bounded_request(client, folder/name, key, BASE+endpoint,
                        params, body_limit=LIMIT, timeout_seconds=min(20, remaining), clock=clock,
                        before_dispatch=before_dispatch, reserved_credits=credits)
                    summary['results'][name] = result
                    if result['outcome'] != 'received':
                        raise ValueError('Response failed')
                    return result
                spec = strict_json(PROPOSAL.read_bytes())
                discovery = await dispatch('discovery', spec['discovery']['endpoint'],
                                           spec['discovery']['params'], 0)
                summary['stage'] = 'discovery_quota'
                q = quota(discovery, 0)
                save(folder, 'discovery-quota.json', q)
                if q['remaining'] < 3:
                    summary['outcome'] = 'insufficient_quota'
                    return summary
                summary['stage'] = 'discovery_schema_and_selection'
                events = strict_json((folder/'discovery/response.json').read_bytes())
                if not isinstance(events, list):
                    raise ValueError('Discovery must be a list')
                selected = select_event(events, discovery['received_at'])
                save(folder, 'selection.json', dict(received_at=discovery['received_at'],
                    response_sha256=discovery['body_sha256'], rule=spec['discovery']['selection'],
                    selected=selected, event_count=len(events)))
                if selected is None:
                    summary['outcome'] = 'no_eligible_event'
                    return summary
                plan = acquisition_plan(selected['id'])
                summary['stage'] = 'pregame_check'
                dispatch_at = clock()
                if time(selected['commence_time']) <= time(dispatch_at):
                    summary['outcome'] = 'event_started'
                    return summary
                save(folder, 'pregame-check.json', dict(checked_at=dispatch_at,
                    commence_time=selected['commence_time'], event_id=selected['id']))
                def check_pregame():
                    if time(selected['commence_time']) <= time(clock()):
                        raise ValueError('Event started immediately before dispatch')
                odds = await dispatch('odds', plan['endpoint'], plan['params'], 3, check_pregame)
                summary['stage'] = 'odds_quota'
                oq = quota(odds, 3)
                save(folder, 'odds-quota.json', oq)
                # Headers are evidence, not a refund/retry allowance. Unexpected
                # account movement stops the run; concurrent account use is unqualified.
                if oq['used'] - q['used'] != oq['cost'] or q['remaining'] - oq['remaining'] != oq['cost']:
                    raise ValueError('Inconsistent quota receipts')
                summary['stage'] = 'odds_schema'
                body = (folder/'odds/response.json').read_bytes()
                validate_odds(strict_json(body), selected)
                rows = normalize_event(body, 'NFL', odds['received_at'])
                save(folder, 'observations.json', rows)
                save(folder/'odds', 'receipt.json', dict(raw_sha256=odds['body_sha256'],
                     received_at=odds['received_at']))
                if monotonic() - start > 45:
                    raise TimeoutError('Wall limit')
                summary.update(outcome='acquired', observations=len(rows),
                    import_command='python -m app.reference.odds_acquire --import-retained')
    except Exception as exc:
        summary.update(outcome='stopped', error_type=type(exc).__name__)
    finally:
        logging.disable(previous_logging)
        summary['finished_at'] = clock()
        save(folder, 'summary.json', summary)
    return summary


def import_retained(folder=OUTPUT, output=None):
    """No network, no credential, and no retry of acquisition on import failure."""
    folder = Path(folder)
    summary = json.loads((folder/'summary.json').read_text())
    if summary['outcome'] != 'acquired':
        raise ValueError('Acquisition did not complete successfully')
    return import_event_response(folder/'odds/response.json', folder/'odds/receipt.json',
                                 'NFL', output or ROOT/'evidence/source-bindings-20260929/sessions')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--describe', action='store_true')
    group.add_argument('--authorization', type=Path)
    group.add_argument('--import-retained', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.describe:
            candidate = identity()
            print(json.dumps(dict(candidate=candidate, attempt_path=str(OUTPUT),
                 status='PREPARED_NOT_AUTHORIZED'), indent=2))
        elif args.import_retained:
            print(import_retained())
        else:
            authorization = json.loads(args.authorization.read_text())
            authorize(authorization, OUTPUT)  # reject before credential prompt
            key = getpass.getpass('Separately authorized Odds API key (hidden): ')
            result = asyncio.run(capture(OUTPUT, key, authorization))
            print(json.dumps(dict(outcome=result['outcome'], evidence=str(OUTPUT))))
    except (Exception, KeyboardInterrupt):
        raise SystemExit('Stopped. Inspect retained evidence; never retry this attempt.') from None


if __name__ == '__main__':
    main()
