"""Prospective reviewed public schedules, independently keyed by venue and product."""
from copy import deepcopy
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from psycopg.types.json import Jsonb

from app.comparison.conditional_benchmark import basis as legacy_basis
from app.storage.store import hashed, stamp
from .schedule_lifecycle import REVIEW_REQUIRED

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = {
    'novig:pregame_straight': dict(venue='novig', product='pregame_straight',
        url='https://support.novig.com/en/articles/16195057-fees-on-novig',
        reference='app/fixtures/novig-fees-review-20261110.html', tag='article',
        reference_sha256='0a76bf94c8d806c6ef6c5956ca64eaf6c59946b588f89deceec4ae99d6b1a422',
        phase='scheduled', method='direct official HTML; complete normalized article text'),
    'polymarket_us:standard_sports': dict(venue='polymarket_us', product='standard_sports',
        url='https://docs.polymarket.us/fees', reference='app/fixtures/polymarket-us-fees-review-20261110.html',
        tag='main', phase=None, method='direct official HTML; complete normalized page text',
        review_receipt='app/fixtures/polymarket-us-standard-fees-review-20261111.json',
        review_receipt_sha256='1add70fd37fe03a06e09546a47d97197a4d83443e267e7f7259366c1aafc6ae4',
        alternate_receipt='app/fixtures/polymarket-us-standard-fees-review-20261112.json',
        alternate_receipt_sha256='fe99296cc172ed943611aec3088930fb5f3417710d8a84a36e4ff795681123cc'),
    'kalshi:exchange': dict(venue='kalshi', product='exchange',
        url='https://kalshi.com/docs/kalshi-fee-schedule.pdf',
        reference='app/fixtures/kalshi-fees-review-20261110.json', tag=None,
        reference_sha256='37c5790a27b6b5964579ba398feb69baab79b92291ee20ed4e8b92578845d8bf',
        rendered_pages=12,
        rendered_sha256='fe8e46228c9dcac4abe097f2738d6a02f811391063fb8baec04564473d8a589b',
        phase=None, method='Fresh official PDF rendering, exact series and event fee changes, and rounding documentation'),
}


class Text(HTMLParser):
    def __init__(self, target):
        super().__init__(); self.target=target; self.depth=0; self.count=0; self.ignored=0; self.parts=[]
    def handle_starttag(self, tag, attrs):
        if tag == self.target:
            self.count += 1; self.depth += 1
        if self.depth and tag in ('script', 'style', 'svg'):
            self.ignored += 1
    def handle_endtag(self, tag):
        if self.depth and tag in ('script', 'style', 'svg'):
            self.ignored -= 1
        if tag == self.target:
            self.depth -= 1
    def handle_data(self, text):
        if self.depth and not self.ignored:
            self.parts.append(text)


def normalized(body, tag):
    parser=Text(tag); parser.feed(body.decode('utf-8')); parser.close()
    text=' '.join(' '.join(parser.parts).split())
    if parser.count != 1 or parser.depth or parser.ignored or len(text) < 1000:
        raise ValueError('public_fee_page_unparseable')
    return text


def _receipt(path, digest, url):
    body = (ROOT / path).read_bytes()
    if sha256(body).hexdigest() != digest:
        raise ValueError('reviewed_receipt_changed')
    receipt = json.loads(body)
    if (receipt.get('source_url') != url
            or not all(re.fullmatch('[0-9a-f]{64}', receipt[key])
                       for key in ('body_sha256', 'normalized_sha256'))):
        raise ValueError('reviewed_receipt_invalid')
    return receipt['normalized_sha256'], dict(path=path, sha256=digest,
        retrieved_at=stamp(receipt['retrieved_at']).isoformat())


def approved(key):
    spec=PRODUCTS[key]
    raw=(ROOT/spec['reference']).read_bytes()
    expected=spec.get('reference_sha256', '7fc03d90a0d92345c7e4b7fcb8b567e588753e1bf6d296c3f065dddaf8bc2586')
    if sha256(raw).hexdigest()!=expected: raise ValueError('reviewed_reference_changed')
    text=normalized(raw,spec['tag']) if spec['tag'] else None
    # The reviewed source fixture itself, not dynamic website chrome, is the approval.
    approval = dict(key=key, url=spec['url'], product=spec['product'], method=spec['method'],
                reference=spec['reference'], reference_sha256=sha256(raw).hexdigest(),
                normalized_sha256=sha256(text.encode()).hexdigest() if text else None)
    if 'rendered_sha256' in spec:
        approval.update(normalized_sha256=spec['rendered_sha256'], rendered_pages=spec['rendered_pages'])
    if 'review_receipt' in spec:
        digest, receipt = _receipt(spec['review_receipt'], spec['review_receipt_sha256'], spec['url'])
        approval.update(normalized_sha256=digest, reviewed_receipt=receipt)
    if 'alternate_receipt' in spec:
        digest, receipt = _receipt(spec['alternate_receipt'], spec['alternate_receipt_sha256'], spec['url'])
        approval.update(alternate_normalized_sha256=digest, alternate_reviewed_receipt=receipt)
    return approval


