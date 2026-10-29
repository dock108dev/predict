"""One owned JSON-shaped value from a validated immutable native book."""
from dataclasses import fields,is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from app.models.core import Ladder


def book_value(value):
    if type(value) in (str,int,float,bool,type(None)):return value
    if type(value) is Ladder:
        # Every level has already passed the immutable model's validation.
        # Emit its exact schema directly instead of reflecting seven objects
        # per level for every native delta. No prices or quantities are rounded.
        return dict(levels=[dict(price=dict(value=str(level.price.value)),
            quantity=dict(value=str(level.quantity.value),unit=level.quantity.unit))
            for level in value.levels],depth=value.depth.value)
    if isinstance(value,Enum):return value.value
    if isinstance(value,datetime):return value.isoformat()
    if isinstance(value,Decimal):return str(value)
    if is_dataclass(value):return {f.name:book_value(getattr(value,f.name)) for f in fields(value)}
    if isinstance(value,dict):return {k:book_value(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [book_value(v) for v in value]
    return value
