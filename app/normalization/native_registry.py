"""Versioned captured native mappings, separate from historical/aggregate registries."""
import json
from pathlib import Path
from .registry import Registry
from functools import lru_cache

@lru_cache(maxsize=2)
def native_registry(live=False):
    data=json.loads(Registry.load().to_json())
    extra=json.loads(Path(__file__).with_name('native-gap-bindings-20260930.json').read_text())
    data['version']+='+'+extra['version']
    for key in ('entities','aliases','native_mappings'):data[key]+=extra[key]
    if live:
        path=Path(__file__).with_name('native-live-bindings-20260930.json')
        if path.stat().st_size>128*1024:raise ValueError('Live native identity catalog bound')
        current=json.loads(path.read_text());data['version']+='+'+current['version']
        for key in ('entities','aliases','native_mappings'):data[key]+=current[key]
    return Registry(data)
