"""Reviewed NHL winner bindings. Pure local gates; no source discovery or inference.

Annotations are review artifacts, not a parser that guesses terms from titles.
Every annotation must bind the exact native listing and explicit literal evidence.
"""
from datetime import timezone
import json
import re
from app.normalization.registry import Registry
from app.reference.product import time

RULES = 'nhl-full-game-two-way-including-overtime-shootout-v1'
FIELDS = ('overtime','shootout','outcomes','tie','cancellation','postponement','abandonment','forfeit')


def event_key(event):
    if event.get('competition') != 'NHL' or event.get('sport') not in ('hockey','ice_hockey'):
        raise ValueError('NHL competition / sport mismatch')
    season=event.get('season','')
    if not isinstance(season,str) or not re.fullmatch(r'20\d{2}-20\d{2}',season) or int(season[5:])!=int(season[:4])+1:
        raise ValueError('Explicit NHL season YYYY-YYYY required')
    start=time(event['scheduled_start']).astimezone(timezone.utc)
    # Conservative season envelope; no season inferred from a calendar year.
    if not (int(season[:4]),9) <= (start.year,start.month) <= (int(season[5:]),7):
        raise ValueError('NHL start outside declared season')
    if event.get('stage') not in ('regular_season','playoffs'):
        raise ValueError('Explicit NHL regular season / playoffs required')
    mapping=event.get('participants',{});registry=Registry.load()
    if len(mapping)!=2 or len(set(mapping.values()))!=2:
        raise ValueError('Two distinct NHL participants required')
    for name,cid in mapping.items():
        if registry.resolve('team',name,league='NHL').canonical_id!=cid:
            raise ValueError('Unknown, ambiguous or conflicting NHL participant')
        if name=='Utah Hockey Club' and season!='2024-2025':
            raise ValueError('Historical Utah name outside reviewed season')
        if cid=='NHL:UTA' and int(season[:4])<2024:
            raise ValueError('Utah franchise did not exist in declared season')
    if event.get('home') not in mapping.values() or event.get('away') not in mapping.values() or event['home']==event['away']:
        raise ValueError('Explicit home and away NHL identities required')
    return ['NHL',season,event['stage'],start.isoformat(),event['home'],event['away']]


def inventory_gaps(inventory):
    """Reject duplicate native games and conflicting bindings before pairing."""
    gaps={}; seen={}; native={}
    for source,cat in inventory.items():
        for e in cat.get('events',[]):
            if e.get('competition')!='NHL' and e.get('sport') not in ('hockey','ice_hockey'):continue
            key=(source,e['id'])
            try: canonical=event_key(e)
            except (ValueError,KeyError,TypeError,AttributeError) as exc:
                gaps[key]=str(exc);continue
            # Same opponents on the same UTC day must not be silently split by
            # a conflicting start, season, orientation, or duplicate native ID.
            collision=(source,canonical[3][:10],tuple(sorted(e['participants'].values())))
            if key in native or collision in seen:
                gaps[key]='Duplicate or conflicting NHL game'
                gaps[native.get(key,seen.get(collision))]='Duplicate or conflicting NHL game'
            native[key]=key;seen[collision]=key
    # Cross-source same-day candidates must agree exactly. Multiple games on a
    # day need a future explicit double-header discriminator, not nearest time.
    buckets={}
    for source,cat in inventory.items():
        for e in cat.get('events',[]):
            if e.get('competition')!='NHL' or (source,e['id']) in gaps:continue
            k=event_key(e);bucket=(k[3][:10],tuple(sorted(e['participants'].values())))
            buckets.setdefault(bucket,[]).append(((source,e['id']),k))
    for entries in buckets.values():
        if len({json.dumps(k) for _,k in entries})>1:
            for key,_ in entries:gaps[key]='Conflicting NHL season, stage, home/away or start time'
    return gaps


