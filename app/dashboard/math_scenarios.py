"""Versioned ordinary-app What-if analysis; immutable original cutoffs stay intact."""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal
from app.fees.engine import digest
from app.reference.product import devig
from app.depth import explicit_allocation, solve_explicit

VERSION='math-package-1'


def reference_sets(snapshot, game):
    """Only complete response/book/market/line/period sets; no cross-book splice."""
    groups=defaultdict(list); estimates=[];excluded=[]
    target=game['product_identity']
    original=next((r['legs'][0]['provenance']['original'] for r in snapshot.get('aggregate_comparisons',[]) if r['game_id']==game['id']),None)
    target_line=target.get('line')
    if target['family']=='spread' and original:
        target_line=str(Decimal(original['point'])*(1 if original['outcome']==original['home_team'] else -1))
    for ref in snapshot.get('references',[]):
        raw=ref.get('original_value');ident=ref.get('market_identity',{})
        if not isinstance(raw,dict) or 'decimal_odds' not in raw:continue
        if any(ident.get(k)!=target.get(k) for k in ('event','competition','family','period')):continue
        line=raw.get('point')
        if ident.get('family')=='spread' and line is not None:
            line=str(Decimal(str(line))*(1 if raw['outcome']==raw['home_team'] else -1))
        elif line is not None:line=str(Decimal(str(line)))
        if target_line is not None and (line is None or Decimal(line)!=Decimal(target_line)):continue
        key=(ref.get('provenance'),raw.get('bookmaker'),raw.get('market'),line,raw.get('received_at'),raw.get('source_at'))
        groups[key].append(ref)
    for key,refs in groups.items():
        raw=refs[0]['original_value'];market=raw['market']
        expected=['Over','Under'] if target['family']=='total' else [raw['home_team'],raw['away_team']]
        if '3_way' in market:expected.append('Draw')
        outcomes={r['original_value']['outcome']:r['original_value']['decimal_odds'] for r in refs}
        try:
            if len(outcomes)!=len(refs):raise ValueError('Conflicting duplicate reference outcome')
            if any(r.get('value') is None for r in refs):raise ValueError('Invalid source odds')
            # Canonical line orientation, never reuse the selected side's line for its opposite.
            identity=deepcopy(refs[0]['market_identity']);identity.update(line=key[3],subject='home' if target['family']=='spread' else identity.get('subject'))
            value=devig(outcomes,expected,identity=identity,provenance=dict(book=key[1],response=key[0],references=[r['id'] for r in refs]),
                        freshness=dict(received_at=key[4],source_at=key[5],mode='historical',provider_delay='unknown'))
            value['conditioning']='Quoted sporting outcomes only; pushes, voids and exceptional settlement probabilities unknown'
            estimates.append(value)
        except (ValueError,ArithmeticError,KeyError) as exc:excluded.append(dict(book=key[1],market=market,line=key[3],reason=str(exc)))
    return dict(estimates=estimates,exclusions=excluded)


def evaluate(snapshot,game,options):
    spec=options.get('spec')
    binding=dict(session=snapshot['session_id'],game=game['id'],cutoff=snapshot['points'][game['id']]['id'],
                 identity=game['product_identity'],at=snapshot['points'][game['id']]['at'])
    result=dict(version=VERSION,binding=binding,references=reference_sets(snapshot,game),
                label='Hypothetical What-if; user-supplied assumptions do not qualify real prices, execution, fees or settlement',
                original_outputs='Preserved. This is a separate versioned derived calculation.')
    if options.get('conversion') is not None:
        from app.reference.product import odds_cashflows
        result['conversion']=odds_cashflows(**options['conversion'])
    if options.get('public_contract') is not None:
        from app.dashboard.public_scenarios import evaluate as public_evaluate
        result['public_contract_request']=deepcopy(options['public_contract'])
        result['public_contract_game']=dict(product_identity=deepcopy(game['product_identity']),sources={
            s:dict(market_id=v['market_id']) for s,v in game['sources'].items()})
        result['public_contract_calculation']=public_evaluate(options['public_contract'],result['public_contract_game'])
    if spec is not None:
        spec=deepcopy(spec)
        # This public path accepts manual assumptions only. Model/reference bindings
        # must come from retained inputs, not a caller-supplied classification label.
        spec['probability_kind']='manual What-if'
        selection=options.get('reference_estimate')
        if selection is not None:
            refs=result['references']['estimates']
            if type(selection) is not int or not 0<=selection<len(refs):raise ValueError('Unknown reference estimate')
            reference=refs[selection]
            if set(reference['probabilities'])!=set(spec['states']):raise ValueError('Reference outcome set must equal scenario states; no inferred push or void probability')
            if options.get('reference_conditioning_acknowledged') is not True:raise ValueError('Explicit quoted-state conditional interpretation required')
            spec['probabilities']=reference['probabilities'];spec['probability_kind']='reference-derived estimate'
            result['reference_basis']=reference
        quantities=options.get('quantities')
        result['calculation']=explicit_allocation(spec,quantities) if quantities is not None else solve_explicit(spec,max_evaluations=options.get('max_evaluations',4096))
        result['spec']=spec;result['quantities']=quantities
        value=result['calculation'] if quantities is not None else result['calculation']['best']
        result['watch_metrics']=None if value is None else dict(hypothetical=True,ev_pct=value['ev_pct'],arbitrage_return_pct=value['return_pct'],worst_case_return=value['worst_case_return'],live_signal_eligible=False)
        result['exclusions']=[] if value is None else value['reasons']
    result['sha256']=digest(result)
    return result


def replay(bundle):
    value=deepcopy(bundle);checksum=value.pop('sha256')
    if value['version']!=VERSION or digest(value)!=checksum:raise ValueError('Scenario bundle hash / version mismatch')
    if 'public_contract_request' in value:
        from app.dashboard.public_scenarios import evaluate as public_evaluate
        if public_evaluate(value['public_contract_request'],value['public_contract_game'])!=value['public_contract_calculation']:
            raise ValueError('Public contract scenario replay mismatch')
    if 'spec' in value:
        old=value['calculation'];q=value['quantities']
        rebuilt=explicit_allocation(value['spec'],q) if q is not None else solve_explicit(value['spec'],max_evaluations=old['search']['requested_evaluations'])
        if rebuilt!=old:raise ValueError('Derived calculation replay mismatch')
    return bundle
