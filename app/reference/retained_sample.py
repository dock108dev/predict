"""Offline import of the one retained Pinnacle sample into ordinary saved history.

Provider-local identities deliberately cannot masquerade as reviewed venue mappings.
"""
from decimal import Decimal, localcontext
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
from app.reference.product import receipt, pinnacle, validate
from app.reference.pinnacle_sample import ENDPOINT, now, save
from app.collection.transport_session import ObservationJournal, reopen
from app.dashboard.session_history import load, project_rows
from app.dashboard.e6_live import digest


def prepare(folder):
    folder=Path(folder)
    result=json.loads((folder/'result.json').read_text());raw=(folder/'response.bin').read_bytes()
    if result['outcome']!='received' or not result['body_complete'] or sha256(raw).hexdigest()!=result['body_sha256']:
        raise ValueError('Successful complete original response required')
    events=json.loads(raw,parse_float=str)
    if not isinstance(events,list) or len({e['id'] for e in events})!=len(events):raise ValueError('Ambiguous event identity')
    r=receipt(raw.decode(),provider='the_odds_api',url=ENDPOINT,received_at=result['received_at'],mode='observation',headers=result['headers'])
    refs=[];audit=[];missing=[]
    for e in sorted(events,key=lambda e:(e['commence_time'],e['id'])):
        if not e['bookmakers']:
            missing.append(e['id']);continue
        if len(refs)>=16:continue
        if len(e['bookmakers'])!=1 or e['bookmakers'][0].get('title')!='Pinnacle':raise ValueError('Ambiguous bookmaker identity')
        i=dict(version=1,event=['the_odds_api',e['id']],sport='american_football',competition='NFL',season=e['commence_time'][:4],stage=None,
            scheduled_start=e['commence_time'],family='moneyline',period='full_game',line=None,subject=None,outcome_set=None,
            rules='pinnacle-h2h-settlement-unverified',category=None,horizon=None)
        for team in (e['home_team'],e['away_team']):
            b=dict(market_identity=i,participant=team,source_event_id=e['id'],source_participants=[e['home_team'],e['away_team']])
            ref=pinnacle(r,b);validate(ref)
            # Independent rational oracle: other decimal price / sum of prices.
            out=ref['original_value'];prices={o['name']:Fraction(str(o['price'])) for o in out}
            exact=prices[next(t for t in prices if t!=team)]/sum(prices.values())
            with localcontext() as ctx:
                ctx.prec=50
                oracle=Decimal(exact.numerator)/Decimal(exact.denominator)
                error=abs(Decimal(ref['value'])-oracle)
                if error>Decimal('1e-39'):raise ValueError('Independent odds reconciliation failed')
            audit.append(dict(reference_id=ref['id'],event=e['id'],participant=team,original_odds=out,
                exact_fraction=str(exact),probability=ref['value'],absolute_error=str(error),source_at=ref['source_at'],received_at=ref['received_at']))
            refs.append(ref)
    return refs,dict(returned_events=len(events),missing_pinnacle_event_ids=missing,extracted_references=len(refs),oracle=audit,
        mapping='Provider-local identity; prediction-venue event and settlement binding outstanding; no compatible books imported',
        selection='First eight populated events ordered by commence_time then id; two sides each; maximum 16')


def package(folder,refs):
    """New stopped replay package; actual import time, no backdating or network."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False);at=now();sid=folder.name
    spec=dict(mode='real',reference_enabled=False,acquisition='retained-only',prediction_collection=False)
    rows=[dict(type='session_started',source='session',session_id=sid,observed_at=at,spec=spec)]
    rows += [dict(type='product_reference',source='reference',session_id=sid,observed_at=at,reference=r) for r in refs]
    rows.append(dict(type='session_finished',source='session',session_id=sid,observed_at=at,reason='retained import complete'))
    j=ObservationJournal(folder/(sid+'.jsonl'))
    try:
        for row in rows:j.save(row)
    finally:j.close()
    original=project_rows(rows)
    save(folder,'run-spec.json',spec)
    save(folder,'report.json',dict(cleanup_complete=True,outcome=dict(status='complete'),session=sid,reason='retained import complete',prediction_collection=False))
    save(folder,'replay.json',dict(verified=True,references=len(refs),mode='retained-only',cutoff=original['durable_cursor']))
    save(folder,'aggregate-limits.json',dict(reference_limit=16,provider_requests=0))
    names=['run-spec.json','report.json','replay.json','aggregate-limits.json',sid+'.jsonl']
    save(folder,'manifest.json',dict(files={n:digest(folder/n) for n in names},journal_chain=reopen(folder/(sid+'.jsonl'))['sha256']))
    restored=load(folder,through_cursor=original['durable_cursor'])
    if restored['references']!=original['references'] or restored['games']:raise ValueError('Saved reference reopening mismatch')
    return dict(session=sid,cutoff=original['durable_cursor'],reference_ids=[r['id'] for r in restored['references']],saved_state=restored['state'],compatible_prediction_games=0,ev='unavailable: no compatible prediction observations or reviewed settlement mapping')

if __name__=='__main__':
    import sys
    folder=Path(sys.argv[1]);refs,audit=prepare(folder)
    save(folder,'prepared-references.json',refs);save(folder,'original-input-reconciliation.json',audit)
    saved=package(folder/'sessions'/'pinnacle-nfl-retained-20260921',refs)
    save(folder,'saved-reopening.json',saved)
    print(json.dumps(dict(references=len(refs),events=audit['returned_events'],missing=len(audit['missing_pinnacle_event_ids']),saved=saved)))
