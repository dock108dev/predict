"""Durable source-local inputs, stable game snapshots and atomic saved results.

Payload strings preserve Decimal spelling and original native units. Journal
records are parsed/redacted aggregate batches or reconstructed books, not wire.
No provider access, quota mutation or source-clock renewal occurs in this module.
"""
import base64
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from .store import Store, connect, encoded, hashed, stamp, exact_time

VERSION='predict-stored-game-1'
MAX_PAYLOAD=8*1024*1024


def wire(v):return encoded(v).decode()
def utc():return datetime.now(timezone.utc).isoformat()

def engine_binding():
    root=Path(__file__).resolve().parents[2]
    paths=['app/comparison/estimated_ev.py','app/comparison/estimated_pair.py','app/comparison/estimated_consumer.py','app/comparison/estimated_content.py','app/comparison/estimated_templates.py','app/fees/engine.py','app/fixtures/estimated-content-v1.json','app/fixtures/comparison-source-rules-v1.json','app/fixtures/comparison-selected-applicability-v1.json']
    paths += ['app/comparison/estimated_policy.py','app/comparison/effective_policy.py','app/comparison/benchmark.py','app/comparison/requested_sizing.py','app/comparison/financial_metrics.py','app/comparison/source_inputs.py','app/comparison/current_metrics.py','app/comparison/current_dependencies.py','app/comparison/domain.py']
    paths += ['app/storage/comparison_board.py','app/dashboard/comparison_board.py','app/dashboard/comparison_board_api.py','app/dashboard/query_policy.py','app/collection/current_database.py','app/comparison/calculation_control.py','app/normalization/registry.py']
    paths += ['app/comparison/calculation_availability.py','app/storage/current_rows.py','app/storage/schedule_metadata.py','app/dashboard/comparison_slate.py']
    paths += ['app/comparison/combined_inputs.py','app/comparison/combined_native.py','app/comparison/occurrence_matching.py','app/collection/current_sink.py','app/collection/current_aggregate_admission.py','app/dashboard/current_normalized.py','app/collection/current_comparison_inputs.py','app/storage/current_games.py']
    paths += ['app/collection/current_aggregate.py','app/reference/odds_sample.py','app/reference/odds_acquire.py','app/comparison/coverage.py']
    paths += ['app/comparison/readiness_encoding.py','app/comparison/scanner_readiness.py','app/comparison/readiness_inputs.py','app/storage/scanner_readiness.py','app/fixtures/scanner-readiness-policy-v1.json']
    paths += ['app/comparison/scanner_finance.py','app/comparison/scanner_projection.py','app/storage/scanner_publication.py','app/dashboard/scanner_api.py']
    paths += ['app/comparison/scanner_ticket_finance.py','app/comparison/scanner_tickets.py','app/comparison/scanner_destinations.py','app/dashboard/scanner_ticket_api.py','app/fixtures/scanner-destinations-v1.json']
    paths += ['app/comparison/scanner_transitions.py','app/comparison/scanner_summaries.py','app/storage/scanner_preparation.py']
    paths += ['app/storage/scanner_latest.py','app/storage/latest_board.py','app/storage/board_capture.py','app/storage/board_view.py','app/storage/selected_frame.py','app/storage/slate_reads.py','app/dashboard/read_work.py',
              'app/collection/runtime_status.py','app/collection/runtime_client.py','app/collection/data_runtime.py']
    paths += ['app/collection/selected_fee_operation.py','app/collection/current_native.py','app/collection/current_native_catalog.py',
              'app/collection/native_fee_metadata.py','app/collection/native_http_transport.py',
              'app/collection/prediction_producer.py']
    paths += ['app/collection/coverage.py','app/collection/admission_enrichment.py','app/collection/v1_comparison.py']
    paths += ['app/comparison/net_ev.py','app/comparison/net_costs.py','app/comparison/modeled_winner.py','app/comparison/bound_finance.py','app/comparison/event_eligibility.py','app/collection/prediction_discovery.py','app/collection/native_score_binding.py','app/fixtures/native-admission-identity-v2.json']
    paths += ['app/storage/observation_publication.py','app/comparison/native_scoring_scope.py','app/comparison/same_outcome.py','app/comparison/sporting_scope.py',
              'app/normalization/registry-v1.json','app/fixtures/comparison-event-links-v1.json',
              'app/fixtures/native-scoring-scope/selected-series-fee-and-ot-resolution.json',
              'app/fixtures/native-scoring-scope/kalshi-football.pdf']
    return hashed({p:sha256((root/p).read_bytes()).hexdigest() for p in paths})


