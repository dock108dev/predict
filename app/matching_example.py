"""Offline Slice 7 demonstration. Optional --store writes a local mapping snapshot."""
import argparse
import asyncio
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
import json

from app.matching import Matcher, observation, compact_raw
from app.models.core import Event, RawPayload, NativeRef, Venue, EvidenceKind
from app.normalization import Registry, enrich_event
from app.normalization_example import captured_events


def synthetic(native, venue=Venue.SYNTHETIC, *, start='2026-09-13T17:00:00+00:00',
              names=('New York Yankees','Boston Red Sox'), league='MLB', game=None,
              status=None, env='synthetic', roles=()):
    raw = RawPayload(ref=NativeRef(venue=venue,event_id=native),source='synthetic:slice-7',
        received_at=datetime(2026,9,12,tzinfo=timezone.utc),kind=EvidenceKind.SYNTHETIC,
        json_text=json.dumps({'fixture':native,'start':start,'game_number':game,'status':status}))
    event = Event(raw=raw,title='Synthetic event',participants=names,league=league,
                  scheduled_start=datetime.fromisoformat(start) if start else None)
    normalized = enrich_event(event,environment=env)
    if roles:
        normalized = replace(normalized, participants=tuple(replace(p,role=r)
                             for p,r in zip(normalized.participants,roles)))
    return observation(normalized,game_number=game,schedule_status=status,
                       evidence_source='synthetic fixture: start/game_number/status',artifact='synthetic:slice-7')


def synthetic_reports():
    cases = {
        'doubleheader-numbered': [synthetic('g1',game=1),synthetic('g2',game=2),
            synthetic('peer1',Venue.NOVIG,game=1),synthetic('peer2',Venue.NOVIG,game=2)],
        'doubleheader-unknown-game': [synthetic('g1',game=1),synthetic('g2',game=2),
            synthetic('peer',Venue.NOVIG,start=None)],
        'transitive-starts': [synthetic('a'),synthetic('b',Venue.NOVIG,start='2026-09-13T17:10:00+00:00'),
            synthetic('c',Venue.KALSHI,start='2026-09-13T17:20:00+00:00')],
        'role-conflict': [synthetic('a',roles=('home','away')),
                          synthetic('b',Venue.NOVIG,roles=('away','home'))],
        'missing-start': [synthetic('a'),synthetic('b',Venue.NOVIG,start=None)],
        'canceled-recreated': [synthetic('old',status='canceled'),synthetic('new')],
    }
    reports = {}
    for label,rows in cases.items():
        m=Matcher(); m.ingest(rows); reports[label]=m.report()
    m=Matcher(); original=synthetic('rescheduled'); m.ingest([original])
    before=m.snapshot
    updated=synthetic('rescheduled',start='2026-09-15T17:00:00+00:00')
    m.ingest([updated]); conflict=m.snapshot
    m.review_schedule(updated['key'],updated['hash'],reason='Invented postponement correction for test only',
                      actor='synthetic-test',source='synthetic:slice-7-reschedule')
    reports['reschedule']={'before':before,'conflicting_update':conflict,'after_synthetic_review':m.report()}
    return reports


async def report(store=None):
    registry=Registry.load()
    rows=[]
    for event,env,path in await captured_events():
        field={'kalshi':'milestones[].start_date (Sports game, related_event_tickers)',
               'polymarket_us':'events[].startTime','prophetx':'data.sport_events[].scheduled'}[event.raw.ref.venue.value]
        rows.append(observation(enrich_event(event,environment=env,registry=registry),
                                artifact=path,evidence_source=field))
    matcher=Matcher(); matcher.ingest(rows)
    if store:
        matcher.save(store)
        assert Matcher.load(store).report()==matcher.report()
    result=matcher.report()
    coverage=[]
    for scope in sorted({tuple(o['scope']) for o in rows}):
        subset=[o for o in rows if tuple(o['scope'])==scope]
        keys={o['key'] for o in subset}
        mappings=[m for k,m in result['mappings'].items() if k in keys]
        coverage.append({'evidence_kind':scope[0],'environment':scope[1],
            'input_observations':len(subset),'distinct_native_events':len(keys),
            'canonical_events':len({m['canonical_id'] for m in mappings if m['canonical_id']}),
            'outcomes':dict(Counter(m['status'] for m in mappings))})
    return {'scope':'Sporting events only; no market equivalence, settlement or tradability claim.',
            'coverage':coverage,'captured_results':result,'synthetic_results':synthetic_reports()}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store')
    args=parser.parse_args()
    data, raw_payloads = compact_raw(asyncio.run(report(args.store)))
    data['raw_payloads'] = raw_payloads
    print(json.dumps(data,indent=2))
