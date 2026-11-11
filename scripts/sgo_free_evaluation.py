"""Offline, experimental comparison of saved SGO and Predict observations.

Only exact-name NBA full-game moneylines are joined; no network or production writes.
The vendor consensus has no observed source clock and is explicitly indicative.
"""
import argparse
from datetime import datetime
from fractions import Fraction
import json
from pathlib import Path
from statistics import median

MAX_AGE = 1800

def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))

def american(value):
    n = int(value)
    if abs(n) < 100:
        raise ValueError('invalid American odds')
    return Fraction(100, n + 100) if n > 0 else Fraction(-n, -n + 100)

def pair_probability(a, b):
    x, y = american(a), american(b)
    return x / (x + y)

def eligible_pair(a, b, at, *, market='ml', line=None):
    if not a or not b or a.get('available') is not True or b.get('available') is not True:
        return None, 'missing or unavailable side'
    try:
        for q in (a, b):
            age = (at - instant(q['lastUpdatedAt'])).total_seconds()
            if age < 0 or age > MAX_AGE:
                return None, 'stale or future side'
        if market != 'ml':
            field = 'spread' if market == 'sp' else 'overUnder'
            la, lb = Fraction(a[field]), Fraction(b[field])
            if la != Fraction(line) or (lb != -la if market == 'sp' else lb != la):
                return None, 'different line'
        return pair_probability(a['odds'], b['odds']), None
    except (KeyError, ValueError, TypeError, ZeroDivisionError):
        return None, 'missing or invalid price, line or clock'

def compatible_sides(odd, opposite, market):
    return (odd.get('periodID') == opposite.get('periodID') == 'game'
            and odd.get('betTypeID') == opposite.get('betTypeID') == market
            and odd.get('statID') == opposite.get('statID') == 'points'
            and odd.get('opposingOddID') == opposite.get('oddID')
            and opposite.get('opposingOddID') == odd.get('oddID')
            and odd.get('oddID') is not None)

def estimate(odd, opposite, at, *, market='ml', line=None, exclude=None):
    books = {}
    exclusions = {}
    a, b = odd.get('byBookmaker', {}), opposite.get('byBookmaker', {})
    for name in sorted(set(a) | set(b)):
        if name == exclude:
            exclusions[name] = 'evaluated venue excluded'
            continue
        probability, reason = eligible_pair(a.get(name), b.get(name), at, market=market, line=line)
        if reason: exclusions[name] = reason
        else: books[name] = {'probability': float(probability), 'selected': a[name], 'opposite': b[name]}
    return books, exclusions, float(median([v['probability'] for v in books.values()])) if books else None

def analyze(sgo, predict):
    at = instant(sgo['received_at'])
    rows = []
    for event in sgo['response']['data']:
        if event['leagueID'] != 'NBA' or event['status']['live'] or event['status']['started']:
            continue
        home = event['teams']['home']['names']['long']; away = event['teams']['away']['names']['long']
        title = f'{away} at {home}'
        for side, name in [('home',home),('away',away)]:
            odd = event['odds'].get(f'points-{side}-game-ml-{side}', {})
            other = 'away' if side == 'home' else 'home'
            opposite = event['odds'].get(f'points-{other}-game-ml-{other}', {})
            if not compatible_sides(odd, opposite, 'ml'): continue
            books, excluded, med = estimate(odd, opposite, at)
            candidates = [g for g in predict['rows'] if g['league']=='NBA' and g['game_title']==title and instant(g['start_at'])==instant(event['status']['startsAt']) and g['market']=={'line':None,'market':'winner','period':'full_game'} and g['outcome_key'][4:] == ['win',None,'normal_win']]
            quote = next((q for g in candidates for q in g['quotes'] if q.get('participant_label') == name and q.get('reference') and q.get('reference_calculation',{}).get('available')), None)
            ref = quote['reference'] if quote else None
            if ref and (ref['bookmaker'] != 'pinnacle' or any(not t or not 0 <= (at-instant(t)).total_seconds() <= MAX_AGE for t in ref['source_at'])): ref=None
            pin = float((1/Fraction(ref['odds'][ref['selected']])) / sum(1/Fraction(o) for o in ref['odds'])) if ref else None
            fair = float(american(odd['fairOdds'])) if odd.get('fairOddsAvailable') and odd.get('fairOdds') else None
            rows.append({'event':title,'event_id':event['eventID'],'start_at':event['status']['startsAt'],'side':name,'sgo_received_at':sgo['received_at'],'pinnacle':pin,'pinnacle_reference':ref,'sgo_fair_indicative':fair,'sgo_fair_source_at':None,'books':books,'excluded':excluded,'median':med,'offer':{'venue':quote.get('venue'),'original':quote.get('original'),'cost_per_normal_claim':quote.get('cost_per_normal_claim')} if ref else None})
    return rows