def observation_binding():
    """Only source admission, identity, matching and price-comparison semantics."""
    root=Path(__file__).resolve().parents[2]
    paths=('app/comparison/combined_native.py','app/comparison/native_scoring_scope.py','app/comparison/same_outcome.py','app/comparison/sporting_scope.py','app/comparison/source_clock.py',
        'app/comparison/occurrence_matching.py','app/comparison/event_links.py',
        'app/collection/coverage.py','app/collection/admission_enrichment.py',
        'app/collection/v1_comparison.py','app/collection/current_sink.py',
        'app/dashboard/current_normalized.py','app/dashboard/current_contract.py','app/dashboard/comparison_board.py',
        'app/storage/current_rows.py','app/storage/schedule_metadata.py','app/storage/comparison_board.py','app/storage/observation_publication.py','app/storage/latest_board.py',
        'app/normalization/registry.py','app/comparison/event_eligibility.py',
        'app/collection/prediction_discovery.py','app/collection/native_score_binding.py','app/fixtures/native-admission-identity-v2.json',
        'app/normalization/registry-v1.json','app/fixtures/comparison-event-links-v1.json')
    # Native scoring registry entries and retained governing rules have scoped
    # dependencies in observation_publication. A data edit for another native
    # outcome must not withdraw every unchanged game.
    return hashed({p:sha256((root/p).read_bytes()).hexdigest() for p in paths})


