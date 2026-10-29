"""Physical book dependencies, independent of economic review qualification.

Catalog price observations and presentation counters cannot invalidate a valid
wire image. Actual market terms, sides, eligibility and unknown fields remain
dependencies. This projection never changes the retained catalog or review seals.
"""
from copy import deepcopy
from .native_review_contract import OBSERVATIONS


def project(venue, raw, *, event=False):
    value=deepcopy(raw)
    for key in OBSERVATIONS[venue]:value.pop(key,None)
    if venue=='kalshi':
        # Modification time describes the enclosing metadata, not a rule/time
        # boundary. Preserve malformed values rather than hiding a new schema.
        modified(value,'last_updated_ts')
        modified(value,'updated_time')
    elif venue=='polymarket_us':
        if not event:
            for side in value.get('marketSides',[]):
                if isinstance(side,dict):
                    side.pop('price',None);side.pop('quote',None)
        else:
            count(value.get('chatChannel'),'chatMemberCount')
            for container in ('marketCounts','combos'):
                for key in ('numMarkets','numSpreadsAndTotalsMarkets'):
                    count(value.get(container),key)
            metadata=value.get('metadata')
            for state in (value.get('eventState'),metadata.get('gameState') if isinstance(metadata,dict) else None):
                if not isinstance(state,dict):continue
                modified(state,'updatedAt')
                number(state,'mainSpreadLine')
                number(state,'mainTotalLine')
                for group in state.get('marketGroupStats',[]):
                    if isinstance(group,dict):number(group,'line')
    return value


def modified(value,key):
    if key not in value:return
    from app.dashboard.session_projection import stamp
    try:
        if not isinstance(value[key],str) or stamp(value[key]).utcoffset() is None:return
    except (ValueError,TypeError):return
    value.pop(key)


def count(value,key):
    if isinstance(value,dict) and type(value.get(key)) is int and value[key]>=0:value.pop(key)


def number(value,key):
    from decimal import Decimal,InvalidOperation
    if key not in value or isinstance(value[key],bool):return
    try:
        if Decimal(str(value[key])).is_finite():value.pop(key)
    except (InvalidOperation,ValueError,TypeError):pass