def winner_review(event,market,meta,source,mode):
    event_key(event)
    if market.get('market_type')!='moneyline' or market.get('period')!='full_game' or any(market.get(k) is not None for k in ('line','subject','category','horizon')):
        raise ValueError('NHL supports unlined full-game winner only')
    if market.get('outcome_set')!='two_way' or market.get('rules_revision')!=RULES:
        raise ValueError('NHL regulation / three-way / unknown winner semantics unsupported')
    r=market.get('nhl_review')
    if not r or r.get('source')!=source or r.get('event_id')!=event['id'] or r.get('market_id')!=market['id']:
        raise ValueError('Source-specific NHL native terms review missing')
    if r.get('evidence_mode') not in ('synthetic','observation') or (r['evidence_mode']=='synthetic' and mode!='mock'):
        raise ValueError('Synthetic NHL mapping cannot qualify observations')
    raw=meta['market']['raw'];body=raw['json_text']
    if raw.get('kind')!=r['evidence_mode']:raise ValueError('NHL review evidence mode conflicts with native receipt')
    if r.get('raw_sha256')!=__import__('hashlib').sha256(body.encode()).hexdigest():
        raise ValueError('NHL native terms receipt changed')
    terms=r.get('terms',{});literals=r.get('literals',{})
    if set(terms)!=set(FIELDS) or set(literals)!=set(FIELDS) or any(not isinstance(literals[k],str) or not literals[k] or literals[k] not in body for k in FIELDS):
        raise ValueError('Missing NHL outcome / exceptional settlement evidence')
    if terms['overtime']!='included' or terms['shootout']!=('included' if event['stage']=='regular_season' else 'not_applicable_playoffs') or terms['outcomes']!='two_way':
        raise ValueError('Conflicting NHL overtime / shootout / two-way meaning')
    if any(not isinstance(terms[k],str) or terms[k] in ('','unknown') for k in FIELDS):
        raise ValueError('Unresolved NHL settlement terms')
    sides=market.get('product_outcomes',[])
    if sides!=r.get('outcomes') or len(sides)!=2 or len({s.get('native_id') for s in sides})!=2:
        raise ValueError('NHL native outcome orientation missing or conflicting')
    names={Registry.load().entities[c]['name'] for c in event['participants'].values()}
    winners=[]
    for s in sides:
        if s.get('participant') not in names or s.get('predicate') not in ('win','not_win') or not s.get('native_id'):
            raise ValueError('NHL native outcome participant / predicate unsupported')
        winners.append(next(n for n in names if n!=s['participant']) if s['predicate']=='not_win' else s['participant'])
    if set(winners)!=names:raise ValueError('NHL outcomes do not cover both normal winners')
    native=json.loads(body)
    markets=native.get('markets',[])+[m for e in native.get('events',[]) for m in e.get('markets',[])]
    if source in ('kalshi','polymarket_us'):
        matched=[m for m in markets if str(m.get('ticker' if source=='kalshi' else 'id'))==market['id']]
        if len(matched)!=1:raise ValueError('Missing or duplicate native NHL listing')
        nm=matched[0];registry=Registry.load()
        def name(value):
            resolved=registry.resolve('team',value,league='NHL')
            if resolved.status!='resolved':raise ValueError('Ambiguous native NHL outcome')
            return resolved.canonical_name
        if source=='kalshi':
            expected={('yes',name(nm['yes_sub_title']),'win'),('no',name(nm['yes_sub_title']),'not_win')}
        else:
            ns=nm['marketSides']
            if len(ns)!=2 or {s.get('long') for s in ns}!={True,False} or any(type(s.get('long')) is not bool for s in ns):raise ValueError('Conflicting native NHL Long/Short orientation')
            expected={(str(s['id']),name(s['team']['name']),'win') for s in ns}
            for side in sides:
                original=next(s for s in ns if str(s['id'])==side['native_id'])
                if side.get('native_label')!=('Long' if original['long'] else 'Short'):raise ValueError('NHL Long/Short label conflicts with native side')
        if expected!={(s['native_id'],s['participant'],s['predicate']) for s in sides}:raise ValueError('NHL outcome review conflicts with native listing')
    if r.get('outcome_literal') not in body or not r.get('outcome_literal'):
        raise ValueError('NHL native outcome evidence missing')
    return r