class GameStore:
    def __init__(self, db):self.db=db

    def immutable(self, table, key, row):
        # DO NOTHING does not fire the immutable UPDATE trigger on a retry.
        from psycopg import sql
        from .payload_codec import TABLES
        from .domain_history import encode
        cols=list(row)
        select=sql.SQL('SELECT * FROM {} WHERE {}=%s').format(sql.Identifier(table),sql.Identifier(key))
        if table in TABLES:
            saved=self.db.execute(select,(row[key],)).fetchone()
            if saved:
                if any(saved[c]!=row[c] for c in cols if c not in ('retained_at','as_of','calculated_at')):
                    raise ValueError('conflicting immutable identity: '+table)
                return
        stored=dict(row)
        if table in TABLES:stored['payload']=encode(row['payload'],self.db,table)
        self.db.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO NOTHING').format(
            sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,cols)),
            sql.SQL(',').join(sql.Placeholder() for _ in cols),sql.Identifier(key)),list(stored.values()))
        saved=self.db.execute(select,(row[key],)).fetchone()
        if any(saved[c]!=row[c] for c in cols if c not in ('retained_at','as_of','calculated_at')):
            raise ValueError('conflicting immutable identity: '+table)

    def envelope(self, record, identity=None):
        payload=wire(record)
        if len(payload.encode())>MAX_PAYLOAD:raise ValueError('current_envelope_byte_cap')
        h=hashed(record);identity=identity or h
        self.immutable('current_envelope','id',dict(id=identity,payload_sha256=h,payload=payload,
            source=record['source'],kind=record['kind'],retained_at=record['retained_at']))
        return identity

    def source(self, source, kind, native, at, eid, payload, *, received_at):
        # The secondary order is the original provider receipt, separately from
        # local retention/read/import time. Provider/source clocks stay untouched.
        observed=exact_time(at);received=exact_time(received_at);body=wire(payload)
        with self.db.transaction():
            self.db.execute('SELECT pg_advisory_xact_lock(901091)')
            old=self.db.execute('''SELECT observed_order,received_order,payload FROM current_source_projection
              WHERE source=%s AND kind=%s AND native_id=%s FOR UPDATE''',(source,kind,native)).fetchone()
            if old and old['received_order'] is None:
                raise ValueError('current_source_receipt_backfill_required')
            if old and (old['observed_order'],old['received_order'])==(observed,received) and old['payload']!=body:
                raise ValueError('current_source_equal_clock_conflict')
            row=self.db.execute('''INSERT INTO current_source_projection
              (source,kind,native_id,observed_at,envelope_id,payload,observed_order,received_order)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
              ON CONFLICT(source,kind,native_id) DO UPDATE SET observed_at=excluded.observed_at,
              envelope_id=excluded.envelope_id,payload=excluded.payload,observed_order=excluded.observed_order,
              received_order=excluded.received_order
              WHERE (excluded.observed_order,excluded.received_order)>
                (current_source_projection.observed_order,current_source_projection.received_order)
              RETURNING native_id''',(source,kind,native,at,eid,body,observed,received)).fetchone()
            return row is not None

    def import_record(self, record, identity=None):
        with self.db.transaction():
            from .comparison_board import LOCK
            self.db.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            eid=self.envelope(record,identity);v=record['value'];source=record['source'];kind=record['kind']
            affected=set()
            if kind=='aggregate_batch':
                body=base64.b64decode(v['body_b64'],validate=True)
                if sha256(body).hexdigest()!=v['body_sha256']:raise ValueError('aggregate_receipt_hash_conflict')
                from app.collection.current_aggregate_admission import admit
                rows=[]
                for venue in ('novig','prophetx','pinnacle'):
                    rows.extend(admit(body,v['sport'],v['received_at'],venue=venue))
                for row in rows:
                    q=row['quote'];key=q['source']['native_event_id']
                    native=hashed([q['venue'],key,q['source']['native_market_id'],q['source']['native_outcome_id']])
                    # Unknown source clocks sort by their original receipt, never insertion.
                    at=q['times']['source_at'] or q['times']['received_at']
                    changed=self.source(source,'quote',native,at,eid,row,received_at=q['times']['received_at'])
                    if changed and v['sport']=='NFL':affected.add(source+':'+key)
            elif kind=='catalog':
                if self.source(source,'catalog',source,record['retained_at'],eid,v['inventory'],received_at=record['retained_at']):
                    affected.update(source+':'+e['id'] for e in v['inventory']['events'] if e.get('competition')=='NFL')
            elif kind=='admitted_books':
                for o in v['observations']:
                    book=o['book'];ref=book['raw']['ref']
                    if ref['venue']!=source:raise ValueError('native_book_source_conflict')
                    if self.source(source,'book',ref['event_id']+':'+ref['market_id'],
                            book['raw'].get('exchange_at') or book['raw']['received_at'],eid,o,
                            received_at=book['raw']['received_at']):
                        affected.add(source+':'+ref['event_id'])
            return affected

    def catch_up(self, path, *, records=16, deadline=None):
        from time import monotonic
        from app.comparison.calculation_control import checkpoint
        path=Path(path);name=str(path.resolve())
        cursor=self.db.execute('SELECT byte_offset FROM current_import_cursor WHERE path=%s',(name,)).fetchone()
        offset=cursor['byte_offset'] if cursor else 0;affected=set();count=0
        if not path.exists():return affected,0
        if path.stat().st_size<offset:raise ValueError('journal_truncated')
        with path.open('rb') as stream:
            stream.seek(offset)
            for _ in range(records):
                checkpoint()
                if deadline is not None and monotonic()>=deadline:break
                start=stream.tell();line=stream.readline(MAX_PAYLOAD+1)
                if not line:break
                if len(line)>MAX_PAYLOAD:raise ValueError('journal_record_cap')
                if not line.endswith(b'\n'):break # incomplete durable tail remains visible
                record=json.loads(line)
                if record.get('schema')=='predict-domain-journal-2':
                    from app.collection.current_journal_domains import unpack_record
                    record=unpack_record(record,path.parent)
                with self.db.transaction():
                    affected.update(self.import_record(record,hashed([name,start])))
                    self.db.execute('''INSERT INTO current_import_cursor VALUES (%s,%s)
                     ON CONFLICT(path) DO UPDATE SET byte_offset=excluded.byte_offset''',(name,stream.tell()))
                count+=1
                checkpoint()
        return affected,count

    def project(self, key):
        source,native=key.split(':',1)
        if source=='the_odds_api':
            rows=self.db.execute("""SELECT payload,envelope_id FROM current_source_projection
              WHERE source=%s AND kind='quote'
                AND payload::jsonb->'quote'->'source'->>'native_event_id'=%s""",(source,native)).fetchall()
            records=[json.loads(r['payload']) for r in rows]
        else:
            cat=self.db.execute("SELECT payload,envelope_id FROM current_source_projection WHERE source=%s AND kind='catalog'",(source,)).fetchone()
            if not cat:return None
            inventory=json.loads(cat['payload']);events=[e for e in inventory['events'] if e['id']==native]
            if not events:return None
            inventory=dict(inventory,events=events,markets=[m for m in inventory['markets'] if m['event_id']==native])
            from app.dashboard.session_projection import SessionProjection
            from app.collection.current_sink import normalized_records
            from app.collection.current_policy import DEFAULT
            reducer=SessionProjection();reducer.inventory={source:inventory}
            rows=self.db.execute("SELECT payload,envelope_id FROM current_source_projection WHERE source=%s AND kind='book'",(source,)).fetchall()
            rows=[r for r in rows if json.loads(r['payload'])['book']['raw']['ref']['event_id']==native]
            for row in rows:reducer.reduce_observation(json.loads(row['payload']))
            from app.dashboard.current_state import unavailable
            records,_=normalized_records(reducer,unavailable()['source_status'],{})
            rows.append(cat)
        if not records:return None
        # Keep provider games distinct. This does not assert a native hedge join.
        quote_records=[r for r in records if r['quote']['venue']!='pinnacle']
        refs=[r for r in records if r['quote']['venue']=='pinnacle']
        if not quote_records:return None
        from app.collection.current_benchmark import attach
        attach(quote_records,refs)
        for r in quote_records:
            r.pop('_instrument',None);r.pop('_fingerprint',None)
        originals=dict(records=quote_records,references=refs,envelope_ids=sorted({r['envelope_id'] for r in rows}),
            representation='parsed/redacted aggregate batches and reconstructed books; not original wire bytes')
        version=hashed(originals)
        payload=dict(version=VERSION,game_key=key,input_version=version,inputs=originals,
            event=quote_records[0]['event'])
        self.db.execute('''INSERT INTO current_game_projection VALUES (%s,%s,%s,%s)
         ON CONFLICT(game_key) DO UPDATE SET input_version=excluded.input_version,payload=excluded.payload,
          updated_at=excluded.updated_at WHERE current_game_projection.input_version<>excluded.input_version''',
            (key,version,wire(payload),utc()))
        return version

    def combined_envelopes(self):
        """Read current projected envelope associations in one SQL snapshot.

        Historical replay supplies retained envelopes to build() explicitly.
        Never scan/refresh providers or replace source-local projections.
        """
        originals,_,_=self.combined_read_capture()
        return originals

    def combined_capture(self):
        """One statement binds current per-member projections to full originals."""
        originals,associations,_=self.combined_read_capture()
        return originals,associations

    def combined_read_capture(self):
        """Capture exact current projections and full originals in one statement.

        The ordinary read context uses admitted event records rather than
        replaying every game in every retained aggregate batch. Immutable
        receipt bytes and the exact current association remain independently
        checked; this performs no capture/publication or provider operation.
        """
        from .comparison_board import MAX_ASSOCIATIONS
        from .payload_codec import logical_size_sql
        from psycopg import sql
        captured=self.db.execute(sql.SQL('''WITH catalogs AS MATERIALIZED (
          SELECT source,payload::jsonb AS inventory FROM current_source_projection
          WHERE source IN (%s,%s) AND kind='catalog'
          ), winners AS MATERIALIZED (
          SELECT c.source,event->>'id' AS event_id,market->>'id' AS market_id
          FROM catalogs c CROSS JOIN LATERAL jsonb_array_elements(c.inventory->'events') event
            CROSS JOIN LATERAL jsonb_array_elements(c.inventory->'markets') market
          WHERE event->>'competition'='NFL' AND market->>'event_id'=event->>'id'
            AND ((market->>'market_type'='moneyline' AND market->>'period'='full_game')
              OR (market->'v1_raw_binding'->'identity'->>'family'='moneyline'
                AND market->'v1_raw_binding'->'identity'->>'period'='full_game'))
          ), p AS MATERIALIZED (
          SELECT p.* FROM current_source_projection p WHERE
            (p.source=%s AND p.kind='quote'
              AND p.payload::jsonb->'event'->>'competition'='NFL'
              AND p.payload::jsonb->'market_identity'->>'family'='moneyline'
              AND p.payload::jsonb->'market_identity'->>'period'='full_game')
            OR (p.source IN (%s,%s) AND (p.kind='catalog'
              OR (p.kind='book' AND EXISTS (
                SELECT 1 FROM winners w WHERE w.source=p.source
                  AND p.native_id=w.event_id||':'||w.market_id
                  AND w.event_id=p.payload::jsonb->'book'->'raw'->'ref'->>'event_id'
                  AND w.market_id=p.payload::jsonb->'book'->'raw'->'ref'->>'market_id'))))
          LIMIT %s
          ), e AS MATERIALIZED (
          SELECT e.id,e.payload_sha256,e.payload FROM
            (SELECT DISTINCT envelope_id FROM p LIMIT 257) originals
            JOIN current_envelope e ON e.id=originals.envelope_id
          ), bounds AS (
          SELECT (SELECT count(*) FROM p) AS associations,
            COALESCE((SELECT sum(octet_length(payload)) FROM p),0) AS projection_bytes,
            (SELECT count(*) FROM e) AS envelopes,
            COALESCE((SELECT sum({logical_size}) FROM e),0) AS envelope_bytes
          )
          SELECT NULL::text AS id,NULL::text AS payload_sha256,NULL::text AS payload,
            NULL::json AS projections,row_to_json(bounds) AS bounds FROM bounds
          UNION ALL
          SELECT e.id,e.payload_sha256,e.payload,
            json_agg(json_build_object('source',p.source,'kind',p.kind,
              'native_id',p.native_id,'envelope_id',p.envelope_id,'payload',p.payload)
              ORDER BY p.source,p.kind,p.native_id) AS projections,NULL::json AS bounds
          FROM p JOIN e ON e.id=p.envelope_id CROSS JOIN bounds
          WHERE bounds.associations<=%s AND bounds.projection_bytes<=%s
            AND bounds.envelopes<=256 AND bounds.envelope_bytes<=%s
          GROUP BY e.id,e.payload_sha256,e.payload''').format(logical_size=logical_size_sql()),
          ('kalshi','polymarket_us','the_odds_api','kalshi','polymarket_us',
           MAX_ASSOCIATIONS+1,MAX_ASSOCIATIONS,24*1024*1024,24*1024*1024)).fetchall()
        bounds=next(r['bounds'] for r in captured if r['id'] is None)
        if bounds['associations']>MAX_ASSOCIATIONS:raise ValueError('board_source_association_capacity')
        if bounds['projection_bytes']>24*1024*1024:raise ValueError('board_source_association_byte_capacity')
        if bounds['envelopes']>256 or bounds['envelope_bytes']>24*1024*1024:raise ValueError('combined_input_capacity')
        rows=[r for r in captured if r['id'] is not None]
        if len(rows)>256 or sum(len(r['payload'].encode()) for r in rows)>24*1024*1024:
            raise ValueError('combined_input_capacity')
        projections=[p for row in rows for p in row['projections']]
        if len(projections)>MAX_ASSOCIATIONS:
            raise ValueError('board_source_association_capacity')
        if sum(len(p['payload'].encode()) for p in projections)>24*1024*1024:
            raise ValueError('board_source_association_byte_capacity')
        originals=[dict(id=r['id'],payload_sha256=r['payload_sha256'],record=json.loads(r['payload'])) for r in rows]
        return originals,{(p['source'],p['kind'],p['native_id']):p['envelope_id'] for p in projections},sorted(projections,key=lambda p:(p['source'],p['kind'],p['native_id']))

    def retain_combined(self, bundle, *, storage_key=None, source_guard=None):
        """Add a combined projection without changing original source history."""
        from app.comparison.combined_inputs import validate
        bundle=validate(bundle)
        key=storage_key or bundle['game_key']
        payload=dict(version=bundle['version'],game_key=key,input_version=bundle['input_version'],inputs=bundle)
        if source_guard is not None:payload.update(source_guard=source_guard,capture_engine=engine_binding())
        if len(encoded(payload))>MAX_PAYLOAD:raise ValueError('combined_snapshot_byte_cap')
        with self.db.transaction():
            for e in bundle['envelopes']:self.envelope(e['record'],e['id'])
            from .price_projection import observe_bundle
            observe_bundle(self.db,bundle)
            self.db.execute('INSERT INTO current_game_projection VALUES (%s,%s,%s,%s) ON CONFLICT(game_key) DO UPDATE SET input_version=excluded.input_version,payload=excluded.payload,updated_at=excluded.updated_at WHERE current_game_projection.input_version<>excluded.input_version',
                (key,bundle['input_version'],wire(payload),utc()))
        return key

    def snapshot(self, key, policy, *, at=None):
        # Short consistent capture. Calculation runs only after this transaction.
        with self.db.transaction():
            row=self.db.execute('SELECT * FROM current_game_projection WHERE game_key=%s FOR SHARE',(key,)).fetchone()
            if not row:raise ValueError('game_inputs_absent')
            projection=json.loads(row['payload'])
            combined=projection.get('version')=='predict-combined-occurrence-inputs-1'
            if combined and at is not None and at!=projection['inputs']['as_of']:raise ValueError('combined_original_evaluation_instant_conflict')
            # An unchanged source-local projection keeps its first evaluation instant
            # just like a combined capture; retry timing belongs to attempts.
            at=at or (projection['inputs']['as_of'] if combined else row['updated_at'].isoformat());value=dict(version=VERSION,game_key=key,input_version=row['input_version'],
                policy=policy.to_dict(),as_of=at,projection=json.loads(row['payload']),engine_binding=engine_binding(),
                engines=['predict-funded-single-2','predict-funded-pair-2','fees-1'] if getattr(policy,'sizing_mode',None) is not None else ['predict-funded-single-1','predict-funded-pair-1','fees-1'],
                model='existing EV05/EV06 NFL pregame model; original assumptions retained')
            sid=hashed(value)
            self.immutable('current_game_snapshot','id',dict(id=sid,game_key=key,input_version=row['input_version'],
                policy_version=policy.revision,as_of=at,payload_sha256=hashed(value),payload=wire(value)))
            return dict(value,id=sid)

    def publish(self,snapshot,result, *, allow_latest=True):
        guard=snapshot['projection'].get('source_guard')
        if guard is not None:
            for field in ('snapshot_id','game_key','input_version','policy','engine_binding'):
                expected=snapshot['id'] if field=='snapshot_id' else snapshot[field]
                if result.get(field)!=expected:raise ValueError('board_result_snapshot_binding_conflict:'+field)
        rid=hashed(dict(snapshot_id=snapshot['id'],result=result));reused=False
        with self.db.transaction():
            if guard is not None:
                from .comparison_board import LOCK,source_guard
                self.db.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            self.db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('calculation:'+snapshot['id'],))
            # Numeric/meaningful calculation identity belongs to the immutable
            # snapshot (exact dependencies, policy and engine), not retry time.
            prior=self.db.execute('SELECT id,payload FROM current_game_result WHERE snapshot_id=%s ORDER BY calculated_at,id LIMIT 1',(snapshot['id'],)).fetchone()
            if prior:
                original=json.loads(prior['payload'])
                if {k:v for k,v in original.items() if k!='calculated_at'}!={k:v for k,v in result.items() if k!='calculated_at'}:
                    raise ValueError('same_snapshot_calculation_conflict')
                rid=prior['id'];reused=True
            else:
                self.immutable('current_game_result','id',dict(id=rid,snapshot_id=snapshot['id'],payload_sha256=hashed(result),
                    payload=wire(result),calculated_at=result['calculated_at']))
            row=self.db.execute('SELECT input_version FROM current_game_projection WHERE game_key=%s FOR UPDATE',(snapshot['game_key'],)).fetchone()
            allowed=allow_latest and row is not None and row['input_version']==snapshot['input_version'] and snapshot['engine_binding']==engine_binding()
            if allowed and guard is not None:allowed=guard==source_guard(self,snapshot['projection']['inputs']['members'])
            self.db.execute('INSERT INTO current_calculation_attempt(snapshot_id,result_id,attempted_at,reused,published) VALUES (%s,%s,%s,%s,%s)',
                (snapshot['id'],rid,result['calculated_at'],reused,allowed))
            if not allowed:return rid,False
            self.db.execute('''INSERT INTO current_latest_result VALUES (%s,%s,%s,%s)
             ON CONFLICT(game_key,policy_version) DO UPDATE SET input_version=excluded.input_version,result_id=excluded.result_id
             WHERE (current_latest_result.input_version,current_latest_result.result_id) IS DISTINCT FROM (excluded.input_version,excluded.result_id)''',
                (snapshot['game_key'],snapshot['policy']['revision'],snapshot['input_version'],rid))
            return rid,True

    def result(self,key,policy):
        row=self.db.execute('''SELECT r.id,r.payload,p.input_version AS latest_input,l.input_version AS saved_input
         FROM current_latest_result l JOIN current_game_result r ON r.id=l.result_id
         JOIN current_game_projection p ON p.game_key=l.game_key WHERE l.game_key=%s AND l.policy_version=%s''',(key,policy.revision)).fetchone()
        if not row:return None
        value=json.loads(row['payload']);value.update(result_id=row['id'],superseded=row['latest_input']!=row['saved_input'] or value.get('engine_binding')!=engine_binding())
        return age_result(value)


