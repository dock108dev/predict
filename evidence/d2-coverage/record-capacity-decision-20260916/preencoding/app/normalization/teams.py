"""Public team lookup; pass a loaded registry for repeated observations."""
from .registry import Registry


def resolve_team(name=None, *, registry=None, **context):
    return (registry or Registry.load()).resolve('team', name, **context)
