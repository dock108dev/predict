"""Explicit evidenced Kalshi score predicates, independent of payout qualification.

Series locates the cell. Both structured strike and primary rule must agree.
Missing completion, stage, pitcher/action and payout facts remain engine gates.
"""
from decimal import Decimal
import re
from app.dashboard.session_projection import stable

POLICY='native-score-predicate-1'

def bind(native, binding, *, revised=False):
    sport,period,family=(binding[k] for k in ('sport','period','family'))
    if family=='futures':return championship(native,binding)
    if family not in ('moneyline','spread','total') or sport not in (('NFL','MLB','NCAAF','NBA','NHL') if revised else ('NFL','MLB')):
        return None
    if period not in ({'full_game','first_half'} if sport in ('NFL','NCAAF','NBA') else {'full_game','first_3','first_5'} if sport=='MLB' and revised else {'first_3','first_5'} if sport=='MLB' else {'full_game'}):
        return None
    text=native.get('rules_primary')
    if family=='moneyline' and period!='full_game':
        return winner(native,binding,text,revised=revised)
    if not isinstance(text,str) or native.get('strike_type')!='greater' or native.get('cap_strike') is not None:
        return None
    strike=native.get('floor_strike')
    if isinstance(strike,bool) or strike is None:return None
    threshold=Decimal(str(strike))
    if not threshold.is_finite() or abs(threshold)>10000 or threshold*2!=(threshold*2).to_integral_value():return None
    unit='runs' if sport=='MLB' else 'goals' if sport=='NHL' else 'points'
    phrase=('wins by more than ' if family=='spread' else 'collectively score more than ')
    literal=re.escape(phrase)
    if revised:literal=r'wins by (?:more than|over) ' if family=='spread' else r'collectively score more (?:than )?'
    match=re.search(literal+r'(-?\d+(?:\.\d+)?) '+unit+r' in ',text)
    if not match or Decimal(match[1])!=threshold:return None
    segment='in the 1st half of ' if period=='first_half' else 'in the first '+period.split('_')[1]+' innings of ' if period in ('first_3','first_5') else None
    if not revised and period=='first_3':segment=None
    if segment and segment not in text:return None
    if not segment and re.search(r'(?:1st half|first \d+ innings)',text):return None
    if not text.startswith('If ') or not text.endswith(', then the market resolves to Yes.'):return None
    participant='combined';native_team=None
    if family=='spread':
        key={'NFL':'football_team','NCAAF':'football_team','NBA':'basketball_team','MLB':'baseball_team','NHL':'hockey_team'}[sport]
        native_team=(native.get('custom_strike') or {}).get(key)
        if not isinstance(native_team,str):return None
        from app.normalization.native_registry import native_registry
        from .admission_enrichment import repair_registry
        registry=repair_registry() if revised else native_registry(live=True)
        resolution=registry.resolve('team',league=sport,venue='kalshi',environment='production',native_id=native_team)
        if resolution.status!='resolved':return None
        participant=resolution.canonical_id
        named=re.split(r' wins by (?:more than|over) ',text[3:],maxsplit=1)[0] if revised else text[3:text.index(' wins by more than ')]
        if revised:
            exact=registry.resolve('team',named,league=sport,venue='kalshi',environment='production',native_id=native_team)
            if exact.status!='resolved' or exact.canonical_id!=participant:return None
        if not str(native.get('yes_sub_title','')).startswith(named+' wins by over '):return None
    line=format(-threshold if family=='spread' else threshold,'f')
    return dict(policy=POLICY,status='EXPLICIT_PREDICATE_ONLY',competition=sport,
        period=period,family=family,participant=participant,native_team_id=native_team,
        line=line,unit=unit,source_threshold=format(threshold,'f'),native_metadata_sha256=stable(native),
        rules_primary=text,outcomes=[dict(native_id='yes',operator='gt'),dict(native_id='no',operator='le')],
        missing=['Exact shared event/season/stage and home/away review',
                 'Effective completion, exceptional payout, amendments and correction terms',
                 'Pitcher/action and reschedule conditions' if sport=='MLB' else 'Applicable overtime or explicit completed first-half scope',
                 'Effective fees, rounding/units and mandatory charges'],
        qualification='Predicate bound; source descriptor/settlement review remains incomplete')

