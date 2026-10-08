"""Observed identity enrichment for manual-comparison-2; no acquisition authority."""
from functools import lru_cache
from copy import deepcopy
import json,re
from app.dashboard.session_projection import stable,stamp
POLICY='manual-comparison-2'
TEAM_KEYS={'NFL':'football_team','NCAAF':'football_team','NCAAB':'basketball_team','NBA':'basketball_team','NHL':'hockey_team','MLB':'baseball_team'}
CALENDARS={'NFL':('2027','2026','https://operations.nfl.com/calendar-events/nfl-important-dates'),
 'NBA':('2027','2026-2027','https://www.nba.com/news/2026-27-nba-regular-season-schedule'),
 'NCAAF':('2027','2026','https://collegefootballplayoff.com/news/2026/1/23/2627-format'),
 'NCAAB':('2027','2026-2027','https://www.ncaa.com/news/basketball-men/article/2026-05-07/how-2027-expanded-ncaa-tournament-and-march-madness-brackets-will-work')}

@lru_cache(maxsize=1)
def _college_registry():
    from .public_contracts import college_registry
    return college_registry()

@lru_cache(maxsize=1)
def repair_registry():
    from pathlib import Path
    from app.normalization.native_registry import native_registry
    from app.normalization.registry import Registry
    p=Path(__file__).resolve().parents[1]/'fixtures/native-admission-identity-v2.json'
    if p.stat().st_size>256*1024:raise ValueError('Retained identity mapping bound')
    extra=json.loads(p.read_text())
    if extra.get('collection_authorized') is not False or extra.get('sha256')!=stable({k:v for k,v in extra.items() if k!='sha256'}):raise ValueError('Retained identity mapping seal conflict')
    data=json.loads(native_registry(live=True).to_json());college=_college_registry()
    present={e['id'] for e in data['entities']};known={(m['league'],m['native_id']):m['target'] for m in data['native_mappings'] if m['kind']=='team' and m['venue']=='kalshi' and m['environment']=='production'}
    for m in extra['mappings']:
        cid=m['target'];key=(m['league'],m['native_id'])
        if cid not in present:
            entity=dict(college.entities[cid]);data['entities'].append(entity);present.add(cid)
            data['aliases'].append(dict(kind='team',league=m['league'],text=entity['name'],targets=[cid],source=entity['source']))
        if key in known:
            if known[key]!=cid:raise ValueError('Retained structured ID conflicts with established identity')
        else:
            data['native_mappings'].append({k:v for k,v in m.items() if k!='evidence'});known[key]=cid
        for proof in m['evidence']:
            if proof['canonical_id']!=cid:raise ValueError('Contradictory retained UUID identity')
            alias=dict(kind='team',league=m['league'],venue='kalshi',text=proof['label'],targets=[cid],source=m['source'])
            from app.normalization.registry import name_key
            existing=[a for a in data['aliases'] if a['kind']=='team' and a.get('league')==m['league'] and a.get('venue')=='kalshi' and name_key(a['text'])==name_key(alias['text'])]
            if not existing:data['aliases'].append(alias)
            elif any(a['targets']!=[cid] for a in existing):raise ValueError('Retained alias conflict')
    data['version']+='+'+extra['version'];return Registry(data)


def resolve_team(team, competition, venue):
    """Exact observed name/native ID; safeName is evidence, never a fuzzy alias."""
    from app.normalization.native_registry import native_registry
    reg=repair_registry()
    resolutions=[reg.resolve('team',team.get(k),league=competition,venue=venue,environment='production',native_id=team.get('id')) for k in ('name','safeName') if team.get(k)]
    # Unmapped IDs may bind by exact names. A mapped ID disagreeing with an
    # unknown display abbreviation needs its exact full name; a known different
    # team is a contradiction.
    known={r.canonical_id for r in resolutions if r.status=='resolved'}
    if any(r.status=='conflicting' and len(r.candidates)>1 for r in resolutions) or len(known)>1:return None
    if len(known)==1:return next(iter(known))
    if competition in ('NCAAF','NCAAB'):
        return college_entrant(team.get('safeName') or team.get('name'),competition)
    return None


