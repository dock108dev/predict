"""Bounded, unauthenticated refresh of the approved retail fee document."""
import asyncio
from datetime import timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
import re

import httpx

from app.fees import schedule_lifecycle as lifecycle
from app.storage.store import hashed, now, stamp

REFRESH_INTERVAL = timedelta(hours=6)
REVIEW_WINDOW = timedelta(hours=24)
RETRY_INTERVAL = timedelta(minutes=15)
INDEX_BYTES = 1024 * 1024
DOCUMENT_BYTES = 512 * 1024
DOCUMENT_URL = re.compile(r'https://framerusercontent\.com/assets/[A-Za-z0-9]+\.pdf')
CARD = re.compile(
    r'Straight Trade Fees All straight trades on site will be charged a trading fee based on the '
    r'Fee Schedule for Straight Contracts Last Updated (\w+ \d{1,2}, \d{4}) Version number (\d+(?:\.\d+)+)')


class ReviewRequired(ValueError):
    pass


class RetrievalFailed(ValueError):
    def __init__(self, reason, receipt):
        super().__init__(reason)
        self.receipt = receipt


def record_attempt(state, outcome, reason, evidence, clock, *, approval_id=None):
    """Shared retry scheduling for each independently reviewed product."""
    at = clock()
    state['last_attempt'] = dict(at=at, state=outcome, error=reason, retrieval=evidence)
    if approval_id is not None:
        state['last_attempt']['approval_id'] = approval_id
    delay = RETRY_INTERVAL if outcome == 'failed' else REFRESH_INTERVAL
    state['next_attempt_at'] = (stamp(at) + delay).isoformat()
    return state


class _Cards(HTMLParser):
    def __init__(self):
        super().__init__()
        self.link = None
        self.text = []
        self.straights = set()

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.link = dict(attrs).get('href', '')
            self.text = []

    def handle_data(self, data):
        if self.link is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.link is not None:
            label = ' '.join(' '.join(self.text).split())
            if label.startswith('Straight Trade Fees'):
                self.straights.add((self.link, label))
            self.link = None


def straight_card(body):
    cards = _Cards()
    try:
        cards.feed(body.decode('utf-8'))
        cards.close()
    except (UnicodeError, ValueError) as exc:
        raise ReviewRequired('fee_index_unparseable') from exc
    if len(cards.straights) > 1:
        raise ReviewRequired('conflicting_straight_fee_documents')
    if not cards.straights:
        raise ReviewRequired('straight_fee_document_missing')
    (url, label), = cards.straights
    match = CARD.fullmatch(label)
    if not match or not DOCUMENT_URL.fullmatch(url):
        raise ReviewRequired('fee_index_unparseable')
    return dict(url=url, published_update=match[1], published_version=match[2])


async def fetch(client, url, limit, *, query=None, fresh=False):
    headers = {'Accept-Encoding': 'identity'}
    if fresh:
        headers['Cache-Control'] = 'no-cache'
    request_url = f'{url}?{query}' if query else url
    async with client.stream('GET', request_url, headers=headers) as response:
        receipt = dict(url=url, retrieved_at=now(), http_status=response.status_code)
        if response.status_code != 200:
            raise RetrievalFailed('fee_http_status', receipt)
        if fresh:
            try:
                origin_date = parsedate_to_datetime(response.headers['date'])
                age = int(response.headers.get('age', '0'))
                if not 0 <= age <= 5 or abs((stamp(receipt['retrieved_at']) - origin_date).total_seconds()) > 60:
                    raise ValueError('outside freshness window')
            except (KeyError, ValueError, TypeError, OverflowError) as exc:
                raise RetrievalFailed('fee_response_freshness_unverified', receipt) from exc
            receipt.update(response_date=origin_date.isoformat(), age_seconds=age)
        if response.headers.get('content-encoding', 'identity').lower() != 'identity':
            raise RetrievalFailed('fee_response_encoding_unsupported', receipt)
        content = bytearray()
        async for chunk in response.aiter_raw(chunk_size=32768):
            if len(content) + len(chunk) > limit:
                raise RetrievalFailed('fee_response_size_limit', receipt)
            content.extend(chunk)
        receipt.update(sha256=sha256(content).hexdigest(), bytes=len(content), retrieved_at=now())
        return bytes(content), receipt


