"""Versioned, evidence-bearing settlement comparison, independent of event identity.

Values are explicit semantic assessments, never inferred by comparing prose.
None is unknown; equivalent assessments need a separate pair-bound approval.
"""
from decimal import Decimal, InvalidOperation
from app.matching import clone, digest

VERSION = 'settlement-comparator-1'
PROFILE_VERSION = 'moneyline-rules-1'
DIMENSIONS = ('overtime', 'tie', 'postponement', 'resumption', 'cancellation',
              'abandonment', 'forfeit', 'shortened_game', 'listed_pitchers',
              'settlement_sources', 'deadlines', 'fair_value', 'venue_change',
              'result_corrections')
SCENARIOS = ('tie', 'postponed_outside_window', 'canceled', 'abandoned',
             'pregame_forfeit', 'shortened_game', 'discretionary_review')


def fact(value=None, *, evidence=None, reason=None, certainty='exact'):
    if certainty not in ('exact', 'equivalent'):
        raise ValueError('unsupported assessment certainty')
    if value is not None and not evidence:
        raise ValueError('known rule requires evidence')
    return {'value':value, 'evidence':evidence, 'reason':reason,
            'certainty':certainty}


def profile(*, sources, dimensions=None, payouts=None, effective_date=None, actor):
    if not sources or not actor.strip():
        raise ValueError('profile requires sources and actual assessment actor')
    dimensions = dimensions or {}
    if set(dimensions) - set(DIMENSIONS):
        raise ValueError('unmodeled material dimension; bump profile version')
    fields = {k:clone(dimensions.get(k, fact(reason='not established: '+k))) for k in DIMENSIONS}
    source_ids = {s['sha256'] for s in sources}
    for s in sources:
        if not all(s.get(k) for k in ('url','sha256','text')):
            raise ValueError('rule source requires URL, hash and retained text')
    for f in fields.values():
        fact(**f)
        if f['value'] is not None and f['evidence'] not in source_ids:
            raise ValueError('rule evidence must reference retained source')
    payouts = payouts or {}
    if set(payouts) - set(SCENARIOS):
        raise ValueError('unmodeled payout scenario')
    for p in payouts.values():
        if p['kind'] not in ('fraction','refund','discretionary','unknown'):
            raise ValueError('invalid payout kind')
        if p['kind'] != 'unknown' and p.get('evidence') not in source_ids:
            raise ValueError('payout requires retained evidence')
        if p['kind'] == 'fraction':
            v=Decimal(p['value'])
            if not v.is_finite() or not 0 <= v <= 1: raise ValueError('invalid payout fraction')
    row={'version':PROFILE_VERSION, 'dimensions':fields, 'sources':clone(sources),
         'payouts':{k:clone(payouts.get(k, {'kind':'unknown','reason':'not established: '+k})) for k in SCENARIOS},
         'effective_date':effective_date, 'actor':actor}
    row['hash']=digest(row)
    return row


def validate(p):
    if p['version'] != PROFILE_VERSION or p['hash'] != digest({k:v for k,v in p.items() if k!='hash'}):
        raise ValueError('invalid rule profile version/hash')
    rebuilt=profile(sources=p['sources'],dimensions=p['dimensions'],payouts=p['payouts'],
                    effective_date=p['effective_date'],actor=p['actor'])
    if rebuilt != p: raise ValueError('invalid profile')


def compare_profiles(a,b,approvals=()):
    validate(a); validate(b)
    unknown=[]; conflicts=[]; equivalent=[]
    for k in DIMENSIONS:
        x,y=a['dimensions'][k],b['dimensions'][k]
        if x['value'] is None or y['value'] is None:
            unknown.append({'condition':k,'left':x,'right':y})
        elif x['value'] != y['value']:
            conflicts.append({'condition':k,'left':x,'right':y})
        elif 'equivalent' in (x['certainty'],y['certainty']):
            equivalent.append(k)
    # Payout tables are also material evidence; equal unknowns never establish equivalence.
    for k in SCENARIOS:
        x,y=a['payouts'][k],b['payouts'][k]
        if 'unknown' in (x['kind'],y['kind']):
            unknown.append({'condition':'payout:'+k,'left':x,'right':y})
        elif x['kind'] != y['kind'] or (x['kind']=='fraction' and Decimal(x['value']) != Decimal(y['value'])):
            conflicts.append({'condition':'payout:'+k,'left':x,'right':y})
        elif x['kind']=='discretionary':
            unknown.append({'condition':'payout:'+k,'left':x,'right':y,
                            'reason':'independent venue discretion does not establish equal payoffs'})
    status='INCOMPATIBLE' if conflicts else 'UNKNOWN' if unknown else 'COMPATIBLE' if equivalent else 'EXACT'
    binding=sorted([a['hash'],b['hash']])
    reviews=[r for r in approvals if r.get('profiles')==binding and r.get('comparator')==VERSION
             and all(r.get(k) for k in ('actor','reason','source','reviewed_at')) and r.get('action')=='approve-compatible']
    return {'version':VERSION,'profiles':binding,'status':status,'unknown':unknown,
            'conflicts':conflicts,'equivalent_dimensions':equivalent,'approvals':clone(reviews),
            'qualified':status=='EXACT' or status=='COMPATIBLE' and bool(reviews),
            'reason':'supported material equivalence' if status=='EXACT' else
                     'explicit equivalence assessment; pair approval required' if status=='COMPATIBLE' else
                     'specific material conflicts' if conflicts else 'material conditions or payoffs unresolved'}


def payout(side, winner, p):
    """Normal sporting result or exceptional condition; fractions are per $1 payout.

    Refund retains a cost-dependent symbol. NO complements a contract fraction,
    never turns a refund or independent fair-value decision into a fabricated number.
    """
    if winner.startswith('winner:'):
        v = Decimal(int(winner[7:]==side['participant']))
        if side['predicate']=='not_win': v=1-v
        return {'kind':'fraction','value':str(v)}
    result=clone(p['payouts'][winner])
    if side['predicate']=='not_win' and result['kind']=='fraction':
        result['value']=str(1-Decimal(result['value']))
    return result


def relationships(a,b,pa,pb,participants,settlement):
    rows=[]
    for x in a:
        for y in b:
            scenarios={k:{'left':payout(x,k,pa),'right':payout(y,k,pb)}
                       for k in [*('winner:'+p for p in participants),*SCENARIOS]}
            known=[]; missing=[]
            for k,s in scenarios.items():
                l,r=s['left'],s['right']
                if l['kind']==r['kind']=='fraction':
                    known.append((k, Decimal(l['value'])+Decimal(r['value'])==1))
                else: missing.append(k)
            noncomplement=[k for k,ok in known if not ok]
            complement='NO' if noncomplement else 'UNKNOWN' if missing or not settlement['qualified'] else 'YES'
            rows.append({'left_side':x['native_id'],'right_side':y['native_id'],
                'same_exposure':(x['participant'],x['predicate'])==(y['participant'],y['predicate']),
                'opposing_sporting_outcomes':x['predicate']==y['predicate']=='win' and x['participant']!=y['participant'],
                'opposite_predicates':x['participant']==y['participant'] and x['predicate']!=y['predicate'],
                'complementary_payoffs':complement,'noncomplementary_cases':noncomplement,
                'unresolved_cases':missing,'scenarios':scenarios})
    return rows