@lru_cache(maxsize=1024)
def college_entrant(label, sport):
    if not isinstance(label,str) or not label:return None
    from .public_contracts import college_registry
    from app.normalization.registry import name_key
    reg=_college_registry();direct=reg.resolve('team',label,league=sport)
    if direct.status=='resolved':return direct.canonical_id
    # Enumerated institutional display normalization, with collision rejection
    # over the complete official directory. No abbreviations or ticker decoding.
    matches=set()
    for cid,e in reg.entities.items():
        if e.get('league')!=sport:continue
        names={e['name']}
        if e['name'].startswith('University of '):names.add(e['name'][14:])
        if e['name'].endswith(' University'):names.add(e['name'][:-11])
        # State -> St. is an enumerated institutional display form, checked
        # against every directory entry so abbreviated Saint names stay ambiguous.
        names.update(n.replace(' State',' St.') for n in tuple(names) if ' State' in n)
        if name_key(label) in {name_key(n) for n in names}:matches.add(cid)
    return next(iter(matches)) if len(matches)==1 else None


def enrich_game(event):
    e=deepcopy(event);facts=e.get('observed_identity_facts',[])
    native=e.get('_native') or {}
    if native.get('gameId') is not None:e['source_game_id']=str(native['gameId'])
    e['identity_field_evidence']=dict(native_season=native.get('season'),native_stage=native.get('stage'),native_series_label=native.get('seriesSlug'),native_game_id=native.get('gameId'),native_game_number=native.get('gameNumber'),native_original_start=native.get('originalStartTime'),native_rescheduled_from=native.get('rescheduledFromGameId'),qualification='Source identifiers/labels retained separately; no common MLB occurrence or sport season inferred from locator labels')
    if e.get('source')=='polymarket_us':
        teams=(e.get('_native') or {}).get('teams',[])
        if len(teams)==2:
            mapping={t.get('name'):resolve_team(t,e.get('competition'),'polymarket_us') for t in teams}
            if None not in mapping.values() and len(set(mapping.values()))==2:
                prior=set(e.get('participants',{}).values())-{None}
                if prior and not prior.issubset(set(mapping.values())):e['conflicting_duplicate']=True
                e.update(participants=mapping,identity='resolved')
                if e.get('scheduled_start'):e['canonical_key']=[stamp(e['scheduled_start']).isoformat(),sorted(mapping.values())]

    from app.normalization.native_registry import native_registry
    reg=repair_registry();role_pairs=[]
    for fact in facts:
        roles={role:reg.resolve('team',league=e.get('competition'),venue='kalshi',environment='production',native_id=fact.get(role+'_team_id')).canonical_id for role in ('home','away')}
        if None not in roles.values() and len(set(roles.values()))==2:role_pairs.append(roles)
    unique={stable(r):r for r in role_pairs}
    if len(unique)==1:
        roles=next(iter(unique.values()))
        prior=set(e.get('participants',{}).values())-{None}
        if prior and prior!=set(roles.values()):e['conflicting_duplicate']=True
        e.update(source_participant_roles=roles,home=roles['home'],away=roles['away'],participants={reg.entities[c]['name']:c for c in roles.values()},identity='resolved')
        if e.get('scheduled_start'):e['canonical_key']=[stamp(e['scheduled_start']).isoformat(),sorted(roles.values())]
    elif len(unique)>1:e['conflicting_duplicate']=True
    seasons={str(f['season']['year']) for f in facts if isinstance(f.get('season'),dict) and type(f['season'].get('year')) is int}
    stages={dict(REG='regular_season',PRE='preseason',POST='playoffs').get(f['season'].get('type')) for f in facts if isinstance(f.get('season'),dict)}-{None}
    if len(seasons)==1 and len(stages)==1:
        season=next(iter(seasons));stage=next(iter(stages))
        if any(e.get(k) is not None and e[k]!=v for k,v in [('season',season),('stage',stage)]):e['conflicting_duplicate']=True
        e.update(season=season,stage=stage)
    # Exact retained public crosswalk may name the observed linked main game.
    from .public_contracts import event_identity
    participants=list(e.get('participants',{}).values())
    if len(participants)==2 and None not in participants and e.get('scheduled_start'):
        p=event_identity(source=e.get('source','kalshi'),event_id=e.get('related_game_event_id') or e['id'],competition=e.get('competition'),participants=participants,scheduled_start=e['scheduled_start'],provider_season=e.get('season'),provider_stage=e.get('stage'),provider_label=native.get('seriesSlug'))
        if p.get('enrichment'):
            if p['conflicts']:e['identity_conflicts']=p['conflicts']
            e.update(season=p['enrichment']['season'],stage=p['enrichment']['stage'],public_identity=p)
    return e