async def refresh(state, retrieve, *, clock=now, load=lifecycle.approved, allowed=lambda: True):
    """Verify the reviewed artifact as a whole. A new byte revision needs review."""
    state = dict(state or {})
    evidence = {}
    approval_id = None
    url = None
    try:
        approval = load()
        lifecycle.validate_rules(approval['rules'])
        approval_id = hashed(approval)
        async with asyncio.timeout(16):
            url = lifecycle.SOURCE_URL
            page, evidence['index'] = await retrieve(url, INDEX_BYTES)
            card = evidence['card'] = straight_card(page)
            if not allowed():
                return None
            url = card['url']
            body, evidence['document'] = await retrieve(url, DOCUMENT_BYTES)
        if not body.startswith(b'%PDF-') or not body.rstrip().endswith(b'%%EOF'):
            raise ReviewRequired('fee_document_unparseable')
        if (card['url'], card['published_version'], card['published_update'],
                evidence['document']['sha256']) != (
                approval['document_url'], approval['published_version'], approval['published_update'],
                approval['document_sha256']):
            raise ReviewRequired('public_straight_schedule_changed')
        prior = state.get('review_required') or {}
        if prior and prior.get('approval') == approval_id:
            raise ReviewRequired('prior_change_requires_explicit_review')
    except ReviewRequired as exc:
        state.setdefault('review_required', dict(approval=approval_id, reason=str(exc),
            detected_at=clock(), retrieval=evidence))
        outcome, reason = 'review_required', str(exc)
    except RetrievalFailed as exc:
        evidence['failed_request'] = exc.receipt
        outcome, reason = 'failed', str(exc)
    except (httpx.HTTPError, TimeoutError, OSError):
        if url is None:
            outcome, reason = 'review_required', 'fee_approval_unavailable'
            state.setdefault('review_required', dict(approval=None, reason=reason, detected_at=clock(), retrieval=evidence))
        else:
            evidence['failed_request'] = dict(url=url, retrieved_at=None)
            outcome, reason = 'failed', 'fee_retrieval_failed'
    except (ValueError, KeyError, TypeError, ArithmeticError, AttributeError) as exc:
        code = str(exc) if str(exc) in ('conflicting_approved_rules', 'fee_terms_require_model_review') else 'fee_approval_unparseable'
        state.setdefault('review_required', dict(approval=approval_id, reason=code,
            detected_at=clock(), retrieval=evidence))
        outcome, reason = 'review_required', code
    else:
        verified_at = clock()
        verified = dict(approval=approval, approval_id=approval_id, retrieval=evidence,
            verified_at=verified_at, review_before=(stamp(verified_at) + REVIEW_WINDOW).isoformat())
        verified['revision'] = hashed(verified)
        outcome = 'unchanged_verified' if state.get('last_verified', {}).get('approval_id') == approval_id else 'verified'
        state.update(last_verified=verified)
        state.pop('review_required', None)
        reason = None
    if not allowed():
        return None
    return record_attempt(state, outcome, reason, evidence, clock)


