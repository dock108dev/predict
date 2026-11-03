"""Price grouping independent of financial models; originals remain in prices.

Unsupported settlement identities are display buckets only, never comparable
best-price groups. No native NO is renamed to its opposing participant.
"""
from collections import defaultdict
from app.storage.store import hashed


def group_prices(prices):
    groups={}
    for q in prices:
        s=q.get('selection',{});m=q.get('market',{});identity=q.get('same_outcome',{})
        supported=identity.get('supported') is True and isinstance(identity.get('key'),list)
        display=[m.get('market'),m.get('period'),s.get('participant'),s.get('predicate'),s.get('signed_line',m.get('line'))]
        key=hashed(['comparable',identity['key']] if supported else ['unqualified_display',display])
        if key not in groups:
            groups[key]=dict(id=key,comparable=supported,selection=s,market=m,cells=defaultdict(list),reason_codes=set())
        row=groups[key];row['cells'][q['venue']].append(q['quote_id'])
        if not supported:row['reason_codes'].add(identity.get('reason') or 'comparison_identity_unavailable')
    rows=[]
    for row in groups.values():
        row['cells']={k:sorted(set(v)) for k,v in sorted(row['cells'].items())}
        row['reason_codes']=sorted(row['reason_codes']);rows.append(row)
    return dict(version='predict-grouped-odds-1',unit='received_price_observation',
        observations=len(prices),rows=sorted(rows,key=lambda r:r['id']),
        meaning='Comparable normal-payout prices before costs; exceptional settlement remains in Details')


def reference_prices(records):
    """Reference-only originals, including exact alternate lines; never legs."""
    from copy import deepcopy
    from .u0_display import quote_display
    result=[]
    for r in records:
        q=r['quote']
        if q['venue']!='pinnacle':continue
        original=q['original'];s=r['selection'];m=r['market_identity']
        result.append(dict(id=hashed(q['source']),venue='pinnacle',role='reference_only',
            selection=deepcopy(s),market=deepcopy(m),source=deepcopy(q['source']),
            original=deepcopy(original),times=deepcopy(q['times']),
            common_odds=quote_display(original['value'],original['units'],original.get('payout','1'))))
    for q in result:q['common_odds'].pop('what_if',None)
    return sorted(result,key=lambda q:q['id'])


def grid_board(board, *, compact=True):
    """Small grid wire view; selected-frame evidence stays in the captured lease."""
    from .comparison_board import expand_price_fields, compact_price_fields
    expand_price_fields(board)
    for q in board['prices']:
        for field in ('gross_comparison','current_comparison','native_contract_summary',
                      'observed_depth','observed_book','book_confirmation','provider_clocks'):
            q.pop(field,None)
    board.pop('native_wordings',None)
    board.pop('comparison_input_encoding',None)
    board['grouped_odds']=group_prices(board['prices'])
    return compact_price_fields(board) if compact else board


def grid_wire(board):
    """Trim display-only payload after exact server aging has completed.

    Every price, source ID, original, clock, refusal and captured selection token
    remains. Full occurrence/rule/depth evidence stays in the immutable lease.
    """
    for q in board['prices']:
        for field in ('event','occurrence_match','source_health','captured_source_health',
                      'observation_time_evidence','captured_source_state','freshness_policy'):
            q.pop(field,None)
    for row in [*board['prices'],*board.get('grouped_odds',{}).get('rows',[])]:
        if 'selection' in row:
            row['selection']={k:v for k,v in row['selection'].items()
                if k in ('participant','predicate','signed_line','label','result_interpretation','period_boundary')}
    return board