def calculate(snapshot):
    from app.dashboard.current_state import unavailable
    from app.dashboard.current_normalized import catalog_from_normalized
    from app.dashboard.current_contract import serialize
    from app.comparison.occurrence_matching import OccurrenceResolver
    from app.comparison.estimated_policy import EstimatePolicy
    if snapshot['engine_binding']!=engine_binding():raise ValueError('snapshot_engine_binding_changed')
    v=snapshot['projection']['inputs']
    if snapshot['projection'].get('version')=='predict-combined-occurrence-inputs-1':
        from app.comparison.combined_inputs import calculate as combined_calculate
        policy=EstimatePolicy.from_dict(snapshot['policy'])
        state=combined_calculate(v,policy)
        return dict(version=VERSION,snapshot_id=snapshot['id'],game_key=snapshot['game_key'],input_version=snapshot['input_version'],
            as_of=snapshot['as_of'],calculated_at=utc(),state=state,policy=snapshot['policy'],engine_binding=snapshot['engine_binding'],
            envelope_ids=v['envelope_ids'],representation=v['representation'])
    raw=unavailable()
    raw.update(runtime_id='stored:'+snapshot['id'],clock_at=snapshot['as_of'],projected_at=snapshot['as_of'],state='available')
    for venue in raw['source_status']:raw['source_status'][venue]=dict(state='available',reason_code='stored_observation',reason='Saved source-local inputs; source clocks apply.',next_due_at=None)
    raw=catalog_from_normalized(raw,deepcopy(v['records']),reference_records=deepcopy(v['references']),occurrence_resolver=OccurrenceResolver())
    policy=EstimatePolicy.from_dict(snapshot['policy'])
    state=serialize(raw,estimate_policy=policy,details=True,supported=False,paired=False)
    from app.comparison.estimated_pair import assemble
    for event in state['events']:
        event['funded_pairs'],event['funded_pair_search']=assemble(event,state['comparison_profiles'],stamp(snapshot['as_of']),policy=policy,details=True)
    return dict(version=VERSION,snapshot_id=snapshot['id'],game_key=snapshot['game_key'],input_version=snapshot['input_version'],
        as_of=snapshot['as_of'],calculated_at=utc(),state=state,policy=snapshot['policy'],engine_binding=snapshot['engine_binding'],
        envelope_ids=v['envelope_ids'],representation=v['representation'])