def winner(native,binding,text,*,revised=False):
    if not isinstance(text,str) or native.get('strike_type')!='structured' or not text.endswith(', then the market resolves to Yes.'):
        return None
    sport,period=binding['sport'],binding['period']
    phrase='the 1st Half of ' if period=='first_half' else 'the first '+period.split('_')[1]+' innings of '
    if revised and period=='first_half':phrase='the 1st [Hh]alf of '
    match=re.match(r'If (.+?) (wins |tie in )'+(phrase if revised and period=='first_half' else re.escape(phrase)),text)
    if match is None:return None
    tied=' tie in '+phrase in text or (match[1]=='neither team' and native.get('yes_sub_title')=='Tie')
    label=native.get('yes_sub_title');key={'NFL':'football_team','NCAAF':'football_team','NBA':'basketball_team','MLB':'baseball_team','NHL':'hockey_team'}[sport]
    native_team=(native.get('custom_strike') or {}).get(key)
    if revised:
        if period=='first_half':
            if label=='Tie 1st Half':label='Tie'
            elif isinstance(label,str) and label.endswith(' wins 1st Half'):label=label[:-len(' wins 1st Half')]
        tied=tied or match[1]=='neither team' and label=='Tie'
    participant=None
    if tied:
        if label!='Tie':return None
        participant='tie'
    else:
        if match[1]!=label or not isinstance(native_team,str):return None
        from app.normalization.native_registry import native_registry
        from .admission_enrichment import repair_registry
        registry=repair_registry() if revised else native_registry(live=True)
        resolved=registry.resolve('team',label,league=sport,venue='kalshi',environment='production',native_id=native_team)
        if resolved.status=='resolved':participant=resolved.canonical_id
    return dict(policy=POLICY,status='EXPLICIT_PREDICATE_ONLY',competition=sport,period=period,
        family='moneyline',participant=participant,native_team_id=native_team,line='0',unit='runs' if sport=='MLB' else 'goals' if sport=='NHL' else 'points',
        source_threshold='0',native_metadata_sha256=stable(native),rules_primary=text,
        outcomes=[dict(native_id='yes',operator='eq' if tied else 'gt'),dict(native_id='no',operator='ne' if tied else 'le')],
        missing=['Exact canonical role/season/stage and shared event review','Effective completed segment boundaries and exceptions',
                 'Source payout, equality, void/refund and fee treatment'],
        qualification='Explicit binary winner/tie predicate; source descriptor/settlement review remains incomplete')

def normalize(event,fact,descriptor):
    """Use the existing engine only when independently supplied facts close gates."""
    from app.normalization.score_lines import orient_descriptor
    for key in ('period','family','participant','line','unit'):
        if descriptor.get(key)!=fact[key]:raise ValueError('Native predicate descriptor conflict: '+key)
    if {s['native_id']:s['operator'] for s in descriptor.get('outcomes',[])}!={s['native_id']:s['operator'] for s in fact['outcomes']}:
        raise ValueError('Native predicate outcome conflict')
    return orient_descriptor(event,descriptor)

def championship(native,binding):
    text=native.get('rules_primary');label=native.get('yes_sub_title')
    if not isinstance(text,str) or not isinstance(label,str) or native.get('strike_type')!='structured':return None
    match=re.fullmatch(r'If (.+?) wins the (.+?), then the market resolves to Yes\.',text)
    if not match or match[1]!=label or not (native.get('custom_strike') or {}).get('football_team'):return None
    award=match[2];year=re.search(r'\b(20\d\d)\b',award)
    from app.normalization.native_registry import native_registry
    resolved=native_registry(live=True).resolve('team',label,league=binding['sport'],venue='kalshi',environment='production',native_id=native['custom_strike']['football_team'])
    # Calendar-year championship labels do not imply an NFL sport season.
    season=year[1] if year and binding['sport']=='NCAAF' and binding['category']=='conference_champion' else None
    return dict(policy=POLICY,status='EXPLICIT_PREDICATE_ONLY',competition=binding['sport'],period='season',family='futures',
        category=binding['category'],source_award=award,source_award_calendar_year=year[1] if year else None,
        season=season,conference_id=binding.get('conference_id'),participant=resolved.canonical_id if resolved.status=='resolved' else None,
        native_team_id=native['custom_strike']['football_team'],native_metadata_sha256=stable(native),rules_primary=text,
        outcomes=[dict(native_id='yes',predicate='wins_declared_award'),dict(native_id='no',predicate='does_not_win_declared_award')],
        missing=['Exact sport season and authoritative award identity where not explicit','Complete entrant field and current membership/revision',
                 'No-award/shared-winner/fractional payout and cancellation treatment','Effective fees and authoritative resolution/correction records'],
        qualification='Literal source award predicate bound; championship engine identity and payouts remain incomplete')