def read_all(db):
    return {row['venue']:row['state'] for row in db.execute(
        'SELECT venue,state FROM public_fee_schedule WHERE venue=ANY(%s)', (list(PRODUCTS),)).fetchall()}


def write(db, key, state):
    if key not in PRODUCTS: raise ValueError('unsupported_public_fee_product')
    db.execute('''INSERT INTO public_fee_schedule VALUES (%s,%s)
        ON CONFLICT(venue) DO UPDATE SET state=excluded.state''', (key, Jsonb(state)))


def key_for(row):
    venue=row.get('venue')
    if venue=='novig':
        if row.get('game_state') in ('live','in_game') or (row.get('fee_applicability') or {}).get('phase') == 'live':
            return None
        return 'novig:pregame_straight'
    if venue=='polymarket_us': return 'polymarket_us:standard_sports'
    if venue=='kalshi': return 'kalshi:exchange'
    return None


def revision(state, *, publication=False):
    if not state: return None
    verified=state.get('last_verified') or {}; review=state.get('review_required') or {}
    return hashed([verified.get('approval_id'), review.get('approval'), review.get('reason'),
                   verified.get('revision') if publication else None]) if verified or review else None


def for_offer(states, row, at, *, fallback=None):
    key=key_for(row)
    if not key: return fallback
    state=(states or {}).get(key) or {}
    verified=state.get('last_verified') or {}
    if fallback is None:
        try: fallback=legacy_basis(row['venue'],at=at)
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError): return None
    # Older captures always use their original evidence; no gap is filled.
    review=state.get('review_required')
    if not verified or at < stamp(verified['verified_at']):
        if review and at >= stamp(review['detected_at']):
            return dict(fallback, unavailable_reason=REVIEW_REQUIRED)
        return fallback
    approval = verified['approval']
    retrieval = verified['retrieval']
    if key == 'kalshi:exchange' and 'rendered_pages' in approval:
        if (fallback.get('path'), fallback.get('sha256')) != (approval['reference'], approval['reference_sha256']):
            return dict(fallback, unavailable_reason=REVIEW_REQUIRED)
        # The full bounded receipt set stays with the product revision in Admin.
        retrieval = {name: retrieval[name] for name in (
            'rendered_origin', 'normalized_sha256', 'series_count', 'event_history_complete',
            'document_check', 'rounding_document') if name in retrieval}
    result=deepcopy(fallback)
    standing = verified.get('standing_public_terms') is True
    result.update(reviewed_at=verified['verified_at'], review_before=verified['review_before'],
        schedule_revision=revision(state), verification_revision=verified['revision'],
        retrieval=retrieval, review_basis=_review_basis(verified), product=approval['product'])
    if standing:
        result.update(standing_public_terms=True, recheck_due_at=verified['recheck_due_at'],
                      verification_scope=verified['verification_scope'])
    if review and at >= stamp(review['detected_at']): result['unavailable_reason']=REVIEW_REQUIRED
    return result


def _review_basis(verified):
    if verified.get('verification_scope') == 'market_terms_only':
        return 'Reviewed PDF terms and unchanged official market fee metadata. PDF recheck unavailable.'
    return (verified.get('approval') or {}).get('method')


def summary(key, state, at):
    spec=PRODUCTS[key]; state=state or {}; verified=state.get('last_verified') or {}
    review=state.get('review_required'); attempt=state.get('last_attempt') or {}
    fallback=legacy_basis(spec['venue'],at=at)
    standing = verified.get('standing_public_terms') is True
    deadline = verified.get('review_before') if verified else fallback['review_before']
    recheck = verified.get('recheck_due_at') or deadline
    scope = verified.get('verification_scope')
    if review:
        status = 'review_required'
    elif deadline and at >= stamp(deadline):
        status = 'expired'
    elif standing and recheck and at >= stamp(recheck):
        status = 'verification_overdue'
    elif standing and scope == 'market_terms_only':
        status = 'market_terms_verified'
    else:
        status = 'verified' if verified or deadline else 'awaiting_verification'
    action=('Review changed or ambiguous source terms' if review else
            'Recheck the official PDF when accessible' if scope == 'market_terms_only' else
            'Connect the official PDF renderer' if attempt.get('error') in ('kalshi_renderer_unconfigured', 'kalshi_renderer_configuration_invalid') else 'Retry retrieval' if attempt.get('state')=='failed'
            else 'Automatic source check' if status=='verified' else 'Verify official terms')
    direct = state.get('direct_pdf')
    if key == 'kalshi:exchange' and not direct:
        failed = (attempt.get('retrieval') or {}).get('failed_request')
        if failed and failed.get('url') == spec['url']:
            direct = failed
    return dict(venue=spec['venue'], product=spec['product'], source_url=spec['url'], state=status,
        review_basis=_review_basis(verified) or fallback.get('retrieval_method') or fallback.get('review_decision'), last_verified_at=verified.get('verified_at') or fallback['reviewed_at'],
        review_before=deadline, recheck_due_at=recheck, verification_scope=scope,
        standing_public_terms=standing, next_refresh_at=state.get('next_attempt_at'), next_action=action,
        refresh=attempt, review_required=review, retrieval=verified.get('retrieval'),
        direct_pdf=direct)
