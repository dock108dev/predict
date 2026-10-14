"""Bounded requested-funding balance solver using allocation-specific owners.

Find the intersection of funding and net decisive balance, then evaluate a legal
neighborhood. This is a local search, not a proof for arbitrary nonlinear fees.
"""
from fractions import Fraction as F
from itertools import product

from .net_costs import wire

MAX_ITERATIONS = 24
MAX_PROBES = 192


def allocations(legs, budget, basis, economics):
    probes = 0
    def read(qs):
        nonlocal probes
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
    qs = [x.floor(max(x.lower, exposure/x.exposure_per_native)) for x in legs]
    reason = 'bounded local net-cashflow balance; no global optimality claim'
    iterations = 0
    for iterations in range(1, MAX_ITERATIONS+1):
        capital, gap = read(qs)
        if capital == budget and gap == 0:
            break
        steps = [max(x.increment, x.floor(max(x.minimum,n/F(1000)))) for x,n in zip(legs,qs)]
        derivatives = []
        for i in range(2):
            changed = list(qs); changed[i] += steps[i]
            cc, gg = read(changed)
            derivatives.append(((cc-capital)/steps[i], (gg-gap)/steps[i]))
        (ca,ga),(cb,gb) = derivatives
        determinant = ca*gb-cb*ga
        if not determinant:
            reason = 'local funding/balance derivative singular; neighborhood only'
            break
        missing = budget-capital
        changes = [(missing*gb+cb*gap)/determinant, (-ca*gap-missing*ga)/determinant]
        changed = [x.floor(min(F(10**9),max(x.lower,n+d))) for x,n,d in zip(legs,qs,changes)]
        if changed == qs:
            break
        qs = changed
    # Only a balanced neighborhood is considered. Spending is never optimized
    # over the unrestricted grid, so an almost-outright trade cannot win.
    points = []
    for x,n in zip(legs,qs):
        points.append(sorted({n+i*x.increment for i in (-2,-1,0,1,2) if x.lower <= n+i*x.increment <= 10**9}))
    result = list(product(*points))
    return result, dict(version='ev09-requested-balance-1', iterations=iterations,
        balance_probes=probes, maximum_balance_probes=MAX_PROBES,
        continuous_target_quantities=[wire(n) for n in qs],
        global_optimality_proven=False, limitation=reason,
        residual_reason='final legal balance neighborhood; funding includes final fees and independent holds; native bound 1e9')
