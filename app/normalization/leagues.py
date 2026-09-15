"""Only registry leagues resolve; planned scope is not implied coverage."""
from .registry import Registry


def resolve_league(name=None, *, registry=None, **context):
    return (registry or Registry.load()).resolve('league', name, **context)