def age_result(value,at=None):
    from app.comparison.estimated_ev import temporal
    from app.dashboard.current_contract import quotes_of
    at=stamp(at or utc());value=deepcopy(value);state=value['state'];historical=value.get('superseded',False);source_clocks=[]
    for e in state['events']:
        has_winner=any(g['market']=='winner' and g['period']=='full_game' for g in e['groups'])
        for g in e['groups']:
            for o in g['outcomes']:
                for q in quotes_of(o):
                    t=temporal(q,state['comparison_profiles'],at,e)
                    if g['market']=='winner' and q['times']['source_at']:source_clocks.append(q['times']['source_at'])
                    for row in q['calculations'].get('funded_estimate',{}).get('reference_inputs',[]):
                        clock=row.get('market_at') or row.get('book_at')
                        if clock:source_clocks.append(clock)
                    estimate=q['calculations'].get('funded_estimate',{})
                    refs=estimate.get('reference_inputs',[])
                    # The ordinary approved adapter records exact original clocks
                    # on the saved estimate; legacy profile rows may omit them.
                    # Keep profile-expiry and kickoff refusals from temporal().
                    clocks=[t[0]]
                    if refs:
                        for ref in refs:
                            source=ref.get('market_at') or ref.get('book_at');receipt=ref.get('received_at')
                            clocks.append('unknown' if not source or not receipt else
                                'future_at_receipt' if stamp(source)>stamp(receipt) else
                                'future' if stamp(source)>at or stamp(receipt)>at else
                                'expired' if (at-stamp(source)).total_seconds()>1800 else 'current')
                    elif estimate.get('model_available'):clocks.extend(x for x in t[1:] if isinstance(x,str))
                    stale=any(x!='current' for x in clocks) or any(x is True for x in t)
                    q['age_seconds']=None if q['times']['source_at'] is None else max(0,int((at-stamp(q['times']['source_at'])).total_seconds()))
                    estimate=q['calculations'].get('funded_estimate',{})
                    if stale or value.get('superseded',False):
                        estimate['ranking_eligible']=False
                        if 'classification' in estimate:
                            estimate['classification']['main_positive_eligible']=False
                            estimate['classification']['positive_rule_sensitive_eligible']=False
                    q['saved_status']='historical' if stale else 'current'
                    # Ordinary saved views display full-game winners and their
                    # pairs. Retained superseded spread lines keep their own ages
                    # without withdrawing unrelated current winner authority.
                    if not has_winner or g['market']=='winner' and g['period']=='full_game':historical|=stale
        if historical:
            for p in e.get('funded_pairs',[]):
                p['ranking_eligible']=False
                if 'classification' in p:
                    p['classification']['main_positive_eligible']=False
                    p['classification']['positive_rule_sensitive_eligible']=False
    value['source_as_of']=min(source_clocks,key=stamp) if source_clocks else None
    value['source_age_seconds']=None if not source_clocks else max(0,int((at-stamp(value['source_as_of'])).total_seconds()))
    value['status']='historical' if historical else 'current';value['read_at']=at.isoformat()
    value['age_seconds']=max(0,int((at-stamp(value['as_of'])).total_seconds()))
    return value
