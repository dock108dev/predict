"""Optional captured-result overlay. Never calculates or grants current authority."""

from . import ordinary_evidence as evidence
from .comparison_snapshot import SnapshotOperationError
from .current_rows import event_id
from .store import encoded

MAX_RESPONSE_BYTES = 1024 * 1024


def matches(price,book,observation):
    source=price.get('source',{})
    if source.get('provider')=='the_odds_api':
        from app.dashboard.session_projection import stable
        market=book['market_id'].removeprefix('alternate_')
        native=stable([book['event_id'],market,str(observation['line']) if observation.get('line') is not None else None,observation['outcome_id']])
        if book.get('kind')=='alternate':native='alternate:'+native
        return (observation['side']=='offer' and source.get('quote_side')=='buy'
            and price.get('venue')==book['venue'] and source.get('provider')==book['provider']
            and source.get('native_event_id')==book['event_id'] and source.get('native_market_id')==native)
    return (observation['side']=='asks' and source.get('quote_side')=='buy'
        and price.get('original',{}).get('transformation')!='one_minus_native_bid'
        and price.get('venue')==book['venue'] and source.get('provider')==book['provider']
        and source.get('native_event_id')==book['event_id'] and source.get('native_market_id')==book['market_id']
        and source.get('native_outcome_id')==observation['outcome_id']
        and str(source.get('native_side','')).lower()==str(observation['native_side']).lower())


def _candidates(member, book, observation):
    prices = {row['id']: row for row in member['rows']}
    wanted = {key for key, row in prices.items() if matches(row, book, observation)}
    for key in sorted(wanted):
        yield 'ev', prices[key], [prices[key]]
    for pair in member['pairs']:
        legs = pair['legs']
        if wanted.intersection(legs) and all(leg in prices for leg in legs):
            yield 'arbs', pair, [prices[leg] for leg in legs]


def read(db, book, observation, offset=0, limit=20):
    """Associate by native identity and use only the published member's inputs."""
    from app.dashboard.product_finance import excluded_reference, visible_assumptions, visible_original, visible_row

    index = evidence.members(db)
    selected = index.get(event_id(book['provider'], book['event_id']), ())
    results = []
    count = size = 0
    for entry in selected:
        member = evidence.read_member(db, entry)
        for view, result, inputs in _candidates(member, book, observation):
            if offset <= count and len(results) < limit and size < MAX_RESPONSE_BYTES:
                exposed_inputs = [visible_original(visible_row(row)) for row in inputs]
                if view == 'ev':
                    result = exposed_inputs[0]
                elif any(excluded_reference(row) for row in inputs):
                    result = dict(result, math=dict(available=False, missing=['eligible_reference_unavailable']),
                                  minimum_return_percent=None)
                payload = dict(state='captured_result', view=view, game_key=result['game_key'],
                    calculated_at=member['calculated_at'], captured_at=member['captured_at'],
                    result_id=member['id'], snapshot_id=member['snapshot_id'],
                    policy=visible_assumptions(member['assumptions']), captured_inputs=exposed_inputs, result=result,
                    raw_revision=book['revision'], current_eligibility=False,
                    association='Exact native identity. Values and clocks come from the published result.')
                added = len(encoded(payload))
                if size + added <= MAX_RESPONSE_BYTES:
                    results.append(payload)
                else:
                    size = MAX_RESPONSE_BYTES
                    if not results:
                        raise SnapshotOperationError('ordinary_raw_result_capacity')
                size += added
            count += 1
    end = offset + len(results)
    return dict(state='captured_result' if count else 'unavailable', results=results, total=count,
                next_offset=end if end < count else None, provider_requests=0)
