"""Versioned detector input envelope; existing engines remain unchanged."""
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from app.arbitrage import Observation, Policy, detect
from app.models.core import (RawPayload, NativeRef, Venue, EvidenceKind, Quote,
    QuoteSide, Probability, Quantity, MarketState)
from app.matching import Matcher
from app.moneyline import MoneylineMatcher
from app.fees.engine import Registry, load_registry, digest


def observation_dump(o):
    d=asdict(o)
    return json.loads(json.dumps(d,default=lambda x: str(x) if isinstance(x,Decimal) else x.isoformat()))


def observation_load(d):
    d=dict(d); q=dict(d.pop('quote')); raw=dict(q.pop('raw'))
    raw['ref']=NativeRef(**{**raw['ref'],'venue':Venue(raw['ref']['venue'])})
    raw['kind']=EvidenceKind(raw['kind'])
    for key in ('received_at','exchange_at'):
        raw[key]=datetime.fromisoformat(raw[key]) if raw[key] else None
    for side in ('ask','bid'):
        if q[side] is not None:
            v=q[side]; qty=v['quantity']
            q[side]=QuoteSide(price=Probability(value=Decimal(v['price']['value'])),
                quantity=Quantity(value=Decimal(qty['value']),unit=qty['unit']) if qty else None)
    return Observation(quote=Quote(raw=RawPayload(**raw),**{**q,'state':MarketState(q['state'])}),**d)


def detector_audit(parents, matcher, observations, contexts, **options):
    # Use the established validated snapshot format, including immutable revisions.
    opts=dict(options)
    opts['evaluation_time']=opts['evaluation_time'].isoformat()
    opts['policy']=asdict(opts.get('policy') or Policy())
    opts['registry']=(opts.get('registry') or load_registry()).data
    inputs=dict(parents=parents.envelope(),markets=matcher.envelope(),
        observations=[observation_dump(o) for o in observations],
        contexts=[[list(k),v] for k,v in contexts.items()],options=opts)
    result=detect(parents,matcher,observations,contexts,**options)
    return dict(engine='detector-capture-1',input=inputs,result=result,
                input_hash=digest(inputs),result_hash=digest(result))


def replay(audit):
    if audit['engine']=='depth-1':
        from app.depth import replay as depth_replay
        return depth_replay(audit)
    if audit['engine']!='detector-capture-1': raise ValueError('unsupported replay engine')
    inputs=audit['input']
    if digest(inputs)!=audit['input_hash']: raise ValueError('detector input identity mismatch')
    parents=Matcher.from_envelope(inputs['parents']);matcher=MoneylineMatcher.from_envelope(inputs['markets'])
    opts=dict(inputs['options']); opts['evaluation_time']=datetime.fromisoformat(opts['evaluation_time'])
    opts['policy']=Policy(**opts['policy']); opts['registry']=Registry(opts['registry'])
    result=detect(parents,matcher,[observation_load(o) for o in inputs['observations']],
                  {tuple(k):v for k,v in inputs['contexts']},**opts)
    if result!=audit['result'] or digest(result)!=audit['result_hash']:
        raise ValueError('detector result identity mismatch')
    return audit
