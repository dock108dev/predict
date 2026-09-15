"""Bounded preserved production replay. No network or account access.

Rule assessments are pinned to exact reviewed listing-text hashes. New text starts
unknown; current general rules are context, not retroactive listing amendments.
"""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from app.adapters.kalshi import Response as KR, parse_market as parse_k
from app.adapters.polymarket_us import Response as PR, parse_market as parse_p
from app.models.core import EvidenceKind
from app.matching import Matcher
from app.moneyline import observe
from app.settlement import profile, fact

ROOT=Path(__file__).resolve().parents[1]
ASSESSMENTS=ROOT/'app/fixtures/moneyline_rule_assessments.json'


def listing_profile(native,venue,source,assessments=None):
    assessments=assessments if assessments is not None else json.loads(ASSESSMENTS.read_text())
    text='\n\n'.join(native[k] for k in ('rules_primary','rules_secondary') if native.get(k)) if venue=='kalshi' else native.get('description','')
    h=sha256(text.encode()).hexdigest()
    src={'url':source['url'],'sha256':h,'text':text or '[listing rule text unavailable]',
         'artifact':source['artifact'],'capture_sha256':source['sha256'],
         'captured_at':source['captured_at'],'listing_updated_at':native.get('updated_time',native.get('updatedAt')),
         'effective_date':None,'priority':'market-specific'}
    assessment=assessments['listings'].get(h,{})
    fields={k:fact(v['value'],evidence=h if v['value'] is not None else None,reason=v['reason'])
            for k,v in assessment.get('dimensions',{}).items()}
    payouts={k:{**v,'evidence':h} for k,v in assessment.get('payouts',{}).items()}
    sources=[src]
    research=ROOT/'evidence/slice-8/research'
    metadata=json.loads((research/'sources.json').read_text())
    filename='kalshi-nfl-rules.pdf' if venue=='kalshi' else 'pmus-sports.md'
    meta=next(x for x in metadata if x['file']==filename)
    general_text=(research/('kalshi-nfl-rules.txt' if venue=='kalshi' else filename)).read_text()
    if sha256((research/filename).read_bytes()).hexdigest()!=meta['sha256']:
        raise ValueError('research source capture hash mismatch')
    reviewed_general=assessments.get('general_sources',{}).get(filename,{})
    general_unchanged=(reviewed_general.get('sha256')==meta['sha256'] and
                       reviewed_general.get('text_sha256')==sha256(general_text.encode()).hexdigest())
    sources.append({'url':meta['source'],'sha256':meta['sha256'],'text':general_text,
                    'artifact':str((research/filename).relative_to(ROOT)),
                    'captured_at':meta['retrieved_at'],'effective_date':None,
                    'priority':'general terms; listing terms take precedence',
                    'applicability':'Kalshi PDF identical to preserved Phase 0 terms' if venue=='kalshi' else
                                    'current broad guidance; exact listing exception precedence unresolved'})
    if venue=='kalshi' and assessment and general_unchanged:
        fields['overtime']=fact('included',evidence=meta['sha256'],reason='FOOTBALLGAMEWIN pages 1-2; identical preserved/current PDF; listing has no period override.')
        payouts['pregame_forfeit']={'kind':'discretionary','evidence':meta['sha256'],
                                   'reason':'FOOTBALLGAMEWIN p2: forfeit before opening kickoff'}
    return profile(sources=sources,dimensions=fields,payouts=payouts,actor=assessments['actor'])


def captured_inputs(parents=None):
    parents=parents or Matcher.load(ROOT/'evidence/slice-7/captured-store.json')
    snapshot=parents.snapshot
    manifest=json.loads((ROOT/'evidence/phase-0/manifest.json').read_text())
    pm_path='evidence/phase-0/pmus-nfl-events.json'; k_path='evidence/phase-0/kalshi-nfl-markets.json'
    texts={p:(ROOT/p).read_text() for p in (pm_path,k_path)}
    payloads={p:json.loads(t) for p,t in texts.items()}
    sources={}
    for p in texts:
        meta=next(m for m in manifest if m['file']==Path(p).name)
        sources[p]={'url':meta['source_endpoint'],'captured_at':meta['retrieved_at_utc'],
                    'artifact':p,'sha256':sha256(texts[p].encode()).hexdigest()}
    rows=[]; excluded=[]; coverage=[]
    for key,mapping in sorted(snapshot['mappings'].items()):
        if mapping['status']!='matched': continue
        parent=snapshot['observations'][snapshot['current'][key]]
        if parent['scope']!=['observation','production']: continue
        eid=parent['native_event_id']; venue=parent['venue']
        if venue=='polymarket_us':
            event=next(e for e in payloads[pm_path]['events'] if str(e['id'])==eid)
            natives=event['markets']; context={k:v for k,v in event.items() if k!='markets'}; path=pm_path
        elif venue=='kalshi':
            natives=[m for m in payloads[k_path]['markets'] if m['event_ticker']==eid]; path=k_path
            parent_body=json.loads(parent['normalized_observation']['observation']['raw']['json_text'])
            context=next(e for e in parent_body['events'] if e['event_ticker']==eid)
        else: continue
        src=sources[path]; count=0
        for native in natives:
            if venue=='polymarket_us' and native.get('marketType')!='moneyline':
                excluded.append({'parent_key':key,'native_market_id':str(native['id']),
                    'reason':'non-moneyline-market:'+str(native.get('marketType')),
                    'period_taxonomy':native.get('sportsMarketType'),'source':src})
                continue
            response=(KR if venue=='kalshi' else PR)(texts[path],src['url'],datetime.fromisoformat(src['captured_at']),EvidenceKind.OBSERVATION)
            market=parse_k(response,native,eid,context['series_ticker']) if venue=='kalshi' else parse_p(response,native,eid)
            row=observe(market,parent,listing_profile(native,venue,src),native=native,context=context,artifact=path)
            rows.append(row); count+=not bool(row['reasons'])
        coverage.append({'canonical_event_id':mapping['canonical_id'],'participants':parent['participants'],
                         'venue':venue,'native_event_id':eid,'captured_full_game_moneylines':count,
                         'gap':None if count else 'no usable captured moneyline for this confirmed event'})
    return parents,rows,excluded,coverage
