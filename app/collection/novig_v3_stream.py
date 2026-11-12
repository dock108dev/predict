"""Read-only Novig v3 stream reconstruction with fail-closed market authority.

No order, account mutation or credential provisioning is implemented here. The
transport passes original decoded frames and local receipt clocks to this owner.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

SECRET_REFERENCE = 'keychain:prediction-arb.novig.v3.production/market-data-read'


def load_read_key():
    """Read the dedicated local Ed25519 key; never return it in diagnostics."""
    import json
    from keyring.backends.macOS import Keyring
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    service, account = SECRET_REFERENCE.removeprefix('keychain:').split('/')
    try:
        value = json.loads(Keyring().get_password(service, account) or '{}')
        if set(value) != {'key_id', 'private_key_pem'} or not isinstance(value['key_id'], str) or not value['key_id']:
            raise ValueError()
        key = load_pem_private_key(value['private_key_pem'].encode(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError()
        return value['key_id'], key
    except Exception:
        raise ValueError('novig_v3_read_key_unavailable') from None


def signed_headers(key_id, key, method, path, query='', body=b'', *, timestamp_ms):
    """Sign an already-canonical query. Caller owns URL encoding and sorting."""
    import base64
    import hashlib
    if method != 'GET' or not path.startswith('/v3/') or '?' in path or '#' in path:
        raise ValueError('novig_read_only_request_required')
    message = '\n'.join(('NOVIG-V3', str(timestamp_ms), method, path, query, hashlib.sha256(body).hexdigest()))
    return {'Novig-Key-Id': key_id, 'Novig-Timestamp': str(timestamp_ms),
            'Novig-Signature': base64.b64encode(key.sign(message.encode())).decode()}


def _seq(value):
    if type(value) is not int or value < 0:
        raise ValueError('novig_invalid_sequence')
    return value


def _orders(raw, *, snapshot):
    result={}
    if not isinstance(raw, dict) or len(raw)>16:
        raise ValueError('novig_invalid_book')
    seen=set()
    for outcome, orders in raw.items():
        if not isinstance(outcome,str) or not outcome or not isinstance(orders,list) or len(orders)>10000:
            raise ValueError('novig_invalid_book')
        result[outcome]=[]
        for order in orders:
            result[outcome].append(_order(order,seen,snapshot=snapshot))
        if any(Decimal(a['price']) < Decimal(b['price']) for a,b in zip(result[outcome],result[outcome][1:])):
            raise ValueError('novig_book_price_order')
    return result


def _order(value, seen, *, snapshot):
    if not isinstance(value,dict):
        raise ValueError('novig_invalid_order')
    oid=value.get('order' if snapshot else 'orderId')
    p=value.get('price'); qty=value.get('qty')
    try:
        price=Decimal(p)
        if not isinstance(oid,str) or not oid or oid in seen or not isinstance(p,str) or not price.is_finite() or not 0 < price < 1 or type(qty) is not int or qty <= 0:
            raise ValueError()
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError('novig_invalid_order') from None
    seen.add(oid)
    return dict(orderId=oid,price=p,qty=qty)


class StreamBook:
    """One connection generation; gaps and disconnect revoke all affected data."""
    def __init__(self, event_id, market_id):
        if not event_id or not market_id: raise ValueError('novig_missing_identity')
        self.event_id,self.market_id=event_id,market_id
        self.generation=str(uuid4()); self.position=0
        self.lifecycle_seq=None;self.book_seq=None;self.status=None;self.phase=None
        self.orders=None;self.transition=None;self.reset_at=None;self.book_at=None
        self.reset_book_seq=None;self.book_source_at=None
        self.frames=[];self.connected=True;self.gap=None;self.pending_snapshot_nonce=None

    def revoke(self, reason):
        self.orders=None;self.transition=None;self.frames=[];self.book_at=None;self.pending_snapshot_nonce=None
        self.reset_book_seq=None;self.book_source_at=None
        self.gap=reason

    def disconnect(self):
        self.connected=False;self.revoke('novig_stream_disconnected')

    def request_snapshot(self, nonce):
        if not self.connected or self.transition is None or type(nonce) is not int or nonce < 1:
            raise ValueError('novig_snapshot_request_not_authorized')
        self.pending_snapshot_nonce=nonce

    def apply(self, frame, received_at):
        if not self.connected: raise ValueError('novig_stream_disconnected')
        if not isinstance(frame,dict):
            self.revoke('novig_stream_invalid_frame');raise ValueError('novig_stream_invalid_frame')
        try:
            snapshot=frame.get('snapshot');delta=frame.get('delta')
            if (snapshot is None)==(delta is None):raise ValueError('novig_stream_invalid_frame')
            payload=(snapshot if snapshot is not None else delta)
            if not isinstance(payload,dict) or set(payload)!={self.market_id}:raise ValueError('novig_stream_subject_conflict')
            value=payload[self.market_id]
            if not isinstance(value,dict) or value.get('eventId')!=self.event_id:
                raise ValueError('novig_stream_event_conflict')
            if not set(value).issubset({'eventId','lifecycle','book'}):raise ValueError('novig_stream_channel_unknown')
            staged=deepcopy(self)
            staged.position+=1
            if snapshot is not None:
                staged._snapshot(value, received_at, frame.get('nonce'))
            else:
                staged._delta(value, received_at)
            self.__dict__.update(staged.__dict__)
        except (ValueError,KeyError,TypeError,ArithmeticError):
            self.revoke('novig_stream_invalid_or_gap')
            raise

    def _snapshot(self, value, received_at, nonce):
        if 'lifecycle' in value:
            life=value['lifecycle']; seq=_seq(life['seq'])
            if self.lifecycle_seq is not None and seq < self.lifecycle_seq:raise ValueError('novig_lifecycle_out_of_order')
            if self.transition and seq != self.lifecycle_seq:raise ValueError('novig_lifecycle_sequence_gap')
            if life['status'] not in ('OPEN','CLOSED','SETTLED'):raise ValueError('novig_lifecycle_status')
            if seq == self.lifecycle_seq and life['status'] != self.status:
                raise ValueError('novig_lifecycle_sequence_conflict')
            self.lifecycle_seq=seq;self.status=life['status']
        if 'book' in value:
            book=value['book'];seq=_seq(book['seq'])
            if self.book_seq is not None and seq < self.book_seq:raise ValueError('novig_book_out_of_order')
            orders=_orders(book['orders'],snapshot=True)
            if seq == self.book_seq and self.orders is not None and orders != self.orders:
                raise ValueError('novig_book_sequence_conflict')
            if self.transition and (self.pending_snapshot_nonce is None or nonce != self.pending_snapshot_nonce):
                raise ValueError('novig_book_snapshot_request_unbound')
            if self.transition and self.reset_book_seq is not None and seq <= self.reset_book_seq:
                # An empty image immediately after the cancellations is valid,
                # but cannot support an offer. Wait for new orders.
                if any(orders.values()):
                    raise ValueError('novig_book_not_new_after_reset')
                self.pending_snapshot_nonce=None
                self.book_seq=seq
                return
            self.pending_snapshot_nonce=None
            self.book_seq=seq;self.orders=orders;self.book_at=received_at
            if self.transition and self.phase=='OPEN_INGAME' and self.status=='OPEN':
                from app.storage.store import hashed
                source_book=dict(marketId=self.market_id,seq=seq,
                                 orders={oid:deepcopy(ladder[:1]) for oid,ladder in orders.items()},
                                 orders_sha256=hashed(orders))
                self.frames.append(dict(position=self.position,market_id=self.market_id,book=source_book,nonce=nonce))
            else:self.frames=[]

    def _delta(self, value, received_at):
        if 'lifecycle' in value:
            item=value['lifecycle'];seq=_seq(item['seq'])
            if self.lifecycle_seq is None or seq != self.lifecycle_seq+1:raise ValueError('novig_lifecycle_sequence_gap')
            changes=item['deltas']
            if not isinstance(changes,list) or not changes:raise ValueError('novig_lifecycle_invalid_batch')
            for change in changes:
                kind=change['kind'];status=change['status']
                if status not in ('OPEN','CLOSED','SETTLED') or kind not in ('OPEN','CLOSE','GRADE','START','END','GOLIVE','UNLIVE'):
                    raise ValueError('novig_lifecycle_unknown')
                self.status=status
                if kind in ('GOLIVE','UNLIVE','CLOSE','END','GRADE'):
                    self.revoke('novig_book_reset_or_phase_change')
                    self.phase='OPEN_INGAME' if kind=='GOLIVE' else None
                    if kind=='GOLIVE' and status=='OPEN':
                        self.transition=dict(kind='GOLIVE',status='OPEN',seq=seq,position=self.position,received_at=received_at)
                        self.reset_at=received_at
                        self.reset_book_seq=self.book_seq
                        self.frames=[dict(position=self.position,market_id=self.market_id,lifecycle=deepcopy(item))]
            self.lifecycle_seq=seq
        if 'book' in value:
            item=value['book'];seq=_seq(item['seq'])
            if self.book_seq is None or seq != self.book_seq+1:raise ValueError('novig_book_sequence_gap')
            if self.orders is not None:
                orders=deepcopy(self.orders); removed={}
                for change in item['deltas']:
                    kind=change['kind']
                    if kind=='remove':
                        locations=[(side,i) for side,rows in orders.items() for i,o in enumerate(rows) if o['orderId']==change['order']]
                        if len(locations)!=1:raise ValueError('novig_unknown_order')
                        side,i=locations[0];removed[change['order']]=(side,i,orders[side].pop(i))
                    elif kind=='add':
                        outcome=change['outcome'];seen={o['orderId'] for rows in orders.values() for o in rows}
                        new=_order(dict(orderId=change['order'],price=change['price'],qty=change['qty']),seen,snapshot=False)
                        rows=orders.setdefault(outcome,[])
                        old=removed.get(new['orderId'])
                        if old and old[0]==outcome and old[2]['price']==new['price']:
                            rows.insert(min(old[1],len(rows)),new)
                        else:
                            i=next((i for i,v in enumerate(rows) if Decimal(v['price']) < Decimal(new['price'])),len(rows));rows.insert(i,new)
                    else:raise ValueError('novig_unknown_book_delta')
                self.orders=orders;self.book_at=received_at
                # A changed book invalidates the captured snapshot, while the
                # continuously observed reset still governs the next image.
                self.frames=[f for f in self.frames if 'book' not in f]
            self.book_seq=seq
        if self.transition and 'lifecycle' in value and self.transition['position']!=self.position:
            self.frames=[f for f in self.frames if 'book' not in f]
            self.frames.append(dict(position=self.position,market_id=self.market_id,lifecycle=deepcopy(value['lifecycle'])))
            if len(self.frames)>=128:self.revoke('novig_lifecycle_evidence_bound')

    def evidence(self, event, market, outcome_id, *, at, minimum_quantity=100):
        """Retain the top opposite order after a source GOLIVE and snapshot."""
        if (not self.connected or self.orders is None or not self.transition
                or not self.frames or 'book' not in self.frames[-1]):
            return None
        if event.get('eventId')!=self.event_id or event.get('status')!='OPEN_INGAME' or market.get('eventId')!=self.event_id or market.get('marketId')!=self.market_id:
            return None
        ids=[o.get('outcomeId') for o in market.get('outcomes',[])]
        if len(ids)!=2 or len(set(ids))!=2 or outcome_id not in ids:return None
        other=next(x for x in ids if x!=outcome_id);orders=self.orders.get(other,[])
        if not orders or orders[0]['qty'] < minimum_quantity:return None
        price=str(Decimal('1')-Decimal(orders[0]['price']))
        family={'MONEY':'winner','SPREAD':'spread','TOTAL':'total'}.get(market.get('marketType'))
        if not family:return None
        book=self.frames[-1]['book']
        return dict(identity=dict(event_id=self.event_id,market_id=self.market_id,outcome_id=outcome_id,side='buy',period='full_game',line=market.get('strike')),
            fill_count=1,price_levels=1,available_native_contracts=orders[0]['qty'],price=price,
            event_status='OPEN_INGAME',market_fee=deepcopy(market.get('fee')),native_event=deepcopy(event),native_market=deepcopy(market),
            quote_at=self.book_at,phase_at=at,terms_at=at,last_book_reset_at=self.reset_at,
            reset_proof=dict(transport='novig_v3_signed_stream',continuous=True,generation=self.generation,event_id=self.event_id,
                market_id=self.market_id,transition=deepcopy(self.transition),book=dict(kind='snapshot',seq=self.book_seq,position=self.frames[-1]['position'],received_at=self.book_at,source_at=self.book_source_at,nonce=self.frames[-1]['nonce']),
                source_book=deepcopy(book),frames=deepcopy(self.frames)))


class StreamSession:
    """Connection-owned market set; a frame is committed as one atomic unit."""
    def __init__(self, markets):
        if not markets or len(markets)>128:raise ValueError('novig_subscription_bound')
        self.markets={mid:StreamBook(eid,mid) for mid,eid in markets.items()}
        self.generation=str(uuid4())
        for owner in self.markets.values():owner.generation=self.generation
        self.connected=True

    def apply(self, frame, received_at):
        if not self.connected:raise ValueError('novig_stream_disconnected')
        kind='snapshot' if 'snapshot' in frame else 'delta' if 'delta' in frame else None
        if kind is None or not isinstance(frame[kind],dict) or not frame[kind]:
            self.disconnect();raise ValueError('novig_stream_invalid_frame')
        changed=frame[kind]
        if not set(changed).issubset(self.markets):
            self.disconnect();raise ValueError('novig_stream_subject_conflict')
        staged=deepcopy(self.markets)
        try:
            for market_id, payload in changed.items():
                staged[market_id].apply({kind:{market_id:payload},**({'nonce':frame['nonce']} if 'nonce' in frame else {})},received_at)
        except (ValueError, KeyError, TypeError, ArithmeticError):
            # The whole delivered batch is suspect. Do not leave an earlier
            # market's values live if another channel fails in the same frame.
            for market_id in changed:self.markets[market_id].revoke('novig_stream_invalid_or_gap')
            raise
        self.markets=staged

    def disconnect(self):
        self.connected=False
        for owner in self.markets.values():owner.disconnect()


async def read_only_stream(markets, on_update, *, key=None, connect_factory=None, duration=30,
                           require_provider_clock=False):
    """Bounded v3 stream. Only subscribe/snapshot are sent; never trade.

    `markets` is a reviewed exact market-id -> event-id catalog association.
    Every exit revokes the connection's authority before returning.
    """
    import asyncio
    import json
    import time
    from websockets.asyncio.client import connect
    if not 0 < duration <= 1800:raise ValueError('novig_stream_duration_bound')
    session=StreamSession(markets)
    key_id,private_key=key if key is not None else load_read_key()
    headers=signed_headers(key_id,private_key,'GET','/v3/ws',timestamp_ms=int(time.time()*1000))
    factory=connect_factory or connect
    nonce=1
    last_request={}
    try:
        async with factory('wss://api.novig.com/v3/ws',additional_headers=headers,
                open_timeout=8,close_timeout=2,max_size=1_000_000,max_queue=16,ping_interval=15,ping_timeout=15) as ws:
            await ws.send(json.dumps({'nonce':nonce,'subscribe':{'markets':{mid:'book' for mid in markets}}}))
            async with asyncio.timeout(duration):
                async for raw in ws:
                    if not isinstance(raw,str) or len(raw.encode())>1_000_000:raise ValueError('novig_stream_frame_bound')
                    frame=json.loads(raw)
                    if not isinstance(frame,dict):raise ValueError('novig_stream_invalid_frame')
                    if 'snapshot' not in frame and 'delta' not in frame:
                        if frame.get('error'):raise ValueError('novig_stream_provider_error')
                        continue
                    received=datetime.now(timezone.utc)
                    at=received.isoformat()
                    if require_provider_clock:
                        ts=frame.get('ts')
                        if type(ts) is not int or not 0 <= received.timestamp()-ts/1000 <= 15:
                            raise ValueError('novig_stream_clock_invalid')
                    session.apply(frame,at)
                    if require_provider_clock:
                        for mid, data in frame.get('snapshot', {}).items():
                            if 'book' in data:
                                session.markets[mid].book_source_at=datetime.fromtimestamp(ts/1000,timezone.utc).isoformat()
                    await on_update(session, frame, at)
                    # GOLIVE cancels resting orders. Request an unambiguous new
                    # snapshot; a later delta or receipt alone does not qualify.
                    request=[]
                    for mid,owner in session.markets.items():
                        ready=owner.book_seq is not None and (owner.reset_book_seq is None or owner.book_seq>owner.reset_book_seq)
                        initial=mid not in last_request or last_request[mid][0]!=owner.reset_at
                        if (owner.transition and owner.pending_snapshot_nonce is None
                                and not any('book' in item for item in owner.frames)
                                and (initial or ready and time.monotonic()-last_request[mid][1]>=3)):
                            request.append(mid)
                    if request:
                        nonce+=1
                        for mid in request:
                            owner=session.markets[mid]
                            owner.request_snapshot(nonce)
                            last_request[mid]=(owner.reset_at,time.monotonic())
                        await ws.send(json.dumps({'nonce':nonce,'snapshot':{'markets':{mid:'book' for mid in request}}}))
    except TimeoutError:
        pass
    finally:
        session.disconnect()
        await on_update(session, None, datetime.now(timezone.utc).isoformat())
