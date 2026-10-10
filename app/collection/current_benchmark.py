"""Exact two-way Pinnacle benchmark, gross conditional return on quote cost."""
from copy import deepcopy
from fractions import Fraction
from app.dashboard.current_contract import fields, stamp, text, bounded_decimal, price, result, exact_wire, display_decimal, current_eligible, packed, identity
from app.comparison.event_links import semantic_market

VERSION='pinnacle-proportional-no-vig-1'
MAXIMUM_AGE=1800


def key(record):
    s=record['selection']
    return packed([semantic_market(record),s['participant'],s['predicate'],s['signed_line']])


def attach(records,references):
    groups={}
    for r in references:
        groups.setdefault(packed(semantic_market(r)),[]).append(r)
    index={}
    for group in groups.values():
        if len(group)!=2 or len({key(r) for r in group})!=2:continue
        group=sorted(group,key=key)
        family=group[0]['market_identity']['family']
        sides=[r['selection'] for r in group]
        event=group[0]['event']
        if any(r['quote']['venue']!='pinnacle' for r in group):continue
        if family=='moneyline' and ({s['participant'] for s in sides}!={event['home'],event['away']} or {s['predicate'] for s in sides}!={'win'}):continue
        if family=='total' and {s['predicate'] for s in sides}!={'over','under'}:continue
        if family=='spread' and ({s['participant'] for s in sides}!={event['home'],event['away']} or {s['predicate'] for s in sides}!={'cover'} or Fraction(sides[0]['signed_line'])!=-Fraction(sides[1]['signed_line'])):continue
        for i,r in enumerate(group):
            index[key(r)]=dict(bookmaker='pinnacle',version=VERSION,selection_digest=None,
                odds=[x['quote']['original']['value'] for x in group],selected=i,
                source_at=[x['quote']['times']['source_at'] for x in group],
                received_at=r['quote']['times']['received_at'],sha256=r['quote']['provenance']['sha256'],maximum_age_seconds=MAXIMUM_AGE,
                selected_odds=r['quote']['original']['value'],provider_clocks=[deepcopy(x['quote'].get('provider_clocks')) for x in group])
    for r in records:
        r['quote'].pop('sharp_reference',None)
        s=r['selection'];market=r['market_identity']
        # Whole lines require push probability; do not infer it from two-way odds.
        if not r['verified'] or s['predicate']=='not_win':continue
        if market['family'] in ('spread','total') and Fraction(market['line']).denominator!=2:continue
        ref=index.get(key(r))
        if ref is not None:r['quote']['sharp_reference']=deepcopy(ref)


def validate_reference(ref,selection):
    fields(ref,{'bookmaker','version','selection_digest','odds','selected','source_at','received_at','sha256','maximum_age_seconds'},{'selected_odds','provider_clocks'})
    if ref['bookmaker']!='pinnacle' or ref['version']!=VERSION or ref['selection_digest']!=identity('binding',selection) or ref['maximum_age_seconds']!=MAXIMUM_AGE:raise ValueError('Exact Pinnacle benchmark binding required')
    if type(ref['selected']) is not int or ref['selected'] not in (0,1) or not isinstance(ref['odds'],list) or len(ref['odds'])!=2:raise ValueError('Complete two-way Pinnacle odds required')
    for value in ref['odds']:
        if bounded_decimal(value)<=1:raise ValueError('Invalid Pinnacle decimal odds')
    if 'selected_odds' in ref and ref['selected_odds']!=ref['odds'][ref['selected']]:raise ValueError('Exact selected Pinnacle odds conflict')
    if 'provider_clocks' in ref:
        if not isinstance(ref['provider_clocks'],list) or len(ref['provider_clocks'])!=2:raise ValueError('Both original Pinnacle clock descriptors required')
        for i,clocks in enumerate(ref['provider_clocks']):
            if clocks is None:continue
            fields(clocks,{'book','market','selected_basis'})
            if clocks['selected_basis'] not in ('book','market','unknown'):raise ValueError('Invalid Pinnacle provider clock basis')
            for kind in ('book','market'):stamp(clocks[kind],True)
            selected=None if clocks['selected_basis']=='unknown' else clocks[clocks['selected_basis']]
            if selected!=ref['source_at'][i]:raise ValueError('Pinnacle original clock conflict')
    if not isinstance(ref['source_at'],list) or len(ref['source_at'])!=2:raise ValueError('Both Pinnacle source clocks required')
    for at in ref['source_at']:stamp(at,True)
    stamp(ref['received_at']);text(ref['sha256'])
    if len(ref['sha256'])!=64 or any(c not in '0123456789abcdef' for c in ref['sha256']):raise ValueError('Pinnacle receipt hash required')


def calculate(q,clock):
    ref=q['sharp_reference'];basis=dict(version=VERSION,inputs=[dict(quote_id=q['id'],quote_revision=q['revision'],venue=q['venue'])],reference_sha256=ref['sha256'],formula='100 × (Pinnacle no-vig probability / normalized quote cost − 1)')
    unavailable=lambda reason:result(reason=reason,unit='percent',basis=basis)
    if clock is None:return unavailable('Evaluation clock unavailable')
    from app.comparison.current_dependencies import link_reasons
    if link_reasons(q,clock):return unavailable('Exact occurrence link expired or not effective')
    if q['state'] in ('stopped','error','unavailable','connecting','resyncing'):
        return unavailable('Updates stopped; reopen current prices' if q['state']=='stopped' else 'Quote source '+q['state'].replace('_',' ')+'; EV waits for available prices')
    clocks=[stamp(at,True) for at in ref['source_at']]
    if any(at is None for at in clocks):return unavailable('Pinnacle source time unknown')
    ages=[(clock-at).total_seconds() for at in clocks]
    if any(age<0 for age in ages) or stamp(ref['received_at'])>clock:return unavailable('Pinnacle clock is ahead of the evaluation clock')
    if max(ages)>MAXIMUM_AGE:return unavailable('Pinnacle baseline is older than the 30-minute limit')
    if q['source']['provider']=='the_odds_api':
        at=stamp(q['times']['source_at'],True)
        if not q['binding']['verified']:return unavailable('Comparison selection binding is unverified')
        if not q['display']['supported']:return unavailable('Comparison quote units or payout are unsupported')
        if at is None:return unavailable('Comparison quote source time is unknown')
        age=(clock-at).total_seconds()
        if age<0:return unavailable('Comparison quote clock is ahead of the evaluation clock')
        if age>MAXIMUM_AGE:return unavailable('Comparison quote is older than the 30-minute limit')
    elif not current_eligible(q):return unavailable('; '.join(q['comparison']['reasons']) or 'Current comparison quote is ineligible')
    cost=price(q)
    if cost<=0:return unavailable('Positive quote cost required')
    implied=[1/Fraction(odds) for odds in ref['odds']]
    probability=implied[ref['selected']]/sum(implied)
    basis.update(probability=exact_wire(probability),implied_probability_sum=exact_wire(sum(implied)),reference_age_seconds=max(ages))
    exact=exact_wire(100*(probability/cost-1))
    out=result(exact['decimal_approx'],'percent',basis=basis)
    out.update(exact=exact,display_value=display_decimal(out['value'],2,True)+' %',engine_version=VERSION,
        scope='EV vs Pinnacle · proportional no-vig benchmark · gross conditional win/loss · fees excluded; ties, pushes and exceptional settlement excluded. This is a market benchmark, not a calibrated probability model.')
    return out