def award(event,market,venue):
    n=market.get('_native') or market.get('native_metadata') or {};scope=market.get('native_scope_binding') or {}
    r=dict(version=POLICY,source=venue,event_id=market['event_id'],market_id=market['id'],native_metadata_sha256=stable(n),predicate=None,identity=None,blockers=[],net=None,ev=None,collection_authorized=False,settlement=dict(status='UNKNOWN',terms=deepcopy(market.get('terms',{})),reason='Raw award correspondence does not qualify payout, field revisions or exceptional settlement'))
    def block(reason):r['blockers'].append(reason)
    sport=scope.get('sport');category=scope.get('category');conference=scope.get('conference_id')
    label=n.get('yes_sub_title');text=n.get('rules_primary','')
    match=None
    if isinstance(label,str):
        prefixes=[f'If {label} wins the ',f'If {label} win the ',f'If the {label} win the ',f'If {label} is the ',f"If the {label} men's college basketball team are the " ]
        suffix=', then the market resolves to Yes.'
        for prefix in prefixes:
            if text.startswith(prefix) and text.endswith(suffix):match=(label,text[len(prefix):-len(suffix)]);break
    if venue!='kalshi' or sport not in TEAM_KEYS or not match or n.get('strike_type')!='structured' or match[0]!=n.get('yes_sub_title'):
        block('Unsupported exact award predicate')
    else:
        label,declared=match;native_id=(n.get('custom_strike') or {}).get(TEAM_KEYS[sport])
        from app.normalization.native_registry import native_registry
        resolved=repair_registry().resolve('team',label,league=sport,venue=venue,environment='production',native_id=native_id)
        entrant=resolved.canonical_id if native_id and resolved.status=='resolved' else None
        if not entrant and native_id and resolved.status!='conflicting':
            named=repair_registry().resolve('team',label,league=sport,venue=venue)
            if named.status=='resolved':entrant=named.canonical_id
        # A recognized structured ID conflicting with the literal label remains blocked.
        if not entrant and sport=='NBA' and label in ('Los Angeles C','Los Angeles L'):
            name={'Los Angeles C':'Los Angeles Clippers','Los Angeles L':'Los Angeles Lakers'}[label]
            exact=repair_registry().resolve('team',name,league=sport,venue=venue,environment='production',native_id=native_id)
            if exact.status=='resolved':entrant=exact.canonical_id
        if not entrant and resolved.status!='conflicting' and sport in ('NCAAF','NCAAB'):
            entrant=college_entrant(label,sport)
        if not entrant:block('Exact canonical award entrant unavailable')
        # Explicit dated award literals and typed, documented source contract.
        from .public_contracts import contract,load
        try:row,doc=contract(scope)
        except (ValueError,KeyError):row=doc=None;block('Supported source award contract unavailable')
        year=re.search(r'\b(20\d\d)(?:-(20\d\d|\d\d))?\b',declared);season=None;calendar=None
        horizon=(event.get('_native') or {}).get('sub_title','')
        if year is None:year=re.fullmatch(r'(20\d\d)(?:-(20\d\d|\d\d))?',horizon)
        if year:
            if year[2]:
                end=int(year[2])+(2000 if len(year[2])==2 else 0)
                if end==int(year[1])+1:
                    season=year[1] if sport in ('NFL','NCAAF') else year[1]+'-'+str(end)
                    if sport in CALENDARS:calendar=CALENDARS[sport][2]
            elif sport=='MLB' or sport=='NCAAF' and category=='conference_champion':season=year[1]
            elif sport in CALENDARS and year[1]==CALENDARS[sport][0]:_,season,calendar=CALENDARS[sport]
        if season is None:block('Exact source-award season association unavailable')
        # Typed contract plus literal named award, never calendar alone.
        words={'NFL':('Pro Football Championship','AFC','NFC'),'NBA':('Pro Basketball Finals','Eastern Conference','Western Conference'),'NHL':('Stanley Cup','Eastern Conference','Western Conference'),'MLB':('World Series','Pro Baseball Championship','American League','National League'),'NCAAF':('College Football','American','AAC'),'NCAAB':('College Basketball','Atlantic 10')}
        patterns={('NFL',None):r'20\d\d Pro Football Championship',('NFL','AFC'):r'Pro Football AFC Championship',('NFL','NFC'):r'Pro Football NFC Championship',
          ('NBA',None):r'20\d\d Pro Basketball Finals',('NBA','EAST'):r'Pro Basketball Eastern Conference Finals in the 20\d\d-\d\d season',('NBA','WEST'):r'Pro Basketball Western Conference Finals in the 20\d\d-\d\d season',
          ('MLB',None):r'20\d\d Pro Baseball Championship',('MLB','AL'):r'20\d\d Pro Baseball American League Championship',('MLB','NL'):r'20\d\d Pro Baseball National League Championship',
          ('NHL',None):r'20\d\d-\d\d Stanley Cup® Finals',('NHL','EAST'):r'20\d\d-\d\d NHL Eastern Conference Finals',('NHL','WEST'):r'20\d\d-\d\d NHL Western Conference Finals',
          ('NCAAF',None):r'College Football Playoff National Championship Game',('NCAAF','AAC'):r'20\d\d College Football American Athletic Conference Championship Game',
          ('NCAAB',None):r"20\d\d-\d\d Division 1 Men's College Basketball National Champion",('NCAAB','ATLANTIC_10'):r'20\d\d Atlantic 10 conference tournament champions'}
        if not re.fullmatch(patterns.get((sport,conference),r'(?!)'),declared):block('Unsupported exact named award/category predicate')
        conf_words={'AFC':'AFC','NFC':'NFC','EAST':'Eastern Conference','WEST':'Western Conference','AL':'American League','NL':'National League','AAC':'American Athletic Conference','ATLANTIC_10':'Atlantic 10'}
        if conference and conf_words.get(conference,'__unsupported__') not in declared:block('Award literal conflicts with typed conference')
        if not conference and any(w in declared for w in ('AFC','NFC','Eastern Conference','Western Conference','American League','National League','American Athletic Conference','Atlantic 10')):block('Conference literal conflicts with league award category')
        # A source subtitle and explicit rule year may not select different horizons.
        if year and horizon and re.fullmatch(r'20\d\d-\d\d',horizon):
            first=int(horizon[:4]);last=2000+int(horizon[-2:])
            if year[2] and int(year[1])!=first or not year[2] and int(year[1]) not in (first,last):block('Explicit source award horizon conflict')
        if category not in ('league_champion','conference_champion') or (category=='conference_champion')!=bool(conference):block('Exact league/conference category unavailable')
        # Existing exact field association is useful but never required merely
        # to compare a single entrant. Check explicit current membership only.
        field=load()['fields'].get('AAC' if sport=='NCAAF' and category=='conference_champion' else sport,{})
        if entrant and field.get('season')==season:
            members=field.get('conferences',{}).get(conference,field.get('members',[])) if conference else field.get('members',[])
            members=[m['id'] if isinstance(m,dict) else m for m in members]
            if members and entrant not in members:block('Entrant conflicts with documented award membership')
        deadline=n.get('expected_expiration_time') or n.get('close_time')
        try:stamp(deadline)
        except (ValueError,TypeError,AttributeError):deadline=None
        r['identity']=dict(competition=sport,season=season,stage='championship',period='season',family='futures',category=category,conference_id=conference,award=declared,event=[sport,season,category,conference,declared],scheduled_start=deadline,line=None)
        r['predicate']=['wins_award',entrant]
        r['award_binding']=dict(season=season,participant=entrant,field=None,association=dict(expected_expiration_time=deadline),predicate=dict(source_award=declared),contract_provenance=doc,calendar_source=calendar,qualification='Exact entrant predicate; no exhaustive field or payout claim')
    if market.get('conflicting_duplicate') or event.get('conflicting_duplicate'):block('Conflicting duplicate native identity')
    r['status']='IDENTITY_BLOCKED' if r['blockers'] else 'BOUND_RAW_PREDICATE';r['sha256']=stable(r);return r