def model_reason(binding,body):
    """Only an annotated, explicit home-win output with established meaning."""
    r=binding.get('nhl_model_review',{});e=r.get('event',{})
    try:
        key=event_key(e)
        i=binding['market_identity']
        if key!=i['event'] or any(i[k]!=e[k] for k in ('season','stage','scheduled_start','competition')):
            return 'Model NHL event, season or start binding conflicts'
        registry=Registry.load()
        if r.get('published_outcome')!='home_win':return 'Explicit published home-win output required'
        for field,cid in [('home_name',e['home']),('away_name',e['away'])]:
            if not r.get(field) or r[field] not in body or registry.resolve('team',r[field],league='NHL').canonical_id!=cid:
                return 'Model home/away names conflict with reviewed NHL event'
        home=registry.entities[e['home']]['name']
        if binding['participant']!=home:return 'Only explicitly published NHL home-win probability supported'
        if i['rules']!=RULES or i['outcome_set']!='two_way':return 'Model NHL outcome meaning does not match two-way full-game winner'
        expected='included' if e['stage']=='regular_season' else 'not_applicable_playoffs'
        if r.get('overtime')!='included' or r.get('shootout')!=expected:return 'Model overtime / shootout meaning unestablished'
        if any(not r.get(k) or r[k] not in body for k in ('home_literal','away_literal','semantics_literal')):
            return 'Model NHL home/away or outcome evidence missing'
    except (KeyError,ValueError,TypeError,AttributeError):return 'Reviewed NHL model event binding missing'
    return None


def assessment(rows,cutoff,game):
    """Reuse settlement profiles without importing football exceptional terms."""
    from app.settlement import profile,fact
    profiles={};sources={};coefficient=None;fee_bases={}
    for venue,review in game.get('nhl_reviews',{}).items():
        eligible=[r for r in rows if r['source']==venue and time(r['observed_at'])<=time(cutoff)]
        if not eligible:continue
        raw=eligible[-1]['market']['raw']
        if __import__('hashlib').sha256(raw['json_text'].encode()).hexdigest()!=review['raw_sha256']:continue
        terms=review['terms'];h=review['raw_sha256']
        source=dict(url=raw['source'],sha256=h,text=json.dumps(terms,sort_keys=True),priority='market-specific',received_at=raw['received_at'])
        # Unknown exceptional payouts remain unknown; a declared NHL sporting
        # winner never establishes a venue's cancellation payout.
        payouts={}
        if terms['tie']=='fraction-0.50':payouts['tie']=dict(kind='fraction',value='0.5',evidence=h)
        profiles[venue]=profile(sources=[source],actor='B5 explicit NHL retained terms review',dimensions={k:fact(v if k!='overtime' else v+'; shootout='+terms['shootout'],evidence=h) for k,v in terms.items() if k not in ('shootout','outcomes')},payouts=payouts)
        sources[venue]=dict(source=source,known_at=eligible[-1]['observed_at'],market_id=raw['ref']['market_id'])
        basis=review.get('fee_basis')
        if basis and basis.get('evidence_literal') and basis['evidence_literal'] in raw['json_text']:
            fee_bases[venue]=basis
            if venue=='polymarket_us':coefficient=basis.get('coefficient')
    return dict(assessed_at=game['assessment_at'],observation_cutoff=cutoff,profiles=profiles,sources=sources,pmus_coefficient=coefficient,nhl_fee_bases=fee_bases,note='Reviewed NHL normal-winner conditional calculation; exceptional probabilities unknown.')
