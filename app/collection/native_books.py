"""One Start, one game/market per venue: raw book delivery, never economics."""
import asyncio
import aiohttp
from datetime import timedelta
from . import coverage
from .odds_http import BudgetStop
from .native_selectors import POLICY, SPORTS, query

SLICE = 'native-books-v1'
CAPS = {'kalshi': 2, 'polymarket_us': 2}
CONTRACT = dict(policy=POLICY, sports=list(SPORTS), discovery_only=False,
                generations=1, slice=SLICE, acquisition_sports=['NCAAF'],
                events_per_venue=1, markets_per_venue=1)


def enabled(spec):
    from .native_target import enabled as target
    return spec.get('native_discovery', {}).get('slice') == SLICE or target(spec)


def validate(spec):
    from .native_target import enabled as target, validate_spec
    if target(spec):return validate_spec(spec)
    from .venue_access import REFERENCES
    if spec['native_discovery'] != CONTRACT:
        raise ValueError('Exact native book slice required')
    if not 0 < spec['duration'] <= 90 or spec['prediction'] != dict(
        messages=600, connections=2, frame_bytes=262144, session_bytes=8388608,
        discovery_requests=2, dollar_cap_per_source='0', dollars_per_discovery_request='0',
        dollars_per_connection='0', plan_evidence='docs/native-book-slice.md#access'):
        raise ValueError('Native book limits changed')
    if any(spec['sources'][v]['credential_reference'] != REFERENCES[v] for v in CAPS):
        raise ValueError('Exact dedicated credential references required')
    if any(x is not None for x in spec['assessment_revisions'].values()):
        raise ValueError('This slice has no qualified economics')


async def discover(d, venue):
    from .native_target import enabled as target, discover as exact
    if target(d.session.spec):return await exact(d,venue)
    # A single bounded page per venue. No account queries, retries or broad fallback.
    path, q = query(venue, 'NCAAF', d.selection_time)
    if venue == 'polymarket_us':
        q.update(marketTypes='moneyline', includeHidden='false', includePopularPlayerProps='false')
    await d.pages_for(venue, path, q, 'events', 5 if venue == 'kalshi' else 1, page_cap=1)


def choices(cats, at):
    candidates = {}
    for v in CAPS:
        candidates[v] = sorted((e for e in cats[v]['events']
            if not e['exclusion'] and e['identity'] == 'resolved' and e['canonical_key']
            and e['competition'] == 'NCAAF' and e['scheduled_start']
            and at+timedelta(minutes=5) < coverage.stamp(e['scheduled_start']) <= at+timedelta(days=7)),
            key=lambda e: (e['scheduled_start'], e['id']))
    pairs = [(k, p) for k in candidates['kalshi'] for p in candidates['polymarket_us']
             if k['canonical_key'] == p['canonical_key']]
    if pairs:
        k, p = pairs[0]
        return {'kalshi': k, 'polymarket_us': p}, 'evidenced_common_event_only'
    return {v: rows[0] for v, rows in candidates.items() if rows}, 'independent_events'


async def finish(d):
    from .native_target import enabled as target, finish as exact
    if target(d.session.spec):return await exact(d)
    from .continuous import select_inventory
    cats = {v: coverage.catalog(d.pages, v, d.selection_time) for v in CAPS}
    chosen, basis = choices(cats, d.selection_time)
    d.acquisition_selected = {v: {chosen[v]['id']} if v in chosen else set() for v in CAPS}
    d.book_market_ids = {v: [] for v in CAPS}
    async def metadata(v, event):
        status = 'selected_event_metadata_pending' if v=='kalshi' else 'embedded_complete'; error = None
        try:
            if v == 'kalshi':
                await d.pages_for(v, '/trade-api/v2/markets', dict(event_ticker=event['id']), 'markets', 5, page_cap=1)
                status = 'selected_event_market_page'
            else:
                local = dict(cats[v], markets=[m for m in cats[v]['markets'] if m['event_id'] == event['id']])
                ids, _ = select_inventory(local, d.selection_time)
                if not ids:
                    # Only exact observed slugs may be retrieved; missing identity stays excluded.
                    slugs = sorted({m['native_slug'] for m in local['markets'] if m.get('native_slug')})[:5]
                    status = 'no_complete_embedded_identity'
                    if slugs:
                        await d.pages_for(v, '/v1/markets', dict(slug=slugs, active='true', closed='false'), 'markets', 5, page_cap=1)
                        status = 'separate_slug_response_observed'
            local = coverage.catalog(d.pages, v, d.selection_time)
            local['markets'] = [m for m in local['markets'] if m['event_id'] == event['id']]
            ids, _ = select_inventory(local, d.selection_time)
            if v not in d.source_stops: d.book_market_ids[v] = ids[:1]
        except (ValueError, TimeoutError, aiohttp.ClientError, BudgetStop) as exc:
            if isinstance(exc,BudgetStop) and v not in d.source_stops and str(exc)!='native_response_byte_cap':raise
            error = type(exc).__name__ + ':' + str(exc)
        d.session.emit(v, dict(type='native_book_selection', event_id=event['id'],
            market_ids=d.book_market_ids[v], selection_basis=basis, metadata=status, error=error,
            separate_slug_delivery='observed_this_attempt' if status=='separate_slug_response_observed' else 'unverified_not_required_for_complete_embedded_identity',
            qualification='raw native books only; event association is not contract equivalence'))
    await asyncio.gather(*(metadata(v, e) for v, e in chosen.items()))
    for v in CAPS:
        if v not in chosen:
            d.session.emit(v, dict(type='native_book_selection', event_id=None, market_ids=[],
                selection_basis=basis, reason='no_supported_current_game_in_bounded_page'))


class Observations:
    """Classify accepted wire-derived native ladders; health emissions are not ticks."""
    def __init__(self):
        self.last = {}
        self.receipts = {}

    def classify(self, book, connection):
        mid = book.raw.ref.market_id
        receipt = (connection, book.raw.received_at.isoformat())
        if book.sync.value != 'synchronized' or book.receipt_freshness.value != 'recent' or self.receipts.get(mid) == receipt:
            return None
        self.receipts[mid] = receipt
        ladders = book.outcomes
        before = self.last.get(mid)
        kind = ('initial_snapshot' if before is None else 'recovery_snapshot' if before[0] != connection
                else 'repeated_identical_observation' if before[1] == ladders else 'price_or_quantity_change')
        self.last[mid] = (connection, ladders)
        def levels(outcomes):
            return {(o.outcome_id, side, level.price.value): level.quantity.value
                    for o in outcomes for side in ('bids','asks')
                    for level in (getattr(o,side).levels if getattr(o,side) else ())}
        old = levels(before[1]) if before else {}
        new = levels(ladders)
        return dict(classification=kind, connection=connection, market_id=mid,
            received_at=book.raw.received_at.isoformat(), exchange_at=book.raw.exchange_at.isoformat() if book.raw.exchange_at else None,
            source_time_progress=book.source_time_progress.value,
            price_levels_changed=None if before is None else set(old)!=set(new),
            quantities_changed=None if before is None else any(old[k]!=new[k] for k in old.keys() & new.keys()),
            comparison_to_previous=None if before is None else ('identical' if before[1] == ladders else 'changed'),
            limitation='Observed native ladder change only; receipt or repeated snapshot does not prove fresh prices')
