from app.normalization import score_periods,futures
"""Bounded durable session view shared by current viewing and verified history.

No transport ownership, provider activation or economic rules live here. Product
identities are additive; legacy selection IDs are deliberately left untouched.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from itertools import combinations, product
import json

from app.dashboard.e6_real import project_book as legacy_book

REVISION = 'product-session-1'
LABELS = {'kalshi':'Kalshi','polymarket_us':'Polymarket US','novig':'Novig','prophetx':'ProphetX'}


def stable(value):
    return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def stamp(value):
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def identity(event, market):
    # Existing coverage canonical keys came from normalized participant bindings.
    # Additional scopes are explicit and never guessed from the event title.
    legacy=isinstance(event.get('canonical_key'),list) and len(event['canonical_key'])==2 and isinstance(event['canonical_key'][1],list)
    return dict(version=1, event=event.get('canonical_key') or ['unresolved',event['id']],
        sport=event.get('sport','american_football' if legacy else 'unknown'), competition=event.get('competition','NFL' if legacy else 'unknown'),
        season=event.get('season',(event.get('scheduled_start') or '')[:4]), stage=event.get('stage'),
        scheduled_start=event.get('scheduled_start'), family=market.get('market_type','unknown'),
        period=market.get('period','unknown'), line=market.get('line'), subject=market.get('subject'),
        outcome_set=market.get('outcome_set'), rules=market.get('rules_revision','normal-winner-legacy'),
        category=market.get('category'), horizon=market.get('horizon'))


def format_book(row, sides):
    # Reuse the established formatter without weakening historical evidence checks.
    value=deepcopy(row)
    for packet in value['packets']:
        kind=packet['normalized']['raw_kind']
        if kind not in ('observation','synthetic'): raise ValueError('unsupported book evidence')
        packet['normalized']['raw_kind']='observation'
    return legacy_book(value,None,sides)


class SessionProjection:
    def __init__(self):
        self.cursor=0; self.chain='0'*64; self.last=None; self.started=None; self.finished=None; self.stop_reason=None
        self.qualification_contexts={}; self.sid=None; self.spec={}; self.inventory={}; self.generation=None
        self.book_evidence={}; self.metadata={}; self.books={}; self.health={}; self.invalid=set(); self.references={}; self.resolutions={}
        self.aggregates={}; self.aggregate_bytes=0; self.aggregate_scopes={}; self.aggregate_status={}; self.aggregate_context={}
        self.native_receipts={}; self.native_reviews={}; self.native_fee_contexts={}; self.qualification_failure=None; self.coverage_status={}; self.refresh=None; self.last_row_hash=None; self.sizes={}; self.safety={}

    def apply(self,row,cursor=None):
        # Match journal JSON types at the acknowledged live boundary.
        row=json.loads(json.dumps(row,default=str))
        cursor=self.cursor+1 if cursor is None else cursor
        if cursor==self.cursor:
            if stable(row)!=self.last_row_hash:raise ValueError('conflicting cursor')
            return
        if cursor!=self.cursor+1: raise ValueError('noncontiguous durable cursor')
        typ=row['type']; source=row.get('source'); at=row['observed_at']
        if self.spec.get('aggregate_version') and typ in ('coverage_inventory','prediction_book','market_selected','product_reference'):
            raise ValueError('Historical aggregate session cannot mix source paths')
        if typ in ('prediction_book','market_selected','coverage_inventory','product_reference'):
            data=row.get('book',row.get('market',{}));ref=data.get('raw',{}).get('ref',{})
            size_key=(typ,source,ref.get('event_id'),ref.get('market_id'),row.get('reference',{}).get('id'))
            size=len(json.dumps(row).encode())
            if sum(self.sizes.values())-self.sizes.get(size_key,0)+size>16*1024*1024:raise ValueError('projection byte bound')
            self.sizes[size_key]=size
        if self.finished: raise ValueError('observation after terminal')
        if self.sid and row['session_id']!=self.sid: raise ValueError('session identity changed')
        if typ=='native_fee_metadata' and source=='kalshi' and row.get('status')=='scoped_current_terms_bound':
            if len(self.native_fee_contexts)>=16:raise ValueError('Native fee context bound')
            self.native_fee_contexts[row['event_id']]=deepcopy(row)
        if typ=='session_started':
            if self.started: raise ValueError('duplicate session start')
            self.sid=row['session_id']; self.started=at; self.spec=deepcopy(row['spec'])
            from app.dashboard.native_reviews import validate
            values=self.spec.get('native_review_records',[])
            if not isinstance(values,list) or len(values)>128 or len(json.dumps(values).encode())>4*1024*1024:raise ValueError('Native review input bound')
            for value in values:
                record=validate(value);key=(record['review_id'],record['revision'])
                if key in self.native_reviews:raise ValueError('Duplicate native review revision')
                self.native_reviews[key]=record
        elif typ=='native_review':
            from app.dashboard.native_reviews import validate
            record=validate(row['review'])
            key=(record['review_id'],record['revision'])
            if key in self.native_reviews:raise ValueError('Native review revision cannot be rewritten')
            if len(self.native_reviews)>=128 or sum(len(json.dumps(v).encode()) for v in self.native_reviews.values())+len(json.dumps(record).encode())>4*1024*1024:raise ValueError('Native review capacity exceeded')
            self.native_reviews[key]=record
        elif typ=='qualification_context':
            if self.spec.get('future_qualification_policy')!='native-prerequisites-1':raise ValueError('Unversioned qualification context')
            context=deepcopy(row['context']); key=context['book_id']
            if key in self.qualification_contexts:raise ValueError('Qualification context cannot be rewritten')
            if len(self.qualification_contexts)>=64 or len(json.dumps(context).encode())>32768:raise ValueError('Qualification context bound')
            self.qualification_contexts[key]=context
        elif typ in ('prediction_http','prediction_discovery_http'):
            # Receipt anchors for versioned retained catalog judgments; never parse partial bytes.
            if row.get('complete') and row.get('status')==200:
                import base64
                body=base64.b64decode(row['body_b64'])
                if sha256(body).hexdigest()!=row['body_sha256']:raise ValueError('Native receipt hash mismatch')
                if len(self.native_receipts)>=4096 and (source,row['body_sha256']) not in self.native_receipts:raise ValueError('Native receipt anchor bound')
                receipt_key=(source,row['body_sha256'])
                from app.collection.native_review_binding import enabled as current_review_binding
                if current_review_binding(self.spec) and receipt_key in self.native_receipts:
                    self.native_receipts[receipt_key]=min(self.native_receipts[receipt_key],row['received_at'],key=stamp)
                else:self.native_receipts[receipt_key]=row['received_at']
        elif typ=='coverage_inventory':
            if row.get('previous_generation')!=self.generation: raise ValueError('inventory dependency mismatch')
            cats=deepcopy(row['inventory'])
            if sum(len(c['markets']) for c in cats.values())>512 and getattr(self,'native_interpretation','native-book-comparison-4')=='native-book-comparison-4':
                from app.collection.catalog_metadata import compact
                for venue,cat in cats.items():compact(cat,venue)
            if sum(len(c['markets']) for c in cats.values())>512: raise ValueError('projection market bound')
            old=self.memberships(); self.inventory=cats; self.generation=row['generation']; new=self.memberships()
            for key in list(self.books):
                if key not in new or old.get(key)!=new[key]:
                    self.books.pop(key,None); self.metadata.pop(key,None); self.invalid.discard(key)
            self.sizes={k:v for k,v in self.sizes.items() if k[0] not in ('prediction_book','market_selected') or (k[1],k[2],k[3]) in new}
            self.health={k:v for k,v in self.health.items() if k in new}
            self.refresh=None;self.safety={}
        elif typ in ('market_selected','prediction_book'):
            data=row['market'] if typ=='market_selected' else row['book']; ref=data['raw']['ref']
            key=(source,ref['event_id'],ref['market_id'])
            if len(self.metadata)+len(self.books)>=1024 and key not in self.metadata and key not in self.books:
                raise ValueError('projection state bound')
            if typ=='market_selected': self.metadata[key]=deepcopy(row)
            else:
                self.books[key]=deepcopy(row)
                if row.get('native_observation'):
                    obs=row['native_observation']
                    summary=self.book_evidence.setdefault(key,dict(counts={},latest=None))
                    label=obs['classification']
                    summary['counts'][label]=summary['counts'].get(label,0)+1
                    summary['latest']=deepcopy(obs)
                if data['sync']=='synchronized' and self.health.get(key,{}).get('state')=='connected': self.invalid.discard(key)
        elif typ=='native_source_stopped':
            if source in self.inventory:
                self.inventory[source].update(source_error=row['reason'],selected_exclusions=[dict(reason=row['reason'],admission='terminal',retry=False)])
            for key in self.books:
                if key[0]==source:
                    self.invalid.add(key)
                    self.health[key]=dict(source=source,state='unavailable',gap_reason=row['reason'])
        elif typ=='source_health':
            for key in self.memberships() | dict.fromkeys(self.books):
                if key[0]!=source: continue
                if row.get('market_ids') is not None and key[2] not in row['market_ids']: continue
                if row.get('stream_group') and row.get('market_ids') is None and self.books.get(key,{}).get('stream_group')!=row['stream_group']: continue
                self.health[key]={k:deepcopy(row.get(k)) for k in ('source','state','gap_reason','market_ids','observed_at','stream_group')}
                if row['state']!='connected': self.invalid.add(key)
        elif typ=='qualification_discovery_failed':
            self.qualification_failure=deepcopy(row)
        elif typ=='product_coverage_status':
            self.coverage_status=deepcopy(row['coverage']); self.refresh=deepcopy(row.get('refresh'));self.safety=deepcopy(row.get('safety_exclusions',{}))
        elif typ=='product_resolution':
            from app.resolution.core import validate,MAX_RECORDS
            r=deepcopy(row['resolution']);validate(r)
            if self.spec.get('mode')!='mock' and r['evidence_mode']=='synthetic':raise ValueError('Synthetic resolution in real session')
            if r['id'] not in self.resolutions:
                if len(self.resolutions)>=MAX_RECORDS or sum(len(json.dumps(v).encode()) for v in self.resolutions.values())+len(json.dumps(r).encode())>8*1024*1024:raise ValueError('Resolution bound')
                self.resolutions[r['id']]=dict(record=r,observed_at=at,cursor=cursor)
        elif typ in ('aggregate_snapshot','aggregate_award_snapshot','aggregate_inventory','aggregate_status'):
            from app.collection.source_session import VERSION as SESSION_VERSION
            from app.reference.aggregate import VERSION
            if self.spec.get('source_session',{}).get('version')!=SESSION_VERSION:
                raise ValueError('Unversioned aggregate session observation')
            if typ=='aggregate_status':self.aggregate_status=deepcopy(row)
            elif typ=='aggregate_inventory':
                for scope in list(self.aggregate_scopes):
                    if scope[0]==row['sport'] and scope[1] not in row['event_ids'] and scope[1]!='award':
                        for key in self.aggregate_scopes.pop(scope):self.aggregates.pop(key,None)
                        self.aggregate_context.pop(scope,None)
            else:
                if row['version']!=VERSION:raise ValueError('Unsupported aggregate mapping')
                records=deepcopy(row['records'])
                if len(records)>5000 or any(r['original']['sport']!=row['sport'] or (typ!='aggregate_award_snapshot' and r['original']['source_event_id']!=row['event_id']) or r['response']!=row['response_sha256'] for r in records):raise ValueError('Aggregate scope mismatch')
                scope=(row['sport'],'award' if typ=='aggregate_award_snapshot' else row['event_id'])
                updated={k:v for k,v in self.aggregates.items() if k not in self.aggregate_scopes.get(scope,[])}
                updated.update({r['id']:r for r in records})
                if len(updated)>5000 or len(json.dumps(updated).encode())>16*1024*1024:raise ValueError('Aggregate bound')
                self.aggregates=updated;self.aggregate_scopes[scope]=[r['id'] for r in records]
                self.aggregate_context[scope]={k:deepcopy(row.get(k)) for k in ('sport','event_id','response_sha256','received_at','processing_at','observed_at')}
        elif typ=='product_aggregate':
            from app.reference.aggregate import VERSION
            if self.spec.get('aggregate_version') != VERSION or self.spec.get('mode') != 'observation':
                raise ValueError('Aggregate import requires an isolated historical observation session')
            if self.inventory or self.books:raise ValueError('Aggregate historical session cannot mix native books')
            records=deepcopy(row['records'])
            if row.get('version') != VERSION:raise ValueError('Unsupported aggregate version')
            for record in records:
                key=record['id']
                if record['version'] not in (VERSION, 'odds-aggregate-period-1'):raise ValueError('Unsupported aggregate record')
                if key in self.aggregates:
                    if self.aggregates[key]!=record:raise ValueError('Aggregate revision changed')
                    continue
                size=len(json.dumps(record).encode())
                if len(self.aggregates)>=5000 or self.aggregate_bytes+size>16*1024*1024:raise ValueError('Aggregate bound')
                self.aggregates[key]=record;self.aggregate_bytes+=size
        elif typ=='product_reference':
            ref=deepcopy(row['reference'])
            if ref['role'] not in ('model_reference','bookmaker_reference'): raise ValueError('invalid reference role')
            if len(self.references)>=128 and ref['id'] not in self.references: raise ValueError('reference bound')
            if ref.get('schema_version')=='b4-reference-1':
                from app.reference.product import validate
                validate(ref)
                if self.spec.get('mode')!='mock' and ref['evidence_mode']=='synthetic':raise ValueError('Synthetic reference in real session')
                if ref['id'] in self.references and {k:v for k,v in self.references[ref['id']].items() if k not in ('observation_id','observed_at')}!=ref:raise ValueError('Reference revision changed')
                ref.update(observation_id=row.get('ingress_id'),observed_at=at)
            else:ref.update(observation_id=row.get('ingress_id'),received_at=at)
            if ref.get('schema_version')!='b4-reference-1' or ref['id'] not in self.references:self.references[ref['id']]=ref
        elif typ=='session_finished': self.finished=at;self.stop_reason=row.get('reason')
        self.cursor=cursor; self.chain=stable([self.chain,row]); self.last=at;self.last_row_hash=stable(row)

    def memberships(self):
        result={}
        for source,cat in sorted(self.inventory.items()):
            if cat.get('role','prediction')!='prediction':continue
            events={e['id']:e for e in cat['events']}
            for m in cat['markets']:
                e=events.get(m['event_id'])
                if e: result[(source,e['id'],m['id'])]=[identity(e,m),m.get('status'),m.get('exclusion')]
        return result

    def snapshot(self,cutoff=None,now=None,mode='saved',state=None):
        token=str(self.cursor)+'-'+self.chain
        if cutoff is not None and cutoff!=token: raise ValueError('cutoff requires verified prefix replay')
        at=(now or datetime.now(timezone.utc).isoformat()) if mode=='current' else self.last
        groups={}; catalog=[]; metadata=[]
        from app.normalization.registry import Registry
        registry=None
        from app.normalization.nhl import inventory_gaps, winner_review, event_key
        nhl_gaps=inventory_gaps(self.inventory)
        from app.normalization import mlb,nba,ncaaf,ncaab,nfl_lines
        mlb_gaps=mlb.inventory_gaps(self.inventory)
        nba_gaps=nba.inventory_gaps(self.inventory)
        ncaaf_gaps=ncaaf.inventory_gaps(self.inventory)
        ncaab_gaps=ncaab.inventory_gaps(self.inventory)
        from app.normalization import nhl_lines
        nhl_line_gaps=nhl_lines.inventory_gaps(self.inventory)
        nfl_line_gaps=nfl_lines.inventory_gaps(self.inventory)
        for source,cat in sorted(self.inventory.items()):
            if cat.get('role','prediction')!='prediction':continue
            events={e['id']:e for e in cat['events']}
            for m in cat['markets']:
                e=events.get(m['event_id']); key=(source,m['event_id'],m['id'])
                ident=identity(e,m) if e else None
                reason=m.get('exclusion') or (e or {}).get('exclusion') or self.safety.get(source,{}).get(m['id'])
                if e and e.get('scheduled_start'):
                    try:
                        if stamp(at)>=stamp(e['scheduled_start']):reason=reason or 'scheduled start reached'
                    except (ValueError,TypeError):reason=reason or 'Invalid or timezone-less scheduled start'
                if not e or e.get('identity')!='resolved': reason=reason or 'unresolved event'
                if ident and not ((ident['competition'] in ('NFL','NCAAF') and ident['sport'] in ('american_football','football')) or (ident['competition']=='MLB' and ident['sport']=='baseball') or (ident['competition'] in ('NBA','NCAAB') and ident['sport']=='basketball') or (ident['competition']=='NHL' and ident['sport'] in ('hockey','ice_hockey'))):reason=reason or 'unsupported sport or competition'
                if e and not futures.scope(ident) and ident['competition']=='NHL':reason=reason or nhl_gaps.get((source,e['id']))
                if e and not futures.scope(ident) and ident['competition']=='MLB':reason=reason or mlb_gaps.get((source,e['id']))
                if e and not futures.scope(ident) and ident['competition']=='NBA':reason=reason or nba_gaps.get((source,e['id']))
                if e and not futures.scope(ident) and ident['competition']=='NCAAF':reason=reason or ncaaf_gaps.get((source,e['id']))
                if e and not futures.scope(ident) and ident['competition']=='NCAAB':reason=reason or ncaab_gaps.get((source,e['id']))
                h1=bool(ident and ident['competition'] in ('NFL','NCAAF','NBA','NCAAB') and ident['period']=='first_half' and ident['family'] in ('moneyline','spread','total'))
                segment=bool(ident and score_periods.scope(ident))
                is_line=futures.scope(ident or {}) or h1 or segment or bool(ident and ident['competition'] in ('NBA','NCAAB','NFL','NCAAF','MLB','NHL') and ident['family'] in ('spread','total'))
                if is_line and ident['competition']=='NHL':reason=reason or nhl_line_gaps.get((source,e['id']))
                if is_line and ident['competition']=='NFL':reason=reason or nfl_line_gaps.get((source,e['id']))
                if ident and ((ident['family']!='moneyline' and not is_line) or (ident['period']!='full_game' and not h1 and not segment and not futures.scope(ident))): reason=reason or 'unsupported family or period'
                if m['id'] not in cat.get('selection',{}).get('ids',[]): reason=reason or 'not selected'
                if self.spec.get('native_discovery',{}).get('slice')=='native-books-v1':
                    reason=reason or 'raw native acquisition; economics and contract equivalence unqualified'
                record=dict(source_id=source,event_id=m['event_id'],market_id=m['id'],identity=ident,title=(e or {}).get('title'),reason=reason,health=deepcopy(self.health.get(key)),native=deepcopy(m))
                if 'display_prices' in m:
                    record.update(received_at=m.get('received_at'),update_path=cat.get('update_path'))
                retained=self.books.get(key)
                if retained:
                    record.update(received_at=retained['book']['raw']['received_at'],update_path=retained.get('update_path','native stream'),
                        quantity_unit=retained['book']['quantity_unit'],quotes=[deepcopy(q) for p in retained['packets'] for q in p['normalized']['quotes']])
                if key in self.book_evidence:
                    record['book_evidence']=deepcopy(self.book_evidence[key])
                    record['native_book']=deepcopy(retained['book']) if retained else None
                catalog.append(record)
                if self.spec.get('mode')=='real' and source in ('kalshi','polymarket_us') and ident and ident.get('rules')=='normal-winner-legacy' and getattr(self,'native_interpretation','native-book-comparison-4')=='native-book-comparison-4':
                    record['reason']=reason or 'Explicit versioned native review required for raw correspondence'
                    continue
                if reason: continue
                meta=self.metadata.get(key)
                if not meta: record['reason']='awaiting metadata'; continue
                review=None
                if ident['competition'] in ('NHL','MLB','NBA','NCAAF','NCAAB') or is_line:
                    try:
                        if ident['competition'] in ('MLB','NBA','NCAAF','NCAAB') or is_line:
                            for observed in (meta,self.books.get(key)):
                                if not observed:continue
                                raw=observed.get('market',observed.get('book'))['raw']
                                if any(raw.get(k) and stamp(raw[k])>stamp(at) for k in ('received_at','exchange_at')) or stamp(observed['observed_at'])>stamp(at):
                                    raise ValueError(ident['competition']+' native input is later than cutoff')
                        review_fn={'MLB':mlb.winner_review,'NBA':nba.winner_review,'NCAAF':ncaaf.winner_review,'NCAAB':ncaab.winner_review}.get(ident['competition'],winner_review)
                        key_fn={'NFL':nfl_lines.event_key,'MLB':mlb.event_key,'NBA':nba.event_key,'NCAAF':ncaaf.event_key,'NCAAB':ncaab.event_key}.get(ident['competition'],event_key)
                        if is_line:
                            from app.normalization.score_lines import review as review_fn
                            if ident['competition']=='NHL':key_fn=nhl_lines.event_key
                            if futures.scope(ident):key_fn=futures.event_key
                        review=review_fn(e,m,meta,source,self.spec.get('mode'))
                        # Additive projection only: retained event/native IDs are untouched.
                        canonical=key_fn(e)
                        ident=dict(ident,event=canonical,sport={'NFL':'american_football','MLB':'baseball','NBA':'basketball','NHL':'ice_hockey','NCAAF':'american_football','NCAAB':'basketball'}[ident['competition']],scheduled_start=canonical[3])
                        if is_line:
                            ident.update(line=review['canonical']['threshold'],subject=e['home'] if ident['family']=='spread' else 'combined',rules={'version':'score-lines-1','unit':review['descriptor']['unit'],'domain':review['canonical']['domain'],'overtime':'included','completion':review['terms']['completion']})
                        if is_line and not futures.scope(ident) and ident['competition']=='NFL':
                            ident['rules'].update({k:review['descriptor'][k] for k in ('overtime_format','tied_score','normal_completion')})
                        if segment:
                            ident['rules'].update(overtime='excluded',settlement_score=ident['period']+'_only',offered='pregame')
                            if ident['family']=='moneyline':ident.update(line=None,subject=e['home'])
                        if h1:
                            ident['rules'].update(overtime='excluded',settlement_score='first_half_only',offered='pregame')
                            if ident['family']=='moneyline':ident.update(line=None,subject=e['home'])
                        if is_line and not futures.scope(ident) and ident['competition']=='NCAAF':
                            ident['rules'].update({k:review['descriptor'][k] for k in ('overtime_format','overtime_scoring','tied_score','normal_completion','subdivision_scope')})
                        if is_line and not futures.scope(ident) and ident['competition']=='MLB':
                            ident['rules'].update({k:review['descriptor'][k] for k in ('extra_innings','pitcher_conditions','normal_completion','tied_score','completion_scope')})
                        if is_line and not futures.scope(ident) and ident['competition']=='NHL':
                            ident['rules'].update({k:review['descriptor'][k] for k in ('overtime_format','settlement_score','normal_completion','tied_score')})
                        if futures.scope(ident):ident['rules'].update(states=e['states'],field=e['field'],field_structure=e['field_structure'],settlement_score='championship_award',overtime='not_applicable')
                        record['identity']=ident
                    except (ValueError,KeyError,TypeError,AttributeError,IndexError,StopIteration) as exc:
                        record['reason']=str(exc);continue
                try:
                    if not m.get('product_outcomes') and registry is None:registry=Registry.load()
                    sides=self.sides(source,e,m,meta,registry)
                except (KeyError,ValueError,StopIteration,TypeError): record['reason']='unsupported outcome identity'; continue
                if len(sides)!=2 and not (is_line and len(sides)==3): record['reason']='unsupported outcome set'; continue
                book=self.books.get(key); age=None if not book else str(Decimal(str((stamp(at)-stamp(book['book']['raw']['received_at'])).total_seconds())))
                connection=self.health.get(key,{}).get('state','awaiting_snapshot')
                if key in self.invalid and connection=='connected': connection='resynchronization_required'
                try: formatted=format_book(book,{source:{s['native_id']:(s['participant'],s.get('native_label',s['native_id'])) for s in sides.values()}}) if book else None
                except (ValueError,KeyError,StopIteration,TypeError):
                    record['reason']='unsupported book packet';continue
                if formatted and book.get('application_received_at'):formatted['application_received_at']=book['application_received_at']
                if formatted and book.get('local_timing'):formatted['local_timing']=deepcopy(book['local_timing'])
                if formatted and self.spec.get('future_qualification_policy'):
                    formatted['native_qualification_scope']={'venue':source,'event_id':e['id'],'market_id':m['id']}
                    formatted['connection_epoch']=book.get('connection_epoch')
                card=dict(venue=source,label=LABELS.get(source,source),book=formatted,
                    connection=connection,age_seconds=age,receipt_stale=age is not None and Decimal(age)>30)
                if card['book'] and card['book']['market_state']=='unknown' and not self.spec.get('native_sources'): card['book']['market_state']=meta['market']['state']
                record.update(age_seconds=age,usable=bool(book and connection=='connected' and not card['receipt_stale'] and card['book']['sync']=='synchronized' and card['book']['market_state']=='active'))
                groups.setdefault(stable(ident) if is_line else stable([ident,review['terms']]) if review else stable(ident),[]).append((source,e,m,sides,card,meta,ident))
        games=[]; points={}; rows_by_game={}; truncated=0
        for group,values in sorted(groups.items()):
            values.sort(key=lambda x:(x[0],x[1]["id"],x[2]["id"]))
            for a,b in combinations(values,2):
                if a[0]==b[0] or self.inventory[a[0]].get('origin_id',a[0])==self.inventory[b[0]].get('origin_id',b[0]): continue
                sides={**a[3],**b[3]}; teams=sorted(set(s['participant'] for s in sides.values()))
                is_line=futures.scope(a[6]) or score_periods.scope(a[6]) or a[6]['family'] in ('spread','total') or (a[6]['competition'] in ('NFL','NCAAF','NBA','NCAAB') and a[6]['period']=='first_half')
                if not is_line and len(teams)!=2: continue
                def winner(s): return next(t for t in teams if t!=s['participant']) if s['predicate']=='not_win' else s['participant']
                candidates=[]
                for x,y in product(a[3],b[3]):
                    if is_line or winner(sides[x])!=winner(sides[y]): candidates.append((stable([x,y]),winner(sides[x])+' + '+winner(sides[y]),(x,y)))
                if is_line and any(len(x[3])==3 for x in (a,b)):
                    from app.normalization.score_lines import market_partitions,payout
                    parts=market_partitions(a[6])
                    for keys in combinations(sides,3):
                        if len({k.split(':')[0] for k in keys})<2:continue
                        pays=[[payout(sides[k],p) for k in keys] for p in parts]
                        if all(all(v not in (None,'refund') for v in ps) and sum(Decimal(v) for v in ps)==1 for ps in pays):candidates.append((stable(list(keys)),'Three-outcome portfolio',keys))
                if not candidates: continue
                if len(games)>=64:
                    truncated+=1;continue
                gid=stable([group,sorted([list((x[0],x[1]['id'],x[2]['id'])) for x in (a,b)])])
                if is_line:gid=stable([gid,[(x[0],x[2]['score_review']) for x in (a,b)]])
                game=dict(id=gid,title=(a[1]['title']+' · '+a[6]['category']+' · '+a[6]['horizon'] if futures.scope(a[6]) else a[1]['title']+' · '+a[6]['family']+' · '+a[6]['period']+(' · including OT/shootout' if a[6]['competition']=='NHL' and a[6]['stage']=='regular_season' else ' · including playoff OT' if a[6]['competition']=='NHL' else ' · including extra innings · action · game '+str(a[1]['game_number']) if a[6]['competition']=='MLB' else ' · including overtime' if a[6]['competition']=='NBA' and a[6]['period']=='full_game' else ' · including college overtime · '+a[1]['subdivisions'][a[1]['home']]+'/'+a[1]['subdivisions'][a[1]['away']]+' · site: '+a[1]['neutral_site'] if a[6]['competition']=='NCAAF' and a[6]['period']=='full_game' else ' · men Division I · two 20-minute halves + overtime · site: '+a[1]['neutral_site'] if a[6]['competition']=='NCAAB' and a[6]['period']=='full_game' else '')),scheduled_start=a[1]['scheduled_start'],teams=teams,sides=sides,
                    sources={x[0]:dict(event_id=x[1]['id'],market_id=x[2]['id']) for x in (a,b)},candidates=candidates,product_identity=a[6])
                if is_line:
                    game['score_reviews']={x[0]:deepcopy(x[2]['score_review']) for x in (a,b)}
                    game['product_identity']=dict(game['product_identity'],outcome_set={x[0]:deepcopy(x[2]['score_review']['descriptor']) for x in (a,b)})
                    if score_periods.scope(a[6]):game['title']=a[1]['title']+' · '+a[6]['family']+' · '+a[6]['period']+' · pregame · specified segment only; later scoring excluded'
                    if a[6]['competition']=='NCAAB' and a[6]['period']=='first_half':game['title']+=' · First half · first 20-minute half · men Division I · pregame · ties included; no second half or OT · '+a[6]['stage']+' · site: '+a[1]['neutral_site']
                    if a[6]['competition']=='NBA' and a[6]['period']=='first_half':game['title']+=' · First half · end of second quarter · pregame · ties included; no second half or OT · '+a[6]['stage']
                    if a[6]['competition']=='NFL' and not futures.scope(a[6]):game['title']+=(' · First half · pregame · ties included; no second half or OT' if a[6]['period']=='first_half' else ' · including overtime')+' · '+a[6]['stage']
                    if a[6]['competition']=='NCAAF' and a[6]['period']=='first_half':game['title']+=' · First half · pregame · ties included; no second half or OT · '+a[6]['stage']+' · '+a[1]['subdivisions'][a[1]['home']]+'/'+a[1]['subdivisions'][a[1]['away']]+' · site: '+a[1]['neutral_site']
                    if a[6]['competition']=='NHL' and not score_periods.scope(a[6]) and not futures.scope(a[6]):game['title']+=' · '+('shootout: one winner goal, counted once' if a[6]['stage']=='regular_season' else 'no shootout; all OT goals')
                    if a[6]['line'] is not None:game['title']+=' · line '+a[6]['line']+' '+a[6]['rules']['unit']
                games.append(game); points[gid]=dict(id=token,at=at,cards=[a[4],b[4]],label='Durable cutoff')
                if a[6]['competition']=='NHL' and not is_line:
                    game['nhl_reviews']={x[0]:deepcopy(x[2]['nhl_review']) for x in (a,b)}
                if a[6]['competition']=='MLB' and not is_line:
                    game['mlb_reviews']={x[0]:deepcopy(x[2]['mlb_review']) for x in (a,b)}
                if a[6]['competition']=='NBA' and not is_line:
                    game['nba_reviews']={x[0]:deepcopy(x[2]['nba_review']) for x in (a,b)}
                if a[6]['competition']=='NCAAF' and not is_line:
                    game['ncaaf_reviews']={x[0]:deepcopy(x[2]['ncaaf_review']) for x in (a,b)}
                if a[6]['competition']=='NCAAB' and not is_line:
                    game['ncaab_reviews']={x[0]:deepcopy(x[2]['ncaab_review']) for x in (a,b)}
                rows_by_game[gid]=[a[5],b[5]]
        paired={(v,ids['market_id']) for g in games for v,ids in g['sources'].items()}
        for record in catalog:
            if ((record.get('identity') or {}).get('competition') in ('NHL','MLB','NBA','NCAAF','NCAAB') or ((record.get('identity') or {}).get('competition')=='NFL' and ((record.get('identity') or {}).get('family') in ('spread','total') or (record.get('identity') or {}).get('period')=='first_half'))) and not record['reason'] and (record['source_id'],record['market_id']) not in paired:
                record['reason']='No other source has matching reviewed '+record['identity']['competition']+' event and settlement terms'
        from app.reference.product import at_cutoff
        refs=at_cutoff(self.references.values(),at)
        sources=[dict(source_id=s,venue_id=s,provider_id=self.inventory.get(s,{}).get('provider_id',s),origin_id=self.inventory.get(s,{}).get('origin_id',s),label=LABELS.get(s,s),role='prediction',state=self.inventory.get(s,{}).get('state','configured' if s in self.inventory else 'not_configured'),coverage=deepcopy(self.coverage_status.get(s)),catalog=deepcopy(self.inventory.get(s))) for s in dict.fromkeys([*LABELS,*self.inventory])]
        for source in sources:
            config=self.spec.get('native_sources',{}).get(source['source_id'],{})
            if self.qualification_failure and config.get('state')=='enabled':
                source['state']='discovery_failed'
                source['discovery_failure']={k:deepcopy(self.qualification_failure.get(k)) for k in ('reason','traversals','responses')}
            source['selected']=config.get('selected')
            source['environment']='synthetic ('+config.get('environment','unspecified')+' shape)' if self.spec.get('mode')=='mock' and config.get('environment') else config.get('environment')
            source['update_path']=self.inventory.get(source['source_id'],{}).get('update_path')
            if self.finished and source.get('coverage') and source['coverage'].get('state') in ('connected','awaiting_snapshot'):
                source['coverage']['state']='stopped'
        result=dict(schema_version=1,session_id=self.sid,data_mode='synthetic' if self.spec.get('mode')=='mock' else self.spec.get('mode'),view_mode=mode,state=state or ('saved' if self.finished else 'current' if mode=='current' else 'incomplete'),
            started_at=self.started,stopped_at=self.finished,stop_reason=self.stop_reason,durable_cursor=token,projection_revision=REVISION,mapping_revision=self.spec.get('mapping_revision'),
            last_update=self.last,sources=sources,market_catalog=catalog,references=refs,refresh=self.refresh,generation=self.generation,
            games=games,points=points,rows_by_game=rows_by_game,comparison_groups_beyond_limit=truncated)
        from app.dashboard.native_book_comparison import connect
        connect(self,result,at)
        if self.spec.get('future_qualification_policy'):
            if self.spec['future_qualification_policy']!='native-prerequisites-1':raise ValueError('Unsupported future qualification policy')
            result['future_qualification_contexts']=deepcopy(self.qualification_contexts)
        if self.spec.get('two_source_qualification'):result['qualification_fee_policy']='native-evidence-required'
        if self.resolutions:result['resolutions']=deepcopy(list(self.resolutions.values()))
        if self.aggregates or self.spec.get('source_session'):
            from app.reference.aggregate import augment
            augment(result,self.aggregates.values())
            if self.spec.get('source_session'):
                from app.collection.source_projection import current_aggregate
                current_aggregate(result,self.spec['source_session'],self.aggregate_status,at,list(self.aggregate_context.values()))
        if self.spec.get('v1_comparison_policy')in ('manual-comparison-1','manual-comparison-2'):
            from app.collection.v1_comparison import connect as manual_connect
            manual_connect(self,result,at)
        from app.dashboard.bounds import retained_bytes
        if retained_bytes(result)>32*1024*1024:raise ValueError('snapshot byte bound')
        return deepcopy(result)

    @staticmethod
    def sides(source,event,market,meta,registry=None):
        explicit=market.get('product_outcomes')
        if explicit:
            sides=explicit
        else:
            raw=json.loads(meta['market']['raw']['json_text'])
            from app.normalization.registry import Registry
            registry=registry or Registry.load()
            names={cid:registry.entities[cid]['name'] for cid in event['participants'].values()}
            if source=='kalshi':
                native=next(m for m in raw['markets'] if m['ticker']==market['id'])
                result=registry.resolve('team',native['yes_sub_title'],league='NFL')
                if result.canonical_id not in names: raise ValueError('unknown native participant')
                sides=[dict(native_id=s,participant=names[result.canonical_id],predicate='win' if s=='yes' else 'not_win',native_label=s.upper()) for s in ('yes','no')]
            elif source=='polymarket_us':
                candidates=raw.get('markets',[])+[m for e in raw.get('events',[]) for m in e.get('markets',[])]
                native=next(m for m in candidates if str(m['id'])==market['id'])
                sides=[]
                for s in native['marketSides']:
                    cid=event['participants'][s['team']['name']]
                    sides.append(dict(native_id=str(s['id']),participant=names[cid],predicate='win',native_label='Long' if s['long'] else 'Short'))
            else: raise ValueError('native outcome handler unsupported')
        return {source+':'+str(s['native_id'])+':'+stable([event['id'],market['id'],s['native_id']]):deepcopy(s) for s in sides}
