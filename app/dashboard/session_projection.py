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
        season=event.get('season',event.get('scheduled_start','')[:4]), stage=event.get('stage'),
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
        self.sid=None; self.spec={}; self.inventory={}; self.generation=None
        self.metadata={}; self.books={}; self.health={}; self.invalid=set(); self.references={}
        self.coverage_status={}; self.refresh=None; self.legacy=None; self.last_row_hash=None; self.sizes={}; self.safety={}

    def apply(self,row,cursor=None):
        # Match journal JSON types at the acknowledged live boundary.
        row=json.loads(json.dumps(row,default=str))
        cursor=self.cursor+1 if cursor is None else cursor
        if cursor==self.cursor:
            if stable(row)!=self.last_row_hash:raise ValueError('conflicting cursor')
            return
        if cursor!=self.cursor+1: raise ValueError('noncontiguous durable cursor')
        typ=row['type']; source=row.get('source'); at=row['observed_at']
        if typ in ('prediction_book','market_selected','coverage_inventory','product_reference'):
            data=row.get('book',row.get('market',{}));ref=data.get('raw',{}).get('ref',{})
            size_key=(typ,source,ref.get('event_id'),ref.get('market_id'),row.get('reference',{}).get('id'))
            size=len(json.dumps(row).encode())
            if sum(self.sizes.values())-self.sizes.get(size_key,0)+size>16*1024*1024:raise ValueError('projection byte bound')
            self.sizes[size_key]=size
        if self.finished: raise ValueError('observation after terminal')
        if self.sid and row['session_id']!=self.sid: raise ValueError('session identity changed')
        if typ=='session_started':
            if self.started: raise ValueError('duplicate session start')
            self.sid=row['session_id']; self.started=at; self.spec=deepcopy(row['spec'])
        elif typ=='multi_game_selection': self.legacy=deepcopy(row)
        elif typ=='coverage_inventory':
            if row.get('previous_generation')!=self.generation: raise ValueError('inventory dependency mismatch')
            cats=deepcopy(row['inventory'])
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
                if data['sync']=='synchronized' and self.health.get(key,{}).get('state')=='connected': self.invalid.discard(key)
        elif typ=='source_health':
            for key in self.memberships() | dict.fromkeys(self.books):
                if key[0]!=source: continue
                if row.get('market_ids') is not None and key[2] not in row['market_ids']: continue
                if row.get('stream_group') and row.get('market_ids') is None and self.books.get(key,{}).get('stream_group')!=row['stream_group']: continue
                self.health[key]={k:deepcopy(row.get(k)) for k in ('source','state','gap_reason','market_ids','observed_at','stream_group')}
                if row['state']!='connected': self.invalid.add(key)
        elif typ=='product_coverage_status':
            self.coverage_status=deepcopy(row['coverage']); self.refresh=deepcopy(row.get('refresh'));self.safety=deepcopy(row.get('safety_exclusions',{}))
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
        from app.normalization.nhl import inventory_gaps, winner_review, event_key
        nhl_gaps=inventory_gaps(self.inventory)
        from app.normalization import mlb,nba,ncaaf,ncaab,nfl_lines
        mlb_gaps=mlb.inventory_gaps(self.inventory)
        nba_gaps=nba.inventory_gaps(self.inventory)
        ncaaf_gaps=ncaaf.inventory_gaps(self.inventory)
        ncaab_gaps=ncaab.inventory_gaps(self.inventory)
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
                if ident and not ((ident['competition'] in ('NFL','NCAAF') and ident['sport'] in ('american_football','football')) or (ident['competition']=='MLB' and ident['sport']=='baseball') or (ident['competition'] in ('NBA','NCAAB') and ident['sport']=='basketball') or (ident['competition']=='NHL' and ident['sport'] in ('hockey','ice_hockey'))):reason=reason or 'unsupported sport or competition (B5)'
                if e and ident['competition']=='NHL':reason=reason or nhl_gaps.get((source,e['id']))
                if e and ident['competition']=='MLB':reason=reason or mlb_gaps.get((source,e['id']))
                if e and ident['competition']=='NBA':reason=reason or nba_gaps.get((source,e['id']))
                if e and ident['competition']=='NCAAF':reason=reason or ncaaf_gaps.get((source,e['id']))
                if e and ident['competition']=='NCAAB':reason=reason or ncaab_gaps.get((source,e['id']))
                is_line=bool(ident and ident['competition'] in ('NBA','NCAAB','NFL','NCAAF','MLB') and ident['family'] in ('spread','total'))
                if is_line and ident['competition']=='NFL':reason=reason or nfl_line_gaps.get((source,e['id']))
                if ident and ((ident['family']!='moneyline' and not is_line) or ident['period']!='full_game'): reason=reason or 'unsupported family or period (B5)'
                if m['id'] not in cat.get('selection',{}).get('ids',[]): reason=reason or 'not selected'
                record=dict(source_id=source,event_id=m['event_id'],market_id=m['id'],identity=ident,title=(e or {}).get('title'),reason=reason,health=deepcopy(self.health.get(key)),native=deepcopy(m))
                if 'display_prices' in m:
                    record.update(received_at=m.get('received_at'),update_path=cat.get('update_path'))
                retained=self.books.get(key)
                if retained:
                    record.update(received_at=retained['book']['raw']['received_at'],update_path=retained.get('update_path','native stream'),
                        quantity_unit=retained['book']['quantity_unit'],quotes=[deepcopy(q) for p in retained['packets'] for q in p['normalized']['quotes']])
                catalog.append(record)
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
                        review=review_fn(e,m,meta,source,self.spec.get('mode'))
                        # Additive projection only: retained event/native IDs are untouched.
                        canonical=key_fn(e)
                        ident=dict(ident,event=canonical,sport={'NFL':'american_football','MLB':'baseball','NBA':'basketball','NHL':'ice_hockey','NCAAF':'american_football','NCAAB':'basketball'}[ident['competition']],scheduled_start=canonical[3])
                        if is_line:
                            ident.update(line=review['canonical']['threshold'],subject=e['home'] if ident['family']=='spread' else 'combined',rules={'version':'score-lines-1','unit':review['descriptor']['unit'],'domain':review['canonical']['domain'],'overtime':'included','completion':review['terms']['completion']})
                        if is_line and ident['competition']=='NFL':
                            ident['rules'].update({k:review['descriptor'][k] for k in ('overtime_format','tied_score','normal_completion')})
                        if is_line and ident['competition']=='NCAAF':
                            ident['rules'].update({k:review['descriptor'][k] for k in ('overtime_format','overtime_scoring','tied_score','normal_completion','subdivision_scope')})
                        if is_line and ident['competition']=='MLB':
                            ident['rules'].update({k:review['descriptor'][k] for k in ('extra_innings','pitcher_conditions','normal_completion','tied_score','completion_scope')})
                        record['identity']=ident
                    except (ValueError,KeyError,TypeError,AttributeError,IndexError,StopIteration) as exc:
                        record['reason']=str(exc);continue
                try: sides=self.sides(source,e,m,meta)
                except (KeyError,ValueError,StopIteration,TypeError): record['reason']='unsupported outcome identity'; continue
                if len(sides)!=2: record['reason']='unsupported outcome set'; continue
                book=self.books.get(key); age=None if not book else str(Decimal(str((stamp(at)-stamp(book['book']['raw']['received_at'])).total_seconds())))
                connection=self.health.get(key,{}).get('state','awaiting_snapshot')
                if key in self.invalid and connection=='connected': connection='resynchronization_required'
                try: formatted=format_book(book,{source:{s['native_id']:(s['participant'],s.get('native_label',s['native_id'])) for s in sides.values()}}) if book else None
                except (ValueError,KeyError,StopIteration,TypeError):
                    record['reason']='unsupported book packet';continue
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
                is_line=a[6]['family'] in ('spread','total')
                if not is_line and len(teams)!=2: continue
                def winner(s): return next(t for t in teams if t!=s['participant']) if s['predicate']=='not_win' else s['participant']
                candidates=[]
                for x,y in product(a[3],b[3]):
                    if is_line or winner(sides[x])!=winner(sides[y]): candidates.append((stable([x,y]),winner(sides[x])+' + '+winner(sides[y]),(x,y)))
                if not candidates: continue
                if len(games)>=64:
                    truncated+=1;continue
                gid=stable([group,sorted([list((x[0],x[1]['id'],x[2]['id'])) for x in (a,b)])])
                if is_line:gid=stable([gid,[(x[0],x[2]['score_review']) for x in (a,b)]])
                game=dict(id=gid,title=a[1]['title']+' · '+a[6]['family']+' · '+a[6]['period']+(' · including OT/shootout' if a[6]['competition']=='NHL' and a[6]['stage']=='regular_season' else ' · including playoff OT' if a[6]['competition']=='NHL' else ' · including extra innings · action · game '+str(a[1]['game_number']) if a[6]['competition']=='MLB' else ' · including overtime' if a[6]['competition']=='NBA' else ' · including college overtime · '+a[1]['subdivisions'][a[1]['home']]+'/'+a[1]['subdivisions'][a[1]['away']]+' · site: '+a[1]['neutral_site'] if a[6]['competition']=='NCAAF' else ' · men Division I · two 20-minute halves + overtime · site: '+a[1]['neutral_site'] if a[6]['competition']=='NCAAB' else ''),scheduled_start=a[1]['scheduled_start'],teams=teams,sides=sides,
                    sources={x[0]:dict(event_id=x[1]['id'],market_id=x[2]['id']) for x in (a,b)},candidates=candidates,product_identity=a[6])
                if is_line:
                    game['score_reviews']={x[0]:deepcopy(x[2]['score_review']) for x in (a,b)}
                    game['product_identity']=dict(game['product_identity'],outcome_set={x[0]:deepcopy(x[2]['score_review']['descriptor']) for x in (a,b)})
                    if a[6]['competition']=='NFL':game['title']+=' · including overtime · '+a[6]['stage']
                    game['title']+=' · line '+a[6]['line']+' '+a[6]['rules']['unit']
                games.append(game); points[gid]=dict(id=token,at=at,cards=[a[4],b[4]],label='Durable cutoff')
                if a[6]['competition']=='NHL':
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
            if ((record.get('identity') or {}).get('competition') in ('NHL','MLB','NBA','NCAAF','NCAAB') or ((record.get('identity') or {}).get('competition')=='NFL' and (record.get('identity') or {}).get('family') in ('spread','total'))) and not record['reason'] and (record['source_id'],record['market_id']) not in paired:
                record['reason']='No other source has matching reviewed '+record['identity']['competition']+' event and settlement terms'
        from app.reference.product import at_cutoff
        refs=at_cutoff(self.references.values(),at)
        sources=[dict(source_id=s,venue_id=s,provider_id=self.inventory.get(s,{}).get('provider_id',s),origin_id=self.inventory.get(s,{}).get('origin_id',s),label=LABELS.get(s,s),role='prediction',state=self.inventory.get(s,{}).get('state','configured' if s in self.inventory else 'not_configured'),coverage=deepcopy(self.coverage_status.get(s)),catalog=deepcopy(self.inventory.get(s))) for s in dict.fromkeys([*LABELS,*self.inventory])]
        for source in sources:
            config=self.spec.get('native_sources',{}).get(source['source_id'],{})
            source['selected']=config.get('selected')
            source['environment']='synthetic ('+config.get('environment','unspecified')+' shape)' if self.spec.get('mode')=='mock' and config.get('environment') else config.get('environment')
            source['update_path']=self.inventory.get(source['source_id'],{}).get('update_path')
            if self.finished and source.get('coverage') and source['coverage'].get('state') in ('connected','awaiting_snapshot'):
                source['coverage']['state']='stopped'
        result=dict(schema_version=1,session_id=self.sid,data_mode='synthetic' if self.spec.get('mode')=='mock' else self.spec.get('mode'),view_mode=mode,state=state or ('saved' if self.finished else 'current' if mode=='current' else 'incomplete'),
            started_at=self.started,stopped_at=self.finished,stop_reason=self.stop_reason,durable_cursor=token,projection_revision=REVISION,mapping_revision=self.spec.get('mapping_revision'),
            last_update=self.last,sources=sources,market_catalog=catalog,references=refs,refresh=self.refresh,generation=self.generation,
            games=games,points=points,rows_by_game=rows_by_game,comparison_groups_beyond_limit=truncated)
        from app.dashboard.bounds import retained_bytes
        if retained_bytes(result)>32*1024*1024:raise ValueError('snapshot byte bound')
        return deepcopy(result)

    @staticmethod
    def sides(source,event,market,meta):
        explicit=market.get('product_outcomes')
        if explicit:
            sides=explicit
        else:
            raw=json.loads(meta['market']['raw']['json_text'])
            from app.normalization.registry import Registry
            registry=Registry.load()
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