def duplicate_identity_conflicts(old,new,*,event):
    """Only identity admission: unknown terms still need separate review."""
    fields=('id','gameId','startTime','rescheduledFromGameId','season','stage') if event else ('id','slug','question','description','sportsMarketType','sportsMarketTypeV2','marketType','gameStartTime','endDate','assetPriceTerms')
    conflicts=[k for k in fields if k in old and k in new and old[k]!=new[k]]
    def sides(value):
        return sorted((str(s.get('id')),s.get('long'),str(s.get('teamId')),str((s.get('team') or {}).get('id')),(s.get('team') or {}).get('name'),(s.get('team') or {}).get('league'),(s.get('team') or {}).get('ordering')) for s in value.get('marketSides',[]))
    if not event and sides(old)!=sides(new):conflicts.append('marketSides')
    if event:
        # Expanded detail can include ancillary teams; main-game binding must
        # agree through exact embedded winner side IDs and names.
        from app.adapters.polymarket_us import event_game_binding
        league=next((t.get('league') for t in old.get('teams',[]) if t.get('league')),None)
        try:
            a=event_game_binding(old,league,live_bindings=True)['teams'];b=event_game_binding(new,league,live_bindings=True)['teams']
            key=lambda ts:sorted((str(t.get('id')),t.get('name'),t.get('league')) for t in ts)
            if key(a)!=key(b):conflicts.append('main_game_teams')
        except ValueError:conflicts.append('ambiguous_main_game')
    return conflicts


