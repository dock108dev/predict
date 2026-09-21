from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import base64
import json
from pathlib import Path
import re
import uuid
from functools import lru_cache
from collections import OrderedDict

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg import sql

ROOT=Path(__file__).resolve().parents[2]
TABLES=('artifact','artifact_edge','capture_session','receipt','quote_observation',
        'metadata_version','calculation','calculation_receipt','candidate_observation','coverage_event')


def now(): return datetime.now(timezone.utc).isoformat()
def encoded(v):
    return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()

def exact_time(t):
    # Keep source fractional precision for clock ordering; PostgreSQL remains an index.
    match=re.fullmatch(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|[+-]\d\d:\d\d)',t)
    if not match: raise ValueError('ISO timestamp with explicit timezone required')
    whole=stamp(match[1]+match[3])-datetime(1970,1,1,tzinfo=timezone.utc)
    return Decimal(whole.days*86400+whole.seconds)+Decimal('0.'+(match[2] or '0'))
def hashed(v): return sha256(encoded(v)).hexdigest()
def stamp(t):
    d=datetime.fromisoformat(t.replace('Z','+00:00'))
    if d.utcoffset() is None: raise ValueError('timezone required')
    return d


def connect(database='prediction_arb'):
    if not database.startswith('prediction_arb'): raise ValueError('dedicated project databases only')
    return psycopg.connect(host=str(ROOT/'.local/pgsocket'),port=55432,user='prediction_arb',
        dbname=database,autocommit=True,row_factory=dict_row,connect_timeout=5,
        options='-c statement_timeout=30000 -c lock_timeout=5000')


@dataclass(frozen=True)
class CapturePolicy:
    max_receipts: int = 1000
    max_seconds: int = 60
    max_payload_bytes: int = 16*1024*1024
    max_total_bytes: int = 128*1024*1024
    max_audit_bytes: int = 32*1024*1024
    snapshot_seconds: int = 30
    # All supplied images retained within these bounds; no stream reconstruction claim.
    def __post_init__(self):
        if any(type(v) is not int or v<=0 for v in asdict(self).values()):
            raise ValueError('positive integer limits required')


@lru_cache(maxsize=64)
def immutable_query(table,cols,keys):
    return sql.SQL('INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}=EXCLUDED.{} WHERE {} RETURNING 1').format(
            sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,cols)),
            sql.SQL(',').join(sql.Placeholder() for _ in cols),sql.SQL(',').join(map(sql.Identifier,keys)),
            sql.Identifier(keys[0]),sql.Identifier(keys[0]),
            sql.SQL(' AND ').join(sql.SQL('{}.{} IS NOT DISTINCT FROM EXCLUDED.{}').format(
                sql.Identifier(table),sql.Identifier(c),sql.Identifier(c)) for c in cols))


