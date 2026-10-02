"""Additive current-season college identities; historical registry stays immutable."""
import json
from pathlib import Path
from functools import lru_cache
from app.normalization.registry import Registry

@lru_cache(maxsize=1)
def expanded():
    base=Registry.load();data=json.loads(base.to_json());extra=json.loads(Path(__file__).with_name('college-2026-27.json').read_text())
    data['version']=extra['version']
    for key in ('entities','aliases','native_mappings'):data[key]+=extra[key]
    return Registry(data)

def for_event(event):
    if event.get('public_binding_version')=='public-contract-bindings-1':
        from app.collection.public_contracts import college_registry
        return college_registry()
    base=Registry.load()
    # Existing events keep their exact historical name-resolution decision.
    if all(cid in base.entities for cid in event.get('participants',{}).values()):return base
    return expanded()


@lru_cache(maxsize=1)
def aggregate_registry():
    """Source-scoped observed aliases; never a native event crosswalk."""
    data=json.loads(expanded().to_json())
    extra=json.loads(Path(__file__).with_name('aggregate-aliases-20260930.json').read_text())
    data['version']+='+'+extra['version']
    data['aliases']+=extra['aliases']
    return Registry(data)
