"""Qualify a fresh rendering of the official schedule and its exact market terms."""

import asyncio
from decimal import Decimal
from hashlib import sha256
import json
from secrets import token_hex
from urllib.parse import urlencode, urlsplit

import httpx

from app.fees import product_schedules as products
from app.storage.store import exact_time, stamp
from .public_fee_refresh import INDEX_BYTES, RetrievalFailed, ReviewRequired

KEY = 'kalshi:exchange'
SOURCE = products.PRODUCTS[KEY]['url']
API = 'https://external-api.kalshi.com/trade-api/v2/'
SERIES_CHANGES = API + 'series/fee_changes?show_historical=true'
EVENT_CHANGES = API + 'events/fee_changes?limit=1000'
ROUNDING = 'https://docs.kalshi.com/getting_started/fee_rounding.md'
CONFIG = products.ROOT / '.local/kalshi-fee-renderer.json'
FORMAT = 'predict-kalshi-fee-rendering-v1'
ATTEMPT_SECONDS = 50
API_SPACING_SECONDS = 1


def renderer_endpoint():
    """Load an operator-qualified renderer. Its URL contains no credentials."""
    try:
        with CONFIG.open('rb') as stream:
            config = json.loads(stream.read(4097))
        url = config['url']
        parsed = urlsplit(url)
        if (set(config) != {'url'} or len(url) > 2048 or parsed.scheme != 'https'
                or not parsed.hostname or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or not parsed.path
                or any(char.isspace() or ord(char) < 32 for char in url)):
            raise ValueError('invalid renderer endpoint')
        return url
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RetrievalFailed('kalshi_renderer_configuration_invalid', {}) from exc