def analyze_lines(sgo, predict):
    at = instant(sgo['received_at'])
    rows = []
    for event in sgo['response']['data']:
        if event['leagueID'] != 'NBA' or event['status']['live'] or event['status']['started']:
            continue
        home = event['teams']['home']['names']['long']; away = event['teams']['away']['names']['long']
        title = f'{away} at {home}'
        for group in predict['rows']:
            market = group['market']['market']
            if (group['league'] != 'NBA' or group['game_title'] != title or
                instant(group['start_at']) != instant(event['status']['startsAt']) or
                group['market']['period'] != 'full_game' or market not in ('spread', 'total') or
                group['outcome_key'][6] != 'normal_win'):
                continue
            predicate = group['outcome_key'][4]
            if market == 'total':
                if predicate not in ('over', 'under'): continue
                side = predicate; other = 'under' if side == 'over' else 'over'; typ = 'ou'
                oid = f'points-all-game-ou-{side}'; otherid = f'points-all-game-ou-{other}'
            else:
                if predicate != 'cover': continue
                label = next((q.get('participant_label') for q in group['quotes'] if q.get('participant_label') in (home, away)), None)
                if not label: continue
                side = 'home' if label == home else 'away'; other = 'away' if side == 'home' else 'home'; typ = 'sp'
                oid = f'points-{side}-game-sp-{side}'; otherid = f'points-{other}-game-sp-{other}'
            line = Fraction(group['outcome_key'][5])
            odd = event['odds'].get(oid, {}); opposite = event['odds'].get(otherid, {})
            if not compatible_sides(odd, opposite, typ): continue
            books, excluded, med = estimate(odd, opposite, at, market=typ, line=line)
            quote = next((q for q in group['quotes'] if q.get('reference') and q.get('reference_calculation',{}).get('available')), None)
            ref = quote['reference'] if quote else None
            if ref and (ref['bookmaker'] != 'pinnacle' or any(not t or not 0 <= (at-instant(t)).total_seconds() <= MAX_AGE for t in ref['source_at'])): ref=None
            pin = float((1/Fraction(ref['odds'][ref['selected']])) / sum(1/Fraction(o) for o in ref['odds'])) if ref else None
            fairfield = 'fairSpread' if typ == 'sp' else 'fairOverUnder'
            try:
                fair = float(american(odd['fairOdds'])) if odd.get('fairOddsAvailable') and Fraction(odd[fairfield]) == line else None
            except (KeyError, ValueError, TypeError, ZeroDivisionError): fair = None
            rows.append({'event':title,'event_id':event['eventID'],'market':market,'side':side,'line':str(line),'sgo_received_at':sgo['received_at'],'pinnacle':pin,'pinnacle_reference':ref,'sgo_fair_indicative':fair,'vendor_fair_line':odd.get(fairfield),'sgo_fair_source_at':None,'books':books,'excluded':excluded,'median':med,'offer':{'venue':quote.get('venue'),'cost_per_normal_claim':quote.get('cost_per_normal_claim')} if ref else None})
    return rows

def main():
    parser=argparse.ArgumentParser();parser.add_argument('sgo',type=Path);parser.add_argument('predict',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    sgo=json.loads(args.sgo.read_text()); predict=json.loads(args.predict.read_text())
    result=analyze(sgo,predict) + analyze_lines(sgo,predict)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(f'{len(result)} NBA outcome observations examined; {sum(r["pinnacle"] is not None and r["median"] is not None for r in result)} with Pinnacle and eligible book median')
if __name__=='__main__': main()
