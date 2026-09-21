"""Pure scope gate for reviewed reference-to-market bindings; no fuzzy matching.

Does not rewrite persisted identities; projection and economic evidence gates remain required.
"""
from app.reference.product import time

SPORTS={'NFL':'american_football','NCAAF':'american_football','NHL':'ice_hockey','MLB':'baseball','NBA':'basketball','NCAAB':'basketball'}

def sport_key(sport,competition):
    if competition=='NHL' and sport=='hockey':sport='ice_hockey'
    if competition in ('NFL','NCAAF') and sport=='football':sport='american_football'
    if SPORTS.get(competition)!=sport:raise ValueError('Sport/competition mismatch')
    return sport


def scope_match(source,target,*,source_teams,target_teams,team_bindings,reviewed_rules=None):
    """Explicit full-game event candidate gate; success is not fee/settlement qualification.

    team_bindings maps exactly two source names to two reviewed target identities.
    reviewed_rules is an explicit pair; absent rule equivalence fails closed.
    """
    reasons=[]
    try:
        if sport_key(source['sport'],source['competition'])!=sport_key(target['sport'],target['competition']):reasons.append('sport')
    except (KeyError,ValueError):reasons.append('sport')
    for field in ('competition','season','stage','family','period','line','subject','outcome_set','category','horizon'):
        if source.get(field)!=target.get(field):reasons.append(field)
    try:
        if time(source['scheduled_start'])!=time(target['scheduled_start']):reasons.append('scheduled_start')
    except (KeyError,TypeError,ValueError,AttributeError):reasons.append('scheduled_start')
    if len(source_teams)!=2 or len(set(source_teams))!=2 or len(target_teams)!=2 or len(set(target_teams))!=2 or set(team_bindings)!=set(source_teams) or set(team_bindings.values())!=set(target_teams):reasons.append('reviewed participant binding')
    if not source.get('rules') or not target.get('rules') or reviewed_rules!=(source.get('rules'),target.get('rules')):reasons.append('reviewed settlement equivalence')
    if source.get('family')!='moneyline' or source.get('period')!='full_game' or source.get('line') is not None:reasons.append('B5 market semantics')
    from app.normalization.nhl import RULES
    nhl=source.get('competition')=='NHL' and source.get('rules')==RULES and source.get('outcome_set')=='two_way' and source.get('stage') in ('regular_season','playoffs')
    return dict(compatible=not reasons,reasons=reasons,ordinary_ev_supported=not reasons and (source.get('competition')=='NFL' or nhl),
        limitation='Scope gate only; explicit event binding, reference rederivation, source terms, fees/depth and exceptional outcomes still required')