class Store:
    def __init__(self, connection):
        self.db=connection;self.tree_cache=OrderedDict();self.tree_cache_bytes=0;self.precompiled={};self.precompiled_written=None

    def migrate(self):
        with self.db.transaction():
            self.db.execute('SELECT pg_advisory_xact_lock(120012)')
            self.db.execute('CREATE TABLE IF NOT EXISTS schema_migration(version text PRIMARY KEY, sha256 text NOT NULL)')
            for p in sorted((Path(__file__).parent/'migrations').glob('*.sql')):
                h=sha256(p.read_bytes()).hexdigest()
                old=self.db.execute('SELECT sha256 FROM schema_migration WHERE version=%s',(p.name,)).fetchone()
                if old:
                    if old['sha256']!=h: raise ValueError('applied migration changed')
                else:
                    self.db.execute(p.read_text())
                    self.db.execute('INSERT INTO schema_migration VALUES (%s,%s)',(p.name,h))

    def immutable(self, table, row, keys):
        """A retry must match every field; never silently accept identity collisions."""
        cols=list(row); params=[Jsonb(v) if isinstance(v,(dict,list)) else v for v in row.values()]
        query=immutable_query(table,tuple(cols),tuple(keys))
        if not self.db.execute(query,params).fetchone(): raise ValueError('stable identity reused with different content: '+table)

    def raw(self, body):
        h=sha256(body).hexdigest()
        self.immutable('artifact',dict(hash=h,content=body,kind='raw'),['hash'])
        return h

    def put(self, value):
        prepared=self.precompiled.get(sha256(encoded(value)).hexdigest()) if self.precompiled else None
        root,artifacts,edges=prepared if prepared is not None else self.compile(value)
        written=self.precompiled_written
        for h,body in artifacts.items():
            key=('artifact',h)
            if written is None or key not in written:
                self.immutable('artifact',dict(hash=h,content=body,kind='tree'),['hash'])
                if written is not None:written.add(key)
        for parent,child in edges:
            key=('edge',parent,child)
            if written is None or key not in written:
                self.immutable('artifact_edge',dict(parent=parent,child=child),['parent','child'])
                if written is not None:written.add(key)
        return root

    def compile(self, value):
        return self.compile_many([value])[0]

    def compile_many(self, values):
        """Compile shared audit/candidate objects once, with identical tree hashes.

        The memo lives only for this call. Dependencies are copied into each
        returned root so every prepared put remains independently complete.
        No memo entry ever represents a committed database write.
        """
        artifacts={};links={};memo={};leaves={}
        def node(v):
            container=isinstance(v,(dict,list,tuple))
            if container and id(v) in memo:return memo[id(v)]
            refs=[]
            if isinstance(v,dict):
                parts=[]
                for k,x in sorted(v.items()):
                    body,children=node(x);refs.extend(children)
                    parts.append(b'['+encoded(k)+b','+body+b']')
                body=b'["dict",['+b','.join(parts)+b']]'
            elif isinstance(v,(list,tuple)):
                parts=[]
                for x in v:
                    body,children=node(x);refs.extend(children);parts.append(body)
                body=b'["list",['+b','.join(parts)+b']]'
            else:
                key=(type(v),v)
                body=leaves.get(key)
                if body is None:
                    body=b'["value",'+encoded(v)+b']'
                    if len(body)<=2048 and len(leaves)<2048:leaves[key]=body
            if len(body)>4096:
                h=sha256(body).hexdigest();artifacts[h]=body;links[h]=set(refs)
                body=b'["ref",'+encoded(h)+b']';refs=[h]
            result=(body,refs)
            if container:memo[id(v)]=result
            return result
        roots=[]
        for value in values:
            body,refs=node(value)
            if not body.startswith(b'["ref",'):
                h=sha256(body).hexdigest();artifacts[h]=body;links[h]=set(refs)
            else:h=refs[0]
            roots.append(h)
        def closure(root):
            blobs={};edges=set();pending=[root]
            while pending:
                h=pending.pop()
                if h in blobs:continue
                blobs[h]=artifacts[h]
                for child in links[h]:edges.add((h,child));pending.append(child)
            return root,blobs,edges
        return [closure(root) for root in roots]

    def get(self, h):
        def expand(n):
            kind,v=n
            if kind=='ref':
                row=self.db.execute('SELECT content,kind FROM artifact WHERE hash=%s',(v,)).fetchone()
                if not row or sha256(bytes(row['content'])).hexdigest()!=v: raise ValueError('missing/corrupt artifact')
                if row['kind']!='tree': raise ValueError('expected tree')
                return expand(json.loads(bytes(row['content'])))
            if kind=='dict': return {k:expand(x) for k,x in v}
            if kind=='list': return [expand(x) for x in v]
            if kind=='value': return v
            raise ValueError('invalid tree tag')
        return expand(['ref',h])

    def start(self, environment, evidence_class, provenance, policy=None, session_id=None):
        policy=policy or CapturePolicy(); sid=session_id or str(uuid.uuid4())
        self.db.execute('INSERT INTO capture_session VALUES (%s,%s,%s,%s,NULL,%s,%s,%s)',
            (sid,environment,evidence_class,now(),'running',Jsonb(asdict(policy)),provenance))
        return sid

    def active(self, sid):
        row=self.db.execute('SELECT * FROM capture_session WHERE id=%s FOR NO KEY UPDATE',(sid,)).fetchone()
        if not row or row['state']!='running': raise ValueError('session is not running; start a new session')
        return row

    def event(self,sid,kind,detail,*,at=None,event_id=None):
        at=at or now()
        self.immutable('coverage_event',dict(session_id=sid,id=event_id or str(uuid.uuid4()),
            observed_at=stamp(at),original_time=at,kind=kind,detail=detail),['session_id','id'])

    def finish(self,sid,state='complete',reason='finite input exhausted'):
        if state not in ('complete','failed','interrupted'): raise ValueError('invalid shutdown state')
        with self.db.transaction():
            self.active(sid)
            self.event(sid,'shutdown',dict(state=state,reason=reason,censored=True))
            self.db.execute('UPDATE capture_session SET state=%s,ended_at=%s WHERE id=%s',(state,now(),sid))

    def interrupt(self,sid):
        # Explicit recovery for a known stopped collector; never resume its timeline.
        with self.db.transaction():
            self.active(sid)
            for path in (ROOT/'.local/failures').glob('*.json'):
                journal=json.loads(path.read_text())
                if journal['session_id']==sid:
                    self.event(sid,'failure',journal,at=journal['at'],event_id='journal:'+path.stem)
            self.event(sid,'restart',dict(reason='previous collector stopped; observation gap duration unknown',censored=True))
            self.finish(sid,'interrupted','explicit interrupted-session recovery')

    def metadata(self,sid,kind,native_key,value):
        with self.db.transaction():
            self.active(sid)
            h=self.put(value)
            if isinstance(value,dict) and 'raw_hash' in value:
                self.immutable('artifact_edge',dict(parent=h,child=value['raw_hash']),['parent','child'])
            self.immutable('metadata_version',dict(session_id=sid,kind=kind,native_key=native_key,
                hash=h),['session_id','kind','native_key','hash'])

    def receipt(self,sid,receipt_id,packet):
        """packet: exact raw bytes + normalized full image + explicit source scope.

        Each call commits atomically unless wrapped in an outer transaction. No receipt
        is omitted for BBO dedup; only immutable BBO artifacts are shared.
        """
        with self.db.transaction():
            session=self.active(sid)
            if (packet['environment'],packet['evidence_class'])!=(session['environment'],session['evidence_class']):
                raise ValueError('receipt scope mismatch')
            body=packet['raw']; t=packet['received_at']; exact_time(t)
            if not isinstance(body,bytes): raise ValueError('raw bytes required')
            if len(body)>session['config']['max_payload_bytes']: raise ValueError('payload limit')
            n=packet['normalized']
            if any(n.get(k,packet[k])!=packet[k] for k in ('environment','evidence_class')):
                raise ValueError('normalized scope mismatch')
            if any(not isinstance(packet[k],str) or not packet[k].strip() for k in ('venue','event_id','market_id','source')):
                raise ValueError('native references and source required')
            if len(encoded(n))>session['config']['max_payload_bytes']: raise ValueError('normalized image limit')
            normalized=self.put(n)
            # Preserve status, locks, units, reconstruction, qualification and clock problems.
            bbo=dict(n); bbo.pop('levels',None)
            bbo['source_time_text']=packet.get('source_time')
            bh=self.put(bbo)
            identity=(sid,packet['venue'],packet['market_id'])
            periodic=self.db.execute("SELECT received_at FROM receipt WHERE session_id=%s AND venue=%s AND market_id=%s AND snapshot_reason IN ('initial','periodic') ORDER BY received_at DESC LIMIT 1",identity).fetchone()
            prior=self.db.execute('SELECT bbo_hash,received_at,received_text FROM receipt WHERE session_id=%s AND venue=%s AND market_id=%s ORDER BY received_at DESC,id DESC LIMIT 1',identity).fetchone()
            old=self.db.execute('SELECT changed,snapshot_reason FROM receipt WHERE session_id=%s AND id=%s',(sid,receipt_id)).fetchone()
            changed=not prior or prior['bbo_hash']!=bh or exact_time(t)<exact_time(prior['received_text'])
            reason='initial' if not prior else 'periodic' if periodic and (stamp(t)-periodic['received_at']).total_seconds()>=session['config']['snapshot_seconds'] else 'bounded-full-context'
            if prior and exact_time(t)<exact_time(prior['received_text']) and not old:
                self.event(sid,'gap',dict(reason='receipt clock regressed',receipt_id=receipt_id),at=t,event_id='clock:'+receipt_id)
            row=dict(session_id=sid,id=receipt_id,received_at=stamp(t),received_text=t,
                source_time_text=packet.get('source_time'),venue=packet['venue'],event_id=packet['event_id'],
                market_id=packet['market_id'],source=packet['source'],raw_hash=self.raw(body),
                normalized_hash=normalized,bbo_hash=bh,changed=old['changed'] if old else changed,
                snapshot_reason=old['snapshot_reason'] if old else reason)
            self.immutable('receipt',row,['session_id','id'])
            for q in n.get('quotes',[]):
                if any(isinstance(q.get(k),(float,bool)) for k in ('ask','ask_size','bid','bid_size')):
                    raise ValueError('quote values require exact numeric text')
                self.immutable('quote_observation',dict(session_id=sid,receipt_id=receipt_id,side=q['side'],
                    **{k:Decimal(q[k]) if q.get(k) is not None else None for k in ('ask','ask_size','bid','bid_size')},
                    unit=q.get('unit'),state=n.get('state','unknown')),['session_id','receipt_id','side'])

    def calculation(self,sid,cid,audit,receipt_ids=()):
        from .replay import replay
        config=self.db.execute('SELECT config FROM capture_session WHERE id=%s',(sid,)).fetchone()
        if not config: raise ValueError('unknown session')
        if len(encoded(audit))>CapturePolicy(**config['config']).max_audit_bytes:
            raise ValueError('calculation audit exceeds declared bound')
        audit=json.loads(encoded(audit))
        replay(audit)  # Reject invalid/incomplete audit before writing anything.
        engine=audit['engine']
        report=audit['result'] if engine=='detector-capture-1' else None
        at=report['evaluation_time'] if report else audit['input']['evaluation_time']
        candidates=report['candidates'] if report else [audit]
        with self.db.transaction():
            session=self.active(sid)
            if report:
                scopes={(o['environment'],o['evidence_class']) for o in audit['input']['observations']}
            else:
                scopes={(w['observation']['environment'],w['observation']['evidence_class']) for w in audit['input']['ladders'] if w}
            if any(s!=(session['environment'],session['evidence_class']) for s in scopes): raise ValueError('calculation scope mismatch')
            ah=self.put(audit)
            self.immutable('calculation',dict(session_id=sid,id=cid,engine=engine,observed_at=stamp(at),observed_text=at,audit_hash=ah,receipt_ids=sorted(set(receipt_ids))),['session_id','id'])
            for rid in receipt_ids:
                self.immutable('calculation_receipt',dict(session_id=sid,calculation_id=cid,receipt_id=rid),['session_id','calculation_id','receipt_id'])
            if report:
                previous=self.db.execute('SELECT id FROM calculation WHERE session_id=%s AND engine=%s AND id!=%s ORDER BY observed_at DESC,id DESC LIMIT 1',(sid,engine,cid)).fetchone()
                seen={c['id'] for c in candidates}
                if previous:
                    for absent in self.db.execute('SELECT * FROM candidate_observation WHERE session_id=%s AND calculation_id=%s',(sid,previous['id'])).fetchall():
                        if absent['candidate_id'] in seen: continue
                        detail=dict(reason='candidate absent from complete detector evaluation; not an observed negative price',previous_calculation=previous['id'])
                        self.immutable('candidate_observation',dict(session_id=sid,calculation_id=cid,candidate_id=absent['candidate_id'],
                            observed_at=stamp(at),engine=engine,structural=False,conditional_positive=False,qualified=False,
                            state='not-observed',reasons=[detail['reason']],liquidity_families=absent['liquidity_families'],
                            result_hash=self.put(detail),changed=absent['state']!='not-observed'),['session_id','calculation_id','candidate_id'])
            for c in candidates:
                base=c if report else c['input']['base']
                calc=c.get('conditional_calculation') if report else c['solutions']['max_profit']['allocation']
                profit=calc.get('worst_case_profit') if calc else None
                positive=profit is not None and Decimal(profit)>0
                qualified=bool(c['qualified_modeled_arbitrage'] if report else calc['qualified_modeled_arbitrage'])
                state='qualified' if qualified else 'conditional-positive' if positive else 'unknown' if profit is None else 'observed-nonpositive'
                reasons=c['reasons']; families=[l['liquidity_family'] for l in base['legs']]
                # Ineligible is never relabeled an observed price-negative disappearance.
                blocking=('stale-','receipt-in-future','market-suspended','market-closed','market-unknown','market-preopen','market-settled','market-canceled','reconstruction-','locked-or-lock-status-unknown','source-time-problem','source-time-regressed','ask-unavailable','ask-observation-unavailable','conflicting-observations','fee-context-unavailable')
                if (reasons and profit is None) or any(any(tag in r for tag in blocking) for r in reasons):
                    state='unavailable-or-ineligible'
                structural=bool(report['matching']['pairs'][c['pair_id']]['structural_match']) if report else None
                ch=self.put(c)
                prior=self.db.execute('SELECT result_hash FROM candidate_observation WHERE session_id=%s AND candidate_id=%s AND engine=%s ORDER BY observed_at DESC,calculation_id DESC LIMIT 1',(sid,c['id'],engine)).fetchone()
                old=self.db.execute('SELECT changed FROM candidate_observation WHERE session_id=%s AND calculation_id=%s AND candidate_id=%s',(sid,cid,c['id'])).fetchone()
                self.immutable('candidate_observation',dict(session_id=sid,calculation_id=cid,candidate_id=c['id'],observed_at=stamp(at),engine=engine,
                    structural=structural,conditional_positive=positive,qualified=qualified,state=state,reasons=reasons,
                    liquidity_families=families,result_hash=ch,changed=old['changed'] if old else not prior or prior['result_hash']!=ch),['session_id','calculation_id','candidate_id'])

    def ingest(self,sid,packets):
        """Finite pull iterator; one in-flight receipt, synchronous backpressure.

        Database outage leaves 'running' visibly incomplete, plus a local failure journal.
        The journal contains identifiers/error type only, never bodies or credentials.
        """
        count=0; total=0
        try:
            session=self.db.execute('SELECT config,started_at FROM capture_session WHERE id=%s',(sid,)).fetchone()
            p=CapturePolicy(**session['config'])
            for rid,packet in packets:
                usage=self.db.execute('SELECT count(*) AS n,coalesce(sum(octet_length(a.content)),0) AS bytes FROM receipt r JOIN artifact a ON r.raw_hash=a.hash WHERE session_id=%s',(sid,)).fetchone()
                retry=self.db.execute('SELECT 1 FROM receipt WHERE session_id=%s AND id=%s',(sid,rid)).fetchone()
                if not retry and (usage['n']>=p.max_receipts or (datetime.now(timezone.utc)-session['started_at']).total_seconds()>=p.max_seconds or usage['bytes']+len(packet['raw'])>p.max_total_bytes):
                    self.event(sid,'limit',dict(reason='declared finite ingestion bound reached',next_receipt=rid,censored=True))
                    self.finish(sid,reason='declared limit reached; remaining input not observed')
                    return count
                self.receipt(sid,rid,packet); count+=1; total+=len(packet['raw'])
            return count
        except BaseException as exc:
            try:
                self.event(sid,'failure',dict(error_type=type(exc).__name__,last_committed_count=count,censored=True))
                self.finish(sid,'failed','ingestion stopped on failure')
            except Exception:
                try:
                    journal=ROOT/'.local/failures'; journal.mkdir(parents=True,exist_ok=True)
                    (journal/(str(uuid.uuid4())+'.json')).write_text(json.dumps(dict(session_id=sid,at=now(),error_type=type(exc).__name__,count=count)))
                except Exception as report_error:
                    from app.diagnostics import failure
                    failure(__name__, 'ingestion', exc)
                    failure(__name__, 'ingestion_failure_report', report_error)
            raise

    def replay_all(self):
        from .replay import replay
        count=0
        for row in self.db.execute('SELECT audit_hash FROM calculation').fetchall():
            replay(self.get(row['audit_hash'])); count+=1
        return count

    def summary(self):
        sessions=self.db.execute('SELECT id,environment,evidence_class,state,provenance FROM capture_session ORDER BY started_at,id').fetchall()
        counts={t:self.db.execute(sql.SQL('SELECT count(*) AS n FROM {}').format(sql.Identifier(t))).fetchone()['n'] for t in TABLES}
        return dict(sessions=sessions,counts=counts,replay='saved calculations and retained images only; no complete stream or exchange-event history')

    def history(self,sid,candidate_id):
        rows=self.db.execute('SELECT * FROM candidate_observation WHERE session_id=%s AND candidate_id=%s ORDER BY engine,observed_at,calculation_id',(sid,candidate_id)).fetchall()
        gaps=self.db.execute("SELECT original_time,kind,detail FROM coverage_event WHERE session_id=%s AND kind!='coverage' ORDER BY observed_at",(sid,)).fetchall()
        # Discrete historical imports have no continuous coverage guarantee. Never integrate
        # first-to-last wall time into profit survival; display individual censored samples.
        return dict(observations=rows,coverage=gaps,first_observed=min((r['observed_at'] for r in rows),default=None),
            last_observed=max((r['observed_at'] for r in rows),default=None),observed_duration_seconds='0',
            duration_basis='discrete samples only; intervals between samples unproven',censored=True,
            liquidity_note='Related liquidity families cannot be summed as independent profit.')

    def export(self,path):
        # Consistent entire-project bundle: no external capture paths needed to replay.
        def wire(v):
            if isinstance(v,(bytes,memoryview)): return {'bytes':base64.b64encode(v).decode()}
            if isinstance(v,datetime): return {'datetime':v.isoformat()}
            if isinstance(v,Decimal): return {'decimal':str(v)}
            return {'json':v}
        with self.db.transaction():
            self.db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            tables={t:[{k:wire(v) for k,v in r.items()} for r in self.db.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier(t))).fetchall()] for t in TABLES}
            migrations=self.db.execute('SELECT * FROM schema_migration ORDER BY version').fetchall()
        payload=dict(format='capture-bundle-1',migrations=migrations,tables=tables)
        Path(path).write_bytes(encoded(dict(sha256=hashed(payload),payload=payload)))

    def import_bundle(self,path):
        envelope=json.loads(Path(path).read_bytes()); payload=envelope['payload']
        if hashed(payload)!=envelope['sha256'] or payload['format']!='capture-bundle-1': raise ValueError('bundle mismatch')
        installed = self.db.execute('SELECT * FROM schema_migration ORDER BY version').fetchall()
        # Additive reference history does not reinterpret capture-bundle-1 tables.
        # Require an exact supported migration prefix: pre-E2, E2, E3, or current E4.
        # Additive reference/pricing tables do not reinterpret capture tables.
        supplied = payload['migrations']
        allowed_lengths = {3, 4, 5, len(installed)}
        if len(supplied) not in allowed_lengths or supplied != installed[:len(supplied)]:
            raise ValueError('migration mismatch')
        def unwire(v):
            if 'bytes' in v:return base64.b64decode(v['bytes'],validate=True)
            if 'datetime' in v:return stamp(v['datetime'])
            if 'decimal' in v:return Decimal(v['decimal'])
            return v['json']
        with self.db.transaction():
            if any(self.db.execute(sql.SQL('SELECT 1 FROM {} LIMIT 1').format(sql.Identifier(t))).fetchone() for t in TABLES):
                raise ValueError('restore requires empty disposable project database')
            for t in TABLES:
                for raw in payload['tables'][t]:
                    row={k:unwire(v) for k,v in raw.items()}
                    if t=='artifact' and sha256(row['content']).hexdigest()!=row['hash']: raise ValueError('artifact hash mismatch')
                    cols=list(row)
                    self.db.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(sql.Identifier(t),sql.SQL(',').join(map(sql.Identifier,cols)),sql.SQL(',').join(sql.Placeholder() for _ in cols)),
                        [Jsonb(v) if isinstance(v,(dict,list)) else v for v in row.values()])
            self.replay_all()