def _object(body):
    def unique(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError('duplicate JSON field')
        return result

    value = json.loads(body, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError('expected JSON object')
    return value


def _digest(text):
    return sha256(' '.join(text.split()).encode()).hexdigest()


def _rendered(body, approval, nonce, started, receipt, evidence):
    try:
        payload = _object(body)
        status = payload['origin_http_status']
        origin = dict(url=SOURCE, http_status=status, retrieved_at=payload['origin_retrieved_at'])
        if (payload['format'] != FORMAT or payload['request_id'] != nonce
                or payload['source_url'] != SOURCE or type(status) is not int):
            raise ValueError('renderer provenance does not match request')
        if not stamp(started) <= stamp(origin['retrieved_at']) <= stamp(receipt['retrieved_at']):
            raise ValueError('origin retrieval outside this attempt')
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise RetrievalFailed('kalshi_rendered_origin_unverified', receipt) from exc
    evidence['rendered_origin'] = origin
    if status != 200:
        raise RetrievalFailed('kalshi_rendered_origin_http_status', origin)
    digest = payload.get('origin_sha256')
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise RetrievalFailed('kalshi_rendered_origin_unverified', receipt)
    origin['sha256'] = digest
    text = payload.get('text')
    if payload.get('complete') is not True or not isinstance(text, str) or not text.strip():
        raise ReviewRequired('kalshi_rendered_scope_ambiguous')
    pages = payload.get('page_count')
    if type(pages) is not int or not 0 < pages <= 100:
        raise ReviewRequired('kalshi_rendered_scope_ambiguous')
    evidence['rendered_pages'] = pages
    evidence['normalized_sha256'] = _digest(text)
    if (pages != approval['rendered_pages']
            or evidence['normalized_sha256'] != approval['normalized_sha256']):
        raise ReviewRequired('kalshi_rendered_schedule_changed')


def _fee_fields(row, *, override=False):
    suffix = '_override' if override else ''
    kind = row['fee_type' + suffix]
    multiplier = row['fee_multiplier' + suffix]
    if not (override and kind is None) and kind not in ('quadratic', 'quadratic_with_maker_fees'):
        raise ValueError('unsupported fee type')
    if not (override and multiplier is None):
        if type(multiplier) not in (int, float, str):
            raise ValueError('invalid fee multiplier')
        multiplier = Decimal(str(multiplier))
        if not multiplier.is_finite() or multiplier < 0:
            raise ValueError('invalid fee multiplier')
    return kind, multiplier


def _history(payload, scope, *, events=False):
    key = 'event_fee_changes' if events else 'series_fee_change_arr'
    if not isinstance(payload[key], list) or payload.get('cursor', None if events else '') != '':
        raise ValueError('incomplete fee-change history')
    rows = {}
    for row in payload[key]:
        ticker = row['series_ticker']
        if not isinstance(ticker, str) or not ticker:
            raise ValueError('missing series identity')
        identity = row['event_ticker'] if events else ticker
        if not isinstance(identity, str) or (events and not identity.startswith(ticker + '-')):
            raise ValueError('ambiguous fee-change identity')
        if ticker not in scope:
            continue
        key = (ticker, identity, exact_time(row['scheduled_ts']))
        if key in rows:
            raise ValueError('conflicting fee-change records')
        rows[key] = _fee_fields(row, override=events)
    return rows


async def qualify(approval, state, evidence, retrieve, allowed, clock):
    """Compare each fetched source to the pinned approval before renewing it."""
    previous = (state.get('last_attempt') or {}).get('retrieval') or {}
    direct = state.get('direct_pdf') or previous.get('failed_request') or previous.get('document')
    if direct and direct.get('url') == SOURCE:
        state['direct_pdf'] = direct
    endpoint = renderer_endpoint()
    if endpoint is None:
        # Keep the legacy direct receipt as a separate diagnostic. A direct
        # response cannot by itself verify the approved rendered representation.
        if 'direct_pdf' not in state and allowed():
            try:
                async with asyncio.timeout(5):
                    _, state['direct_pdf'] = await retrieve(SOURCE, INDEX_BYTES)
            except RetrievalFailed as exc:
                state['direct_pdf'] = exc.receipt
            except (httpx.HTTPError, TimeoutError, OSError):
                state['direct_pdf'] = dict(url=SOURCE, retrieved_at=None, http_status=None)
        raise RetrievalFailed('kalshi_renderer_unconfigured', {})

    async def get(url, name, *, query=None):
        if not allowed():
            raise RetrievalFailed('fee_refresh_interrupted', {})
        evidence['request_stage'] = name
        async with asyncio.timeout(5):
            body, receipt = await retrieve(url, INDEX_BYTES, query=query, fresh=True)
        evidence[name] = receipt
        return body, receipt

    async def public(url, name):
        await asyncio.sleep(API_SPACING_SECONDS)
        return (await get(url, name))[0]

    try:
        async with asyncio.timeout(ATTEMPT_SECONDS):
            nonce = token_hex(16)
            started = clock()
            body, receipt = await get(endpoint, 'renderer', query=urlencode({'request_id': nonce}))
            _rendered(body, approval, nonce, started, receipt, evidence)

            raw = (products.ROOT / approval['reference']).read_bytes()
            if (sha256(raw).hexdigest() != approval['reference_sha256']
                    or products.legacy_basis('kalshi', at=stamp(started))['sha256'] != approval['reference_sha256']):
                raise ReviewRequired('kalshi_market_terms_approval_mismatch')
            approved = _object(raw)
            for ticker, reference in approved['series'].items():
                series = _object(await public(API + 'series/' + ticker, 'series:' + ticker))['series']
                if series['ticker'] != ticker:
                    raise ReviewRequired('kalshi_market_terms_ambiguous')
                if _fee_fields(series) != _fee_fields(reference['response']['series']):
                    raise ReviewRequired('kalshi_market_terms_changed')
            changes = _object(await public(SERIES_CHANGES, 'series_changes'))
            events = _object(await public(EVENT_CHANGES, 'event_changes'))
            scope = approved['series']
            series_history = _history(changes, scope)
            if (series_history != _history(approved['series_changes'], scope)
                    or _history(events, scope, events=True) != _history(approved['event_changes'], scope, events=True)):
                raise ReviewRequired('kalshi_market_terms_changed')
            rounding = await public(ROUNDING, 'rounding_document')
            if _digest(rounding.decode()) != _digest(approved['rounding_document']):
                raise ReviewRequired('kalshi_rounding_terms_changed')
            # The current series baseline is re-dated on renewal. If a reviewed
            # transition has come due, require review of that new baseline.
            reviewed_at, checked_at = exact_time(approved['reviewed_at']), exact_time(clock())
            if any(reviewed_at < scheduled_at <= checked_at for _, _, scheduled_at in series_history):
                raise ReviewRequired('kalshi_market_terms_changed')
            evidence.update(series_count=len(scope), event_history_complete=True)
            evidence.pop('request_stage')
    except (ReviewRequired, RetrievalFailed):
        raise
    except (httpx.HTTPError, TimeoutError, OSError) as exc:
        raise RetrievalFailed('fee_retrieval_failed', {}) from exc
    except (ValueError, KeyError, TypeError, AttributeError, ArithmeticError) as exc:
        raise ReviewRequired('kalshi_market_terms_ambiguous') from exc
