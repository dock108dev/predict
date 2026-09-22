"""Reviewed MLB winner bindings. Pure local gates; no source discovery or inference.

Annotations are review artifacts, not a parser that guesses terms from titles.
Every annotation must bind the exact native listing and explicit literal evidence.
"""
from datetime import timezone
from hashlib import sha256
import json
import re
from app.normalization.registry import Registry
from app.reference.product import time

RULES = 'mlb-full-game-two-way-including-extra-innings-v1'
FIELDS = ('extra_innings','outcomes','tie','cancellation','postponement','suspension',
          'shortened_game','listed_pitchers','void','refund','forfeit','venue_change','result_corrections')


def event_key(event):
    """Reviewed shared game ID, never title or nearest-start matching."""
    if event.get('competition') != 'MLB' or event.get('sport') != 'baseball':
        raise ValueError('MLB competition / sport mismatch')
    season=event.get('season','')
    if not isinstance(season,str) or not re.fullmatch(r'20\d{2}',season):
        raise ValueError('Explicit MLB season YYYY required')
    start=time(event['scheduled_start']).astimezone(timezone.utc)
    original=time(event['original_start']).astimezone(timezone.utc)
    if start.year!=int(season) or original.year!=int(season):
        raise ValueError('MLB start outside declared season')
    if event.get('stage') not in ('regular_season','playoffs'):
        raise ValueError('Explicit MLB regular season / playoffs required')
    mapping=event.get('participants',{});registry=Registry.load()
    if len(mapping)!=2 or len(set(mapping.values()))!=2:
        raise ValueError('Two distinct MLB participants required')
    for name,cid in mapping.items():
        if registry.resolve('team',name,league='MLB').canonical_id!=cid:
            raise ValueError('Unknown, ambiguous or conflicting MLB participant')
    if event.get('home') not in mapping.values() or event.get('away') not in mapping.values() or event['home']==event['away']:
        raise ValueError('Explicit home and away MLB identities required')
    if not isinstance(event.get('game_id'),str) or not event['game_id'].strip():
        raise ValueError('Reviewed shared MLB game ID required; names alone are insufficient')
    if type(event.get('game_number')) is not int or event['game_number'] not in (1,2):
        raise ValueError('Explicit MLB game number 1 or 2 required')
    if event.get('schedule_status') not in ('scheduled','rescheduled'):
        raise ValueError('Unknown or unsupported MLB game status')
    if (start!=original)!=(event['schedule_status']=='rescheduled'):
        raise ValueError('MLB original start / reschedule conflict')
    return ['MLB',season,event['stage'],start.isoformat(),event['home'],event['away'],
            event['game_id'],event['game_number'],original.isoformat(),event['schedule_status']]


def inventory_gaps(inventory):
    gaps={};buckets={};native={};slots={}
    for source,cat in inventory.items():
        for e in cat.get('events',[]):
            if e.get('competition')!='MLB' and e.get('sport')!='baseball':continue
            key=(source,e['id'])
            try:k=event_key(e)
            except (ValueError,KeyError,TypeError,AttributeError) as exc:
                gaps[key]='MLB identity: '+str(exc);continue
            if key in native:
                gaps[key]='Duplicate native MLB event'
            native[key]=key
            buckets.setdefault(e['game_id'],[]).append((key,k))
            # Same opponents/original UTC date/game number with different IDs
            # are a conflicting binding, not two independent games.
            slot=(k[8][:10],tuple(sorted(e['participants'].values())),e['game_number'])
            slots.setdefault(slot,[]).append((key,k))
    for entries in [*buckets.values(),*slots.values()]:
        if len({json.dumps(k) for _,k in entries})>1 or len({key[0] for key,_ in entries})!=len(entries):
            for key,_ in entries:gaps[key]='Conflicting MLB game ID, number, season, start or reschedule binding'
    return gaps


def winner_review(event,market,meta,source,mode):
    from app.normalization import reviewed_winner
    import sys
    return reviewed_winner.winner_review(sys.modules[__name__],event,market,meta,source,mode)


def model_reason(binding,body):
    """Only an annotated, explicit home-win output with established meaning."""
    r=binding.get('mlb_model_review',{});e=r.get('event',{})
    try:
        key=event_key(e)
        i=binding['market_identity']
        if key!=i['event'] or any(i[k]!=e[k] for k in ('season','stage','competition')) or time(i['scheduled_start'])!=time(e['scheduled_start']):
            return 'Model MLB event, season or start binding conflicts'
        if any(str(e[k]) not in body for k in ('game_id','game_number','scheduled_start')):return 'Model MLB game ID, number or start evidence missing'
        registry=Registry.load()
        if r.get('published_outcome')!='home_win':return 'Explicit published home-win output required'
        for field,cid in [('home_name',e['home']),('away_name',e['away'])]:
            if not r.get(field) or r[field] not in body or registry.resolve('team',r[field],league='MLB').canonical_id!=cid:
                return 'Model home/away names conflict with reviewed MLB event'
        home=registry.entities[e['home']]['name']
        if binding['participant']!=home:return 'Only explicitly published MLB home-win probability supported'
        if i['rules']!=RULES or i['outcome_set']!='two_way':return 'Model MLB outcome meaning does not match two-way full-game winner'
        if r.get('extra_innings')!='included' or r.get('listed_pitchers')!='action':return 'Model extra innings / action meaning unestablished'
        if any(not r.get(k) or r[k] not in body for k in ('home_literal','away_literal','semantics_literal')):
            return 'Model MLB home/away or outcome evidence missing'
    except (KeyError,ValueError,TypeError,AttributeError):return 'Reviewed MLB model event binding missing'
    return None


def assessment(rows,cutoff,game):
    from app.normalization import reviewed_winner
    import sys
    return reviewed_winner.assessment(sys.modules[__name__],rows,cutoff,game)

LEAGUE='MLB'
KEY='mlb'
SERIES='KXMLBGAME'
EVENT_FIELDS=('game_id','game_number','original_start','scheduled_start','home','away','season','stage','schedule_status')
REQUIRED_TERMS={'extra_innings':'included','outcomes':'two_way','listed_pitchers':'action'}
