"""Exact V1 identity keys, independent of exhaustive payout state tables."""
from app.reference.product import time


def baseball(event):
    """Explicit original occurrence plus numbered/rescheduled current occurrence."""
    if event.get('competition')!='MLB' or not isinstance(event.get('season'),str) or not event['season'] or not event.get('stage'):
        raise ValueError('Exact MLB season/stage required')
    if not isinstance(event.get('game_id'),str) or not event['game_id'] or type(event.get('game_number')) is not int or not 1<=event['game_number']<=2:
        raise ValueError('Exact MLB game ID and single/doubleheader game number required')
    if event.get('schedule_status') not in ('original','rescheduled'):
        raise ValueError('Original versus rescheduled occurrence required')
    original=time(event['original_start']);current=time(event['scheduled_start'])
    if event['schedule_status']=='original' and original!=current:
        raise ValueError('Original MLB occurrence has conflicting schedule')
    if not event.get('home') or not event.get('away') or event['home']==event['away']:
        raise ValueError('Exact MLB home/away participants required')
    return (event['season'],event['stage'],event['game_id'],event['game_number'],original.isoformat(),current.isoformat(),event['schedule_status'],event['home'],event['away'])


def award(event,entrant):
    """A selected entrant predicate needs the award identity, not all cashflows."""
    if event.get('category') not in ('league_champion','conference_champion') or event.get('stage')!='championship':
        raise ValueError('Exact championship category/stage required')
    for k in ('competition','season','award_id'):
        if not isinstance(event.get(k),str) or not event[k]:raise ValueError('Exact championship '+k+' required')
    conference=event.get('conference_id')
    if (event['category']=='conference_champion') != (isinstance(conference,str) and bool(conference)):
        raise ValueError('Exact league/conference award scope required')
    if not isinstance(entrant,str) or not entrant.startswith(event['competition']+':'):
        raise ValueError('Exact canonical entrant required')
    return (event['competition'],event['season'],event['category'],conference,event['award_id'],entrant)
