"""Offline native frame replay; saved receipts used, no economics or network."""
import base64
from dataclasses import asdict, replace
from datetime import datetime
import json
from app.models.core import EvidenceKind, ReceiptFreshness
from app.adapters.kalshi import Response as KR, parse_market as km
from app.adapters.polymarket_us import Response as PR, parse_market as pm
from app.adapters.kalshi_stream import BookReconstructor, RecoveryRequired
from app.adapters.polymarket_us_stream import MarketStream
from .transport_session import reopen


def verify_native(path):
    return verify_native_saved(reopen(path))

class NativeVerifier:
    """One stream group's native state; no retained observation list."""
    def __init__(self, first, profile_name=None):
        self.profile_name=profile_name
        self.native_product=bool(first.get('spec',{}).get('native_sources'))
        self.engines = {}; self.markets = {}; self.last = {}
        self.counts = {'kalshi': 0, 'polymarket_us': 0}; self.gaps = []
        if profile_name:
            from .supervised import Samples
            self.gaps=Samples()
        self.kind = EvidenceKind.OBSERVATION if first.get('spec', {}).get('mode') == 'real' else EvidenceKind.SYNTHETIC

    def feed(self, row):
        engines, markets, last = self.engines, self.markets, self.last
        counts, gaps, kind = self.counts, self.gaps, self.kind
        def dump(book): return json.loads(json.dumps(asdict(book), default=str))
        venue=row.get('source')
        if row['type']=='market_selected' and venue not in engines:
            m=row['market'];raw=m['raw'];r=(KR if venue=='kalshi' else PR)(raw['json_text'],raw['source'],datetime.fromisoformat(raw['received_at']),kind)
            payload=json.loads(raw['json_text']);mid=raw['ref']['market_id'];eid=raw['ref']['event_id']
            if venue=='kalshi':
                market=km(r,next(x for x in payload['markets'] if x['ticker']==mid),eid,'KXNFLGAME')
                markets.setdefault(venue,{})[mid]=market
            else:
                native = payload.get('markets') if 'markets' in payload else [x for e in payload['events'] for x in e.get('markets',[])]
                market=pm(r,next(x for x in native if str(x['id'])==mid),eid)
                markets.setdefault(venue,{})[mid]=market
        elif row['type']=='prediction_command':
            command=json.loads(row['body'])
            if venue not in engines:
                engines[venue]=(BookReconstructor(list(markets[venue].values()),kind=kind) if venue=='kalshi' else MarketStream(list(markets[venue].values()),None,kind=kind))
            e=engines[venue]
            if self.profile_name:
                from .supervised import bound_native
                if not getattr(e,'history_bounded',False): bound_native(e); e.history_bounded=True
            if venue=='kalshi':e.begin(command['id'])
            else:e.begin_subscription(command['subscribe']['requestId'])
            last.pop(venue,None)
        elif row['type']=='prediction_frame':
            e=engines[venue];body=base64.b64decode(row['body_b64']).decode()
            try:
                book=(e.feed(body,e.generation,datetime.fromisoformat(row['received_at'])) if venue=='kalshi' else e.parse(body,e.subscription_id,generation=e.generation))
                if book is not None:
                    last[venue]=book
            except (ValueError,RecoveryRequired):
                gaps.append(dict(source=venue,ingress_id=row.get('ingress_id'),reason='native_frame_rejected'))
                last.pop(venue,None)
        elif row['type']=='prediction_book':
            expected=row['book']
            if expected['sync']!='synchronized' or expected['receipt_freshness']!='recent':return
            if venue not in last:raise ValueError('saved book has no replayable native image')
            book=last[venue]
            # Native parsers sample wall time after recv; that exact saved clock is replay input.
            book=replace(book,raw=replace(book.raw,received_at=datetime.fromisoformat(expected['raw']['received_at'])),receipt_freshness=ReceiptFreshness.RECENT)
            if self.native_product:
                from .native_semantics import purchase_book
                book=purchase_book(book)
            if dump(book)!=expected:raise ValueError('native book replay mismatch: '+venue)
            counts[venue]+=1
            # Verify derived quote packets too, using the existing converter.
            from app.arbitrage import book_observations
            from app.storage.workflow import packet
            packets=[]
            for observation in book_observations(book,environment='production' if kind==EvidenceKind.OBSERVATION else 'synthetic',evidence_class='current' if kind==EvidenceKind.OBSERVATION else 'synthetic',source_time_semantics='unknown'):
                p=packet(observation);p['raw_b64']=base64.b64encode(p.pop('raw')).decode();packets.append(p)
            if packets!=row['packets']:raise ValueError('native quote packet replay mismatch')

    def result(self, sha256=None, state='interrupted'):
        return dict(exact_native_books=self.counts, exact_packets=True, gaps=self.gaps,
                    journal_sha256=sha256, state=state)


