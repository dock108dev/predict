"""Complete provider book observations, separate from price clocks and revisions.

No heartbeat, delta, connection receipt or local clock is a confirmation.
"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from app.dashboard.session_projection import stable
VERSION='predict-book-confirmation-1'
BASES={'kalshi':'kalshi-complete-snapshot-send-1','polymarket_us':'us-complete-book-transact-1'}

def instant(value):
    at=datetime.fromisoformat(value.replace('Z','+00:00'))
    if at.tzinfo is None:raise ValueError('Confirmation clock lacks zone')
    return at

def content(book):
    return stable({k:book[k] for k in ('outcomes','state','sync','quantity_unit')})

class Confirmations:
    def __init__(self,venue):
        self.venue=venue;self.highwater={};self.latest={};self.generation=0
    def begin(self,generation):
        if generation<=self.generation:raise ValueError('Confirmation generation regressed')
        self.generation=generation;self.latest.clear()
    def observe(self,book,data,raw,*,generation,request_id,requested_at=None,sid=None,sequence=None):
        if generation!=self.generation:raise ValueError('Stale confirmation generation')
        ref=book['raw']['ref'];mid=ref['market_id'];at=None
        if self.venue=='kalshi':
            if data.get('type')=='orderbook_snapshot' and requested_at is not None:
                ms=data.get('sending_ts_ms')
                if type(ms) is int:at=datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()
                if data.get('msg',{}).get('market_ticker')!=mid or data.get('sid')!=sid or data.get('seq')!=sequence:raise ValueError('Snapshot confirmation identity conflict')
        else:
            md=data.get('marketData',{})
            if data.get('requestId')!=request_id or data.get('subscriptionType')!='SUBSCRIPTION_TYPE_MARKET_DATA':raise ValueError('Book confirmation subscription conflict')
            if isinstance(md.get('bids'),list) and isinstance(md.get('offers'),list) and md.get('transactTime') is not None:
                at=book['raw'].get('exchange_at')
                if at is not None and instant(at)!=instant(md['transactTime']):raise ValueError('Transaction timestamp reconstruction conflict')
        if ref['venue']!=self.venue or book['sync']!='synchronized':raise ValueError('Confirmation requires complete admitted book')
        if at is not None:
            observed=instant(at);received=instant(book['raw']['received_at'])
            if observed>received:raise ValueError('Future confirmation clock')
            if requested_at and observed<instant(requested_at):raise ValueError('Snapshot predates its request')
            prior=self.highwater.get(mid)
            if prior and observed<prior:raise ValueError('Confirmation clock regressed')
            if (not prior or observed>prior) and (received-observed).total_seconds()<=30:
                if self.latest.get(mid,{}).get('payload_sha256')==sha256(raw).hexdigest():raise ValueError('Replayed confirmation payload')
                proof=dict(version=VERSION,basis=BASES[self.venue],venue=self.venue,event_id=ref['event_id'],market_id=mid,
                    generation=generation,request_id=str(request_id),requested_at=requested_at,subscription_id=None if sid is None else str(sid),
                    sequence=sequence,confirmed_at=at,received_at=book['raw']['received_at'],provider_source_at=book['raw'].get('exchange_at'),
                    payload_sha256=sha256(raw).hexdigest(),content_sha256=content(book))
                proof['sha256']=stable(proof);self.latest[mid]=proof;self.highwater[mid]=observed
        proof=self.latest.get(mid)
        return deepcopy(proof) if proof and proof['content_sha256']==content(book) else None

def validate(proof,ref=None,book=None):
    keys={'version','basis','venue','event_id','market_id','generation','request_id','requested_at','subscription_id','sequence','confirmed_at','received_at','provider_source_at','payload_sha256','content_sha256','sha256'}
    if not isinstance(proof,dict) or set(proof)!=keys or proof['version']!=VERSION or proof['venue'] not in BASES or proof['basis']!=BASES[proof['venue']]:raise ValueError('Unsupported book confirmation')
    if proof['sha256']!=stable({k:v for k,v in proof.items() if k!='sha256'}):raise ValueError('Book confirmation seal mismatch')
    if type(proof['generation']) is not int or proof['generation']<1:raise ValueError('Invalid confirmation generation')
    for key in ('event_id','market_id','request_id'):
        if not isinstance(proof[key],str) or not 0<len(proof[key])<=256:raise ValueError('Bounded confirmation identity required')
    for key in ('payload_sha256','content_sha256','sha256'):
        if not isinstance(proof[key],str) or len(proof[key])!=64 or set(proof[key])-set('0123456789abcdef'):raise ValueError('Invalid confirmation hash')
    at=instant(proof['confirmed_at']);received=instant(proof['received_at'])
    if not 0<=(received-at).total_seconds()<=30:raise ValueError('Invalid confirmation age at receipt')
    if proof['provider_source_at'] is not None and instant(proof['provider_source_at'])>received:raise ValueError('Future provider source clock')
    if proof['venue']=='kalshi':
        if not proof['subscription_id'] or type(proof['sequence']) is not int or proof['sequence']<1 or proof['requested_at'] is None or instant(proof['requested_at'])>at:raise ValueError('Snapshot request/continuity proof missing')
    elif proof['provider_source_at']!=proof['confirmed_at'] or proof['sequence'] is not None or proof['subscription_id'] is not None:raise ValueError('US confirmation basis mismatch')
    if ref and any(proof[k]!=ref[r] for k,r in [('venue','venue'),('event_id','event_id'),('market_id','market_id')]):raise ValueError('Confirmation market mismatch')
    if book and (proof['content_sha256']!=content(book) or instant(proof['received_at'])>instant(book['raw']['received_at'])):raise ValueError('Confirmation content mismatch')
    return proof
