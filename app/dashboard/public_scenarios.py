"""Public contract scenarios on existing engines, bound to an immutable cutoff."""
from copy import deepcopy
from decimal import Decimal
from app.collection import public_contracts as contracts


def evaluate(request, game):
    r=deepcopy(request)
    if r.pop('version',None)!=contracts.VERSION:raise ValueError('Explicit public contract version required')
    kind=r.pop('kind',None)
    if kind=='account':
        from app.resolution.source_adapters import kalshi_account_report
        from app.fees.public_bindings import us_execution
        format=r.pop('format');source=r.pop('source');market_id=r.pop('market_id');body=r.pop('body')
        if source not in game['sources'] or market_id!=game['sources'][source]['market_id']:
            raise ValueError('Account observation exact selected source/market conflict')
        if format=='kalshi_account_report' and source=='kalshi':
            decoded=kalshi_account_report(body,ticker=market_id,party_id=r.pop('party_id'))
        elif format=='us_execution' and source=='polymarket_us':
            basis=r.pop('association_basis')
            if not isinstance(basis,str) or not basis.strip() or len(basis)>2000:raise ValueError('Explicit execution/order association basis required')
            decoded=dict(us_execution(body),market_id=market_id,association_basis=basis,
                         kind='Account execution amounts; explicit caller association, not sporting result or venue resolution')
        else:raise ValueError('Unsupported account observation format/source')
        if r:raise ValueError('Unknown account observation controls')
        return dict(kind=kind,decoded=decoded,scope='Explicit supplied account/scenario record; no account access, actual position inference or provider publication history')
    if kind=='fees':
        from app.fees.public_bindings import bind
        from app.fees import calculate
        c=r.pop('context');source=c['venue']
        if source not in game['sources'] or c['market_id']!=game['sources'][source]['market_id']:
            raise ValueError('Fee scenario exact selected source/market conflict')
        options={k:r.pop(k) for k in ('market','membership','instrument') if k in r}
        if r:raise ValueError('Unknown public fee controls')
        c=bind(c,**options)
        return dict(kind=kind,fee_audit=calculate(c),scope='Public formula with explicit hypothetical fills/account or association inputs; no actual fill inference')
    if kind=='score':
        from app.normalization.score_lines import orient_descriptor,payout
        binding=r.pop('binding');native=r.pop('native');event=r.pop('event');scores=r.pop('scores')
        identity=game['product_identity']
        if any(binding[k]!=identity[k2] for k,k2 in [('sport','competition'),('period','period'),('family','family')]):
            raise ValueError('Score scenario selected scope conflict')
        from app.resolution.core import event_key
        if event_key(event)!=identity['event']:raise ValueError('Score scenario exact selected event conflict')
        result=contracts.descriptor(native,binding,tie_strike_listed=r.pop('tie_strike_listed',None))
        if r:raise ValueError('Unknown score controls')
        domain,sides=orient_descriptor(event,result['descriptor'])
        originals=identity.get('outcome_set')
        if isinstance(originals,dict):
            expected,_=orient_descriptor(event,next(iter(originals.values())))
            if any(domain[k]!=expected[k] for k in ('domain','threshold')):raise ValueError('Score scenario selected line/participant conflict')
        if not isinstance(scores,list) or not 1<=len(scores)<=32:raise ValueError('Bounded explicit score scenarios required')
        values=[]
        for observation in scores:
            if observation.get('period')!=binding['period'] or observation.get('completed') is not True:
                raise ValueError('Explicit completed selected-period score required')
            h,a=observation['home'],observation['away']
            if any(type(v) is not int or not 0<=v<=1000 for v in (h,a)):raise ValueError('Bounded integer sporting scenario scores required')
            value=h-a if domain['domain']=='home_margin' else h+a
            values.append(dict(scenario=observation,payouts={s['native_id']:payout(s,dict(representative=str(value))) for s in sides}))
        return dict(kind=kind,binding=result,domain=domain,states=values,probability_required=False,
                    scope='Hypothetical completed-period sporting scores; venue decision and exception branches separate')
    if kind=='portfolio':
        from app.settlement import portfolio
        if set(r)-{'legs','states','complete','probabilities','reserve'}:raise ValueError('Unknown payoff controls')
        return dict(kind=kind,calculation=portfolio(**r),probability_required=False)
    raise ValueError('Unsupported public contract scenario')