async def refresh_product(key, state, retrieve, *, clock=now, allowed=lambda: True):
    """Review one approved venue/product without changing another product's deadline."""
    from app.fees import product_schedules as products
    state = dict(state or {})
    evidence = {}; approval_id = None; url = None
    try:
        approval = products.approved(key)
        approval_id = hashed(approval)
        url = approval['url']
        if key == 'kalshi:exchange':
            from .kalshi_fee_refresh import qualify
            await qualify(approval, state, evidence, retrieve, allowed, clock)
        else:
            async with asyncio.timeout(16):
                body, evidence['document'] = await retrieve(url, INDEX_BYTES)
            text = products.normalized(body, products.PRODUCTS[key]['tag'])
            evidence['normalized_sha256'] = sha256(text.encode()).hexdigest()
            evidence['method'] = approval['method']
            if evidence['normalized_sha256'] != approval['normalized_sha256']:
                raise ReviewRequired('public_product_schedule_changed')
        prior = state.get('review_required') or {}
        if prior and prior.get('approval') == approval_id:
            raise ReviewRequired('prior_change_requires_explicit_review')
    except ReviewRequired as exc:
        outcome, reason = 'review_required', str(exc)
        if (state.get('review_required') or {}).get('approval') != approval_id or not state.get('review_required'):
            state['review_required'] = dict(approval=approval_id, reason=reason,
                detected_at=clock(), retrieval=evidence)
    except RetrievalFailed as exc:
        if exc.receipt:
            evidence['failed_request'] = exc.receipt
        outcome, reason = 'failed', str(exc)
    except (httpx.HTTPError, TimeoutError, OSError):
        if url is None:
            outcome, reason = 'review_required', 'fee_approval_unavailable'
            state.setdefault('review_required', dict(approval=approval_id, reason=reason,
                detected_at=clock(), retrieval=evidence))
        else:
            evidence['failed_request'] = dict(url=url, retrieved_at=None)
            outcome, reason = 'failed', 'fee_retrieval_failed'
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        outcome, reason = 'review_required', str(exc) or 'fee_approval_unparseable'
        state.setdefault('review_required', dict(approval=approval_id, reason=reason,
            detected_at=clock(), retrieval=evidence))
    else:
        verified_at=clock()
        verified=dict(approval=approval, approval_id=approval_id, retrieval=evidence,
            verified_at=verified_at, review_before=(stamp(verified_at)+REVIEW_WINDOW).isoformat())
        verified['revision']=hashed(verified)
        outcome='unchanged_verified' if state.get('last_verified',{}).get('approval_id')==approval_id else 'verified'
        state['last_verified']=verified; state.pop('review_required',None); reason=None
    if not allowed(): return None
    return record_attempt(state, outcome, reason, evidence, clock, approval_id=approval_id)


def product_due(key, state, at):
    if not state or stamp(state['next_attempt_at']) <= at:
        return True
    required = state.get('review_required')
    if not required:
        return False
    from app.fees import product_schedules as products
    approval_id = hashed(products.approved(key))
    return approval_id not in (required.get('approval'), (state.get('last_attempt') or {}).get('approval_id'))


async def run(runtime):
    """The local data owner runs this independently of price acquisition."""
    def allowed():
        return (runtime.service.config['enabled'] and not runtime.stopping.is_set()
                and not runtime.global_stopped and 'the_odds_api' not in runtime.paused_sources)

    def load():
        with runtime.connector() as db:
            return lifecycle.read(db)

    def save(state):
        with runtime.connector() as db:
            lifecycle.write(db, state)

    async with httpx.AsyncClient(timeout=6, follow_redirects=False, trust_env=False) as client:
        async def retrieve(url, limit, **options):
            return await fetch(client, url, limit, **options)

        while not runtime.stopping.is_set():
            if allowed():
                try:
                    previous = await asyncio.to_thread(load)
                    if not previous or stamp(previous['next_attempt_at']) <= stamp(now()):
                        updated = await refresh(previous, retrieve, allowed=allowed)
                        if updated is not None and allowed():
                            await asyncio.to_thread(save, updated)
                            if runtime.board:
                                runtime.board.wake.set()
                except Exception as exc:
                    from app.diagnostics import failure
                    failure(__name__, 'public_fee_refresh', exc)
            from app.fees import product_schedules as products
            for key, spec in products.PRODUCTS.items():
                def product_allowed():
                    paused = runtime.paused_sources
                    source = 'the_odds_api' if spec['venue']=='novig' else spec['venue']
                    return (runtime.service.config['enabled'] and not runtime.stopping.is_set()
                            and not runtime.global_stopped and source not in paused and spec['venue'] not in paused)
                if not product_allowed(): continue
                try:
                    def load_product():
                        with runtime.connector() as db: return products.read_all(db).get(key)
                    previous=await asyncio.to_thread(load_product)
                    if product_due(key, previous, stamp(now())):
                        updated=await refresh_product(key, previous, retrieve, allowed=product_allowed, clock=now)
                        if updated is not None and product_allowed():
                            def save_product():
                                with runtime.connector() as db: products.write(db,key,updated)
                            await asyncio.to_thread(save_product)
                            if runtime.board: runtime.board.wake.set()
                except Exception as exc:
                    from app.diagnostics import failure
                    failure(__name__, 'product_fee_refresh', exc)
            await asyncio.sleep(30)
