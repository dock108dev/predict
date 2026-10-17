"""Bounded requested-funding balance solver using allocation-specific owners.

Find the intersection of funding and net decisive balance, then evaluate a legal
neighborhood. This is a local search, not a proof for arbitrary nonlinear fees.
"""
from fractions import Fraction as F
from itertools import product

from .net_costs import wire
from .calculation_control import checkpoint

MAX_ITERATIONS = 24
MAX_PROBES = 192


def allocations(legs, budget, basis, economics, *, observed_bounds=None):
    # Scanner tickets may only consume supplied observed native quantities.
    # The optional bound leaves all legacy requested-trade behavior unchanged.
    if observed_bounds is not None:
        if len(observed_bounds) != len(legs):
            raise ValueError('requested_two_observed_bounds_required')
        observed_bounds = [F(n) for n in observed_bounds]
        if any(n < x.lower for x,n in zip(legs,observed_bounds)):
            raise ValueError('requested_observed_depth_below_meaningful_minimum')
    def bounded(index, quantity):
        upper = F(10**9) if observed_bounds is None else min(F(10**9), observed_bounds[index])
        return legs[index].floor(min(upper,max(legs[index].lower,quantity)))
    probes = 0
    def read(qs):
        nonlocal probes
        checkpoint()
        if probes + 2 > MAX_PROBES:
            raise ValueError('requested_balance_probe_limit')
        components = [x.get(n) for x,n in zip(legs,qs)]
        probes += 2
        capital, states = economics(components, basis)
        a, b = (states[s]['profit_usd'] for s in ('a_wins','b_wins'))
        if a is None or b is None:
            raise ValueError('requested_decisive_cashflows_unknown')
        return capital, F(a)-F(b)

    exposure = budget/sum(x.path['minimum_cost']/x.exposure_per_native for x in legs)
    qs = ([x.floor(max(x.lower,exposure/x.exposure_per_native)) for x in legs]
          if observed_bounds is None else
          [bounded(i,exposure/x.exposure_per_native) for i,x in enumerate(legs)])
    reason = 'bounded local net-cashflow balance; no global optimality claim'
    iterations = 0
    for iterations in range(1, MAX_ITERATIONS+1):
        capital, gap = read(qs)
        if capital == budget and gap == 0:
            break
        steps = [max(x.increment, x.floor(max(x.minimum,n/F(1000)))) for x,n in zip(legs,qs)]
        derivatives = []
        for i in range(2):
            changed = list(qs)
            step = steps[i]
            if observed_bounds is not None and changed[i]+step > observed_bounds[i]:
                step = -min(step, changed[i]-legs[i].lower)
            if not step:
                reason = 'observed legal bound leaves no local derivative; neighborhood only'
                break
            changed[i] += step
            cc, gg = read(changed)
            derivatives.append(((cc-capital)/step, (gg-gap)/step))
        if len(derivatives) != 2:
            break
        (ca,ga),(cb,gb) = derivatives
        determinant = ca*gb-cb*ga
        if not determinant:
            reason = 'local funding/balance derivative singular; neighborhood only'
            break
        missing = budget-capital
        changes = [(missing*gb+cb*gap)/determinant, (-ca*gap-missing*ga)/determinant]
        changed = [bounded(i,n+d) for i,(n,d) in enumerate(zip(qs,changes))]
        if observed_bounds is not None:
            # An exhausted observed leg cannot fund the requested target.
            # Balance its opposite leg instead of inventing deeper liquidity.
            for i in range(2):
                if qs[i]+changes[i] > observed_bounds[i]:
                    j=1-i; slope=derivatives[j][1]
                    if slope:
                        delta=-(gap+derivatives[i][1]*(changed[i]-qs[i]))/slope
                        changed[j]=bounded(j,qs[j]+delta)
        if changed == qs:
            break
        qs = changed
    # Only a balanced neighborhood is considered. Spending is never optimized
    # over the unrestricted grid, so an almost-outright trade cannot win.
    points = []
    for index,(x,n) in enumerate(zip(legs,qs)):
        upper=F(10**9) if observed_bounds is None else min(F(10**9),observed_bounds[index])
        points.append(sorted({n+i*x.increment for i in (-2,-1,0,1,2) if x.lower <= n+i*x.increment <= upper}))
    result = list(product(*points))
    return result, dict(version='ev09-requested-balance-1', iterations=iterations,
        balance_probes=probes, maximum_balance_probes=MAX_PROBES,
        continuous_target_quantities=[wire(n) for n in qs],
        global_optimality_proven=False, limitation=reason,
        residual_reason='final legal balance neighborhood; funding includes final fees and independent holds; native bound 1e9')
