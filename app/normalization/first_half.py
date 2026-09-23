"""Shared first-half payout mechanics; competition and source rules remain explicit."""
PERIOD='first_half'
COMPLETION='first_two_quarters_definitively_completed'

def scope(identity):
    return identity.get('competition') in ('NFL','NCAAF','NBA','NCAAB') and identity.get('period')==PERIOD and identity.get('family') in ('moneyline','spread','total')

def series(identity):
    from app.normalization import nfl_first_half,ncaaf_first_half,nba_first_half,ncaab_first_half
    return {'NFL':nfl_first_half,'NCAAF':ncaaf_first_half,'NBA':nba_first_half,'NCAAB':ncaab_first_half}[identity['competition']].SERIES[identity['family']]

def completion(identity):
    if identity.get('competition')=='NCAAB':
        from app.normalization.ncaab_first_half import COMPLETION as college_completion
        return college_completion
    return COMPLETION

def validate_payout(d):
    if d['family']=='moneyline':
        if d.get('line') is not None:raise ValueError('First-half winner must be unlined')
        structure=d.get('winner_structure');sides=d.get('outcomes',[])
        ops={s.get('operator') for s in sides}
        if structure=='binary_team_win_not_win':
            if ops!={'gt','le'} or any(s.get('equality')!='predicate' for s in sides):raise ValueError('Binary winner requires strict team win and complementary not-win including tie')
        elif structure=='two_way_draw_no_bet':
            if ops!={'gt','lt'} or any(s.get('equality')!='stake_refund' for s in sides):raise ValueError('Draw-no-bet requires two strict outcomes with explicit stake refunds')
        elif structure=='three_way_winner_tie':
            if ops!={'gt','eq','lt'} or len(sides)!=3 or any(s.get('equality')!='predicate' for s in sides):raise ValueError('Three-way winner requires explicit home/away/tie native outcomes')
        elif structure=='binary_tie_not_tie':
            if ops!={'eq','ne'} or any(s.get('equality')!='predicate' for s in sides):raise ValueError('Tie strike requires exact tie/not-tie outcomes')
        elif structure=='shared_winner':
            if ops!={'gt','le'} or any(s.get('equality')!='fraction' or s.get('equality_payout')!='0.5' for s in sides):raise ValueError('Reviewed two-team shared winner requires explicit half payout to both binary sides')
        else:raise ValueError('First-half winner structure unknown or unsupported; three-way needs a separately reviewed tie contract')

def score_value(identity,observation):
    """Offline sporting score check, not a venue settlement or result collector."""
    if not scope(identity) or observation.get('period')!=PERIOD or observation.get('complete') is not True:
        raise ValueError('Explicit completed first-half score required')
    if observation.get('event')!=identity['event']:raise ValueError('First-half result event conflict')
    scores=[observation.get(k) for k in ('home','away')]
    if any(type(n) is not int or n<0 for n in scores):raise ValueError('Nonnegative integer first-half scores required')
    return str(scores[0]-scores[1] if identity['rules']['domain']=='home_margin' else sum(scores))