def verify_native_saved(saved):
    verifier = NativeVerifier(saved['rows'][0])
    for row in saved['rows']:
        verifier.feed(row)
    return verifier.result(saved['sha256'], saved['state'])


class GroupedNativeVerifier:
    """Sequential cross-segment replay: engines never start at an arbitrary segment.

    Group metadata, subscription and native snapshot dependencies must precede use.
    The finite offline policy caps total rows; no checkpoints or hidden sidecars.
    """
    def __init__(self, profile_name=None):
        from .supervised import profile
        self.profile=profile(profile_name) if profile_name else None
        self.retired=set()
        self.first = None
        self.groups = {}
        self.previous_books = {}
        self.derived_health_books = 0

    def feed(self, row):
        if row['type'] == 'session_started':
            if self.first is not None:
                raise ValueError('new source session requires explicit replay boundary')
            self.first = row
        group = row.get('stream_group')
        if group is None and row.get('source') in ('kalshi', 'polymarket_us'):
            group = '_legacy'
        if group is not None:
            if self.first is None:
                raise ValueError('missing session dependency')
            if group not in self.groups:
                if len(self.groups) >= (self.profile['groups'] if self.profile else 24):
                    raise ValueError('offline replay group cap')
                self.groups[group] = NativeVerifier(self.first,self.profile['name'] if self.profile else None)
            verifier = self.groups[group]
            if self.profile and group in self.retired and row['type'] in ('prediction_command','prediction_frame','prediction_book','market_selected'):
                raise ValueError('observation after retired stream group')
            if self.profile and row['type']=='subscription_departure':
                verifier.engines.clear();verifier.markets.clear();verifier.last.clear()
                self.previous_books={k:v for k,v in self.previous_books.items() if k[0]!=group}
                self.retired.add(group)
            if row['type'] == 'source_health' and row.get('state') in ('awaiting_snapshot', 'disconnected', 'ineligible'):
                verifier.last.pop(row['source'], None)
            verifier.feed(row)
            if row['type'] == 'prediction_book':
                from copy import deepcopy
                book = row['book']
                key = (group, row['source'], book['raw']['ref']['market_id'])
                if book['sync'] == 'synchronized' and book['receipt_freshness'] == 'recent':
                    self.previous_books[key] = row
                else:
                    if key not in self.previous_books:
                        raise ValueError('health book lacks prior native image')
                    old = self.previous_books[key]
                    expected = deepcopy(old['book'])
                    if book['sync'] not in ('synchronized', 'unsynchronized') or book['receipt_freshness'] not in ('recent', 'stale'):
                        raise ValueError('unsupported health derivation')
                    expected.update(sync=book['sync'], receipt_freshness=book['receipt_freshness'])
                    packets = deepcopy(old['packets'])
                    for packet in packets: packet['normalized']['sync'] = book['sync']
                    if expected != book or packets != row['packets']:
                        raise ValueError('health book or packets changed native input')
                    self.derived_health_books += 1

    def result(self, state='interrupted', sha256=None):
        return {group: verifier.result(sha256, state) for group, verifier in self.groups.items()}