def share_games(target,other):
    """Share observed season/stage only for exact schedule and two participants."""
    facts={}
    for raw in other['events']:
        e=enrich_game(dict(raw,source='kalshi'))
        if e.get('identity')=='resolved' and e.get('season') and e.get('stage') and not e.get('conflicting_duplicate') and e.get('canonical_key') and len(e.get('participants',{}))==2:
            key=stable([e.get('competition'),e['canonical_key']]);facts.setdefault(key,[]).append(e)
    for raw in target['events']:
        e=enrich_game(dict(raw,source='polymarket_us'));raw.update(e)
        key=stable([e.get('competition'),e.get('canonical_key')]);matches=facts.get(key,[])
        if matches and len({(m['season'],m['stage']) for m in matches})==1:
            m=matches[0]
            if any(e.get(k) is not None and e[k]!=m[k] for k in ('season','stage')):raw['conflicting_duplicate']=True
            raw.update(source_participant_roles=deepcopy(m.get('source_participant_roles',{})),season=m['season'],stage=m['stage'],shared_identity_provenance=dict(source='kalshi',event_ids=sorted(x['id'] for x in matches),facts=deepcopy(m.get('observed_identity_facts',[])),qualification='Exact two-participant schedule correspondence; no MLB occurrence inferred'))

