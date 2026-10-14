"""Read-only request policy: validation and financial owners shared by all views."""
from dataclasses import replace
from fractions import Fraction

from app.dashboard.u0_display import bounded_decimal
from .estimated_policy import EstimatePolicy


def effective_policy(base, *, ceiling=None, buffer=None, amount=None, sizing_mode=None, benchmark_venue=None, benchmark_method=None):
    policy = EstimatePolicy.from_dict(base) if isinstance(base, dict) else base
    changes = {}
    if amount is not None:
        bounded_decimal(amount)
        if ceiling is not None:
            bounded_decimal(ceiling)
        if ceiling is not None and Fraction(amount) != Fraction(ceiling):
            raise ValueError('conflicting requested amounts')
        ceiling = amount
    choices = dict(sizing_mode=sizing_mode, benchmark_venue=benchmark_venue, benchmark_method=benchmark_method)
    if any(v is not None for v in choices.values()):
        from .estimated_policy import RequestedTradePolicy
        if not isinstance(policy, RequestedTradePolicy):
            raise ValueError('explicit successor policy required for new settings')
        changes.update({k:v for k,v in choices.items() if v is not None})
    for name, value in (('capital_ceiling_usd', ceiling), ('buffer_rate', buffer)):
        if value is not None:
            bounded_decimal(value)
            changes[name] = value
    return replace(policy, **changes)


def recalculate(state, policy):
    """Rebuild derived values only; never save policy or touch observations."""
    # Inputs are immutable captured publication values. Own only the groups
    # whose derived metrics are rebuilt; do not duplicate the slate registry,
    # old pair results or all groups before the first occurrence is evaluated.
    result = dict(state, events=[])
    for original in state['events']:
        steps=event_steps(state,original,policy)
        while True:
            try:next(steps)
            except StopIteration as done:
                result['events'].append(done.value)
                break
    result['estimate_policy'] = policy.to_dict()
    return result


def event_steps(state, original, policy):
    """Own one occurrence's writable shells; immutable inputs stay shared.

    The synchronous consumer drains these identical financial owners. The HTTP
    job yields after each quote, prepared leg and pair and discards the occurrence
    after encoding, so no rebuilt whole-slate graph is retained.
    """
    from app.dashboard.current_contract import stamp
    from .current_metrics import group_metric_steps
    from .current_details import compact_group
    from .shared_templates import shared
    from .estimated_pair import assembly_steps
    event={k:v for k,v in original.items() if k not in ('groups','funded_pairs','funded_pair_search')}
    event['groups']=[]
    profiles=state.get('comparison_profiles',{})
    at=stamp(state['clock_at'])
    for original_group in original['groups']:
        group=dict(original_group,outcomes=[])
        event['groups'].append(group)
        for o in original_group['outcomes']:
            def shell(q):return dict(q,calculations=dict(q['calculations']))
            group['outcomes'].append(dict(o,quotes={v:shell(q) for v,q in o['quotes'].items()},
                alternatives={v:[shell(q) for q in qs] for v,qs in o.get('alternatives',{}).items()}))
        yield from group_metric_steps(group,profiles,at,event=event,estimate_policy=policy)
        if shared(profiles):compact_group(group)
    event['funded_pairs'],event['funded_pair_search']=yield from assembly_steps(event,profiles,at,policy=policy)
    return event


def request_binding(request, state):
    """Optional pinned comparison requests reject crossed current identities."""
    from app.dashboard.current_state import SelectionError
    if ('runtime_id' in request) != ('state_revision' in request):
        raise ValueError('Both runtime and state revision are required')
    if 'runtime_id' in request:
        revision = request['state_revision']
        if not isinstance(revision, str) or not revision.isdigit() or not 1 <= int(revision) <= 9007199254740991:
            raise ValueError('Positive bounded state revision required')
        if request['runtime_id'] != state['runtime_id']:
            raise SelectionError(410, 'selection_expired', 'Current runtime changed')
        if int(revision) != state['state_revision']:
            raise SelectionError(409, 'selection_changed', 'Current inputs changed')
    generation = request.get('request_generation')
    if generation is not None and (not isinstance(generation, str) or not generation.isdigit() or not 0 <= Fraction(generation) <= 9007199254740991):
        raise ValueError('Bounded request generation required')
    return generation