def us_score(native,locator,event):
    """Observed retail signed line + literal period + native side orientation."""
    from decimal import Decimal,InvalidOperation
    family=locator.get('family');period=locator.get('period');sport=event.get('competition')
    if family not in ('moneyline','spread','total') or sport not in ('NFL','NCAAF') or period not in ('full_game','first_half'):return None
    sides=native.get('marketSides',[]);text=native.get('description','')
    if len(sides)!=2 or {s.get('long') for s in sides}!={True,False} or any(str(s.get('marketId'))!=str(native.get('id')) for s in sides):return None
    if (period=='first_half') != ('in the first half of ' in text):return None
    try:line=Decimal('0') if family=='moneyline' else Decimal(str(native.get('line')))
    except InvalidOperation:return None
    # Integer strikes need exact equality/push semantics absent in these records.
    if not line.is_finite() or abs(line)>10000 or family!='moneyline' and line%1 not in (Decimal('.5'),Decimal('-.5')):return None
    long=next(s for s in sides if s['long']);short=next(s for s in sides if not s['long'])
    if family=='moneyline':
        if period!='first_half' or long.get('description')!='Yes' or short.get('description')!='No':return None
        match=re.match(r'^1st Half Winner settles Yes if (.+?) outscores (.+?) in the first half of ',text)
        tied=text.startswith('1st Half Winner settles Yes if both teams score the same number of points in the first half of ')
        if tied:
            if any(s.get('teamId') for s in sides):return None
            participant='tie'
        elif match:
            participant=resolve_team(long.get('team') or {},sport,'polymarket_us')
            if participant is None or resolve_team(short.get('team') or {},sport,'polymarket_us')!=participant:return None
            names=[college_entrant(match[k],sport) for k in (1,2)]
            if names[0]!=participant or set(names)!=set(event.get('participants',{}).values()):return None
        else:return None
    elif family=='spread':
        participant=resolve_team(long.get('team') or {},sport,'polymarket_us')
        other=resolve_team(short.get('team') or {},sport,'polymarket_us')
        if participant is None or other is None or {participant,other}!=set(event.get('participants',{}).values()):return None
        label=(long.get('team') or {}).get('name')
        match=re.search(r'^This market will settle to Yes if '+re.escape(label)+r' covers a ([+-]\d+(?:\.\d+)?) point spread in ',text)
        try:valid=match and Decimal(match[1])==line and Decimal(long['description'])==line and Decimal(short['description'])==-line
        except (InvalidOperation,KeyError):return None
        if not valid:return None
    else:
        participant='combined'
        if locator.get('total_scope') not in ('combined','game','requires_contract_scope'):return None
        match=re.search(r' combine for (?:more than|over) (\d+(?:\.\d+)?) points in ',text)
        labels=re.search(r'(?:settles Over if|settle to Yes if) (.+?) and (.+?) combine for ',text)
        if not labels:return None
        names=[resolve_team(dict(name=labels[k]),sport,'polymarket_us') for k in (1,2)]
        if set(names)!=set(event.get('participants',{}).values()) or None in names:return None
        if not match or Decimal(match[1])!=line or long.get('description')!='Over' or short.get('description')!='Under':return None
    return dict(policy=POLICY,status='EXPLICIT_PREDICATE_ONLY',competition=sport,period=period,family=family,participant=participant,line=format(line,'f'),unit='points',native_metadata_sha256=stable(native),rules_primary=text,outcomes=[dict(native_id=str(long['id']),operator='eq' if participant=='tie' else 'gt'),dict(native_id=str(short['id']),operator='ne' if participant=='tie' else 'le')],qualification='Half-integer literal threshold; exceptional settlement remains unavailable')
