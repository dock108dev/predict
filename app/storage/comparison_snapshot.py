"""Finite local capture -> match -> math -> atomic replacement, independent of queues."""
from copy import deepcopy
from datetime import timedelta
from fractions import Fraction as F
import gzip
import lzma
import zlib
import json
import math
import orjson
from time import monotonic
from uuid import uuid4
from psycopg.types.json import Jsonb

from .store import Store, encoded, hashed, stamp
from .current_games import utc
from .current_rows import CurrentRowStore
from .comparison_board import ReadContext
from app.comparison.snapshot_math import assumptions, funded
from app.comparison.cashflows import exact_wire as wire

SPORTS=('NFL','NCAAF','NBA','NCAAB','MLB','NHL')


class SnapshotOperationError(ValueError):
    """An expected snapshot refusal that can be shown to the caller."""


def pack(value, *, fast=False):
    if fast:
        # Keep the C encoder, but feed its chunks directly into gzip. Joining a
        # whole root string, its UTF-8 copy and the compressed bytes at once can
        # exceed the ordinary worker's unchanged memory budget as finance fills.
        encoder=json.JSONEncoder(sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
        compressor=zlib.compressobj(level=6,wbits=31)
        def pieces():
            # Top-level lists contain independent source/result rows. Encode one
            # at a time in C so the encoder's fragment list cannot retain the
            # entire expanded slate alongside its decoded object graph.
            if not isinstance(value,dict):
                yield from encoder.iterencode(value,_one_shot=True)
                return
            yield '{'
            for index,key in enumerate(sorted(value)):
                if index:yield ','
                yield encoder.encode(key)+':'
                item=value[key]
                if isinstance(item,list):
                    yield '['
                    for n,row in enumerate(item):
                        if n:yield ','
                        yield from encoder.iterencode(row,_one_shot=True)
                    yield ']'
                else:yield from encoder.iterencode(item,_one_shot=True)
            yield '}'
        chunks=[compressor.compress(chunk.encode()) for chunk in pieces()]
        chunks.append(compressor.flush())
        content=b''.join(chunks)
    else:
        content=lzma.compress(encoded(value),preset=1)
    if len(content)>96*1024*1024:raise SnapshotOperationError('Snapshot storage capacity reached')
    return content


def expand_row(row):
    """Decode deferred display evidence only for a returned row, never for rank."""
    if '_detail_json' not in row:
        return row
    detail=json.loads(row['_detail_json'])
    # Current authority can withdraw these fields before their detail is read.
    reference=row.get('reference_calculation')
    if reference is not None:
        detail['reference_calculation']=dict(detail.get('reference_calculation') or {}, **reference)
    return dict(detail, **{k:v for k,v in row.items() if k not in (
        '_detail_json','_metric_states','_fee_bases','reference_calculation')})


def defer_details(result):
    """Same JSON evidence, with cold list reads decoding only ranking inputs.

    Every original field is recoverable; no financial input or source is dropped.
    The deferred object is a JSON string, not an independently versioned cache.
    """
    required=set(('id kind venue source game_key game_title league start_at selection market '
        'current_authority publication_epoch publication_policy settings_revision probability '
        'gross_return_percent conditional_return_percent conservative_return_percent net_return_percent '
        'gross_profit_per_claim price_difference_cents snapshot_benchmark_reason same_outcome '
        'times original evidence_result_id '
        'captured_at price_revision economic_revision').split())
    rows=[]
    for row in result['rows']:
        if '_detail_json' in row:
            # Already deferred immutable component copied from the prior root.
            # Do not nest or decode its exact display evidence on every seal.
            rows.append(row)
            continue
        light={k:v for k,v in row.items() if k in required}
        light['_metric_states']={k:v['state'] for k,v in row.get('metric_status',{}).items()}
        light['_fee_bases']={k:[row.get(k,{}).get('available'),row.get(k,{}).get('ranking_basis')]
            for k in ('conditional_trade_benchmark','conservative_trade_benchmark')}
        light['_detail_json']=encoded({k:v for k,v in row.items() if k not in required}).decode()
        rows.append(light)
    return dict(result,rows=rows)


def pack_read(result):
    """Strict fast JSON for the replaceable read projection, with exact fallback.

    Arbitrary-size integers in retained source evidence must never be decoded as
    doubles. OPT_STRICT_INTEGER rejects them before this format is marked; older
    and nonconforming payloads continue through the original exact JSON codec.
    """
    pending=[result]
    while pending:
        item=pending.pop()
        if isinstance(item,dict):pending.extend(item.values())
        elif isinstance(item,list):pending.extend(item)
        elif isinstance(item,float) and not math.isfinite(item):
            raise ValueError('Non-finite snapshot number')
    try:
        raw=orjson.dumps(result,option=orjson.OPT_SORT_KEYS|orjson.OPT_STRICT_INTEGER)
    except TypeError:
        return pack(result,fast=True)
    content=b'PJ1'+gzip.compress(raw,compresslevel=6,mtime=0)
    if len(content)>96*1024*1024:raise SnapshotOperationError('Snapshot storage capacity reached')
    return content


def _decode(value):
    if value.startswith(b'PMI1'):
        from .member_packet import read
        return read(value)
    if value.startswith(b'PJ1'):
        result=orjson.loads(gzip.decompress(value[3:]))
    else:
        decompress=gzip.decompress if value.startswith(b"\x1f\x8b") else lzma.decompress
        result=json.loads(decompress(value))
    return result


def unpack(value, *, lazy=False, db=None, previous=None):
    result=_decode(value)
    if isinstance(result,dict) and '_read_fragments' in result:
        if db is None:raise SnapshotOperationError('Coherent database view required for member fragments')
        from .ordinary_fragments import expand
        result=expand(result,db,lazy=lazy,previous=previous)
    if not lazy and isinstance(result,dict) and 'rows' in result:
        result['rows']=[expand_row(row) for row in result['rows']]
    return result


def neighborhoods(frame):
    """Necessary-condition components; no possible occurrence peer is omitted.

    The resolver can compare records sharing source event, participant set or a
    typed provider ID. Union those indexes before invoking its exact predicates.
    This bounds normalization per match neighborhood without altering matching.
    """
    from app.comparison.occurrence_matching import OccurrenceResolver
    resolver=OccurrenceResolver();parents={};records={}
    def root(k):
        parents.setdefault(k,k)
        while parents[k]!=k:
            parents[k]=parents[parents[k]];k=parents[k]
        return k
    for r in frame['records']:
        f=resolver._facts(r)
        keys=[('event',*f['key']),('roles',f['league'],*sorted(f['roles'].values())),
              *(('shared',name,value) for name,value in f['shared'].items())]
        first=root(keys[0])
        for k in keys[1:]:parents[root(k)]=first
        records.setdefault(keys[0],[]).append(r)
    groups={}
    for k,rows in records.items():groups.setdefault(root(k),[]).extend(rows)
    for rows in groups.values():yield dict(frame,records=rows)


def captured_price(event,group,q,record,game,league):
    from app.dashboard.comparison_board import price
    from app.dashboard.current_contract import identity
    from app.comparison.same_outcome import quote_identity
    row=price(q)
    row.update(game_key=game['game_key'],game_title=game['title'],league=league,
        start_at=game['start_at'],market={k:group.get(k) for k in ('market','period','line')},
        same_outcome=quote_identity(q,group,event),original_record=record,
        native_contract=q.get('native_contract'),binding=q['binding'])
    reference=deepcopy(record['quote'].get('sharp_reference'))
    if reference:reference['selection_digest']=identity('binding',q['binding']['selection'])
    row['reference']=reference
    row['benchmark_quote']=dict(q,sharp_reference=reference) if reference else None
    row['id']=hashed([game['game_key'],row['quote_id']])
    return row


def capture(db, *, at=None, ordinary=False, event_ids=None, capture_binding=None, price_basis=False, _frame_dependencies=None):
    from app.dashboard.comparison_board import entries
    from app.dashboard.grouped_odds import reference_prices
    at=at or utc();start=monotonic();out=dict(captured_at=at,quotes=[],references=[],games=[],sources={},issues=[])
    if price_basis:
        from .capture_price import begin, remember_frame, remember_catalog
        out['_price_basis']=begin(capture_binding)
    # All leagues share one MVCC transaction. Per-league materialization avoids
    # duplicating the complete normalized universe in the old board cache.
    owns_transaction = db.info.transaction_status == 0
    with db.transaction():
        if owns_transaction:
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        db.execute('SET LOCAL statement_timeout=30000')
        if ordinary:
            from .ordinary_publication import dependencies, policy_identity
            out['dependencies']=dependencies(db,event_ids) if _frame_dependencies is None else _frame_dependencies
            out['policy_identity']=policy_identity()
        if ordinary:
            from .board_capture import capture_batches
            components=[event_ids] if event_ids is not None else capture_batches(db)
        # Partition the exact requested window once in this capture transaction.
        # Complete structural fallback used to scan the full slate for each league.
        league_ids={}
        for row in db.execute("""SELECT id,facts->>'competition' league FROM current_event
            WHERE scheduled_start::timestamptz >= %s AND scheduled_start::timestamptz < %s
            AND (%s::text[] IS NULL OR id=ANY(%s)) ORDER BY id""",
            (stamp(at),stamp(at)+timedelta(hours=72),event_ids,event_ids)):
            league_ids.setdefault(row['league'],[]).append(row['id'])
        for league in SPORTS:
            from app.comparison.calculation_control import checkpoint
            checkpoint()
            ids=league_ids.get(league,[])
            if not ids:continue
            scopes=[ids]
            if ordinary:
                selected=set(ids)
                scopes=[list(selected.intersection(component)) for component in components if selected.intersection(component)]
            for scope in scopes:
                frame=CurrentRowStore(db).capture(include_depth=False,event_ids=scope)
                if price_basis:remember_frame(out['_price_basis'],frame,at)
                # Hydrate only the captured contracts, still inside this MVCC frame.
                # Ordinary top-price math never consumes depth. The exact source
                # price/contract witnesses remain attached; avoid expanding every
                # ladder into an automatic whole-slate capture.
                if not ordinary:
                    frame['records']=CurrentRowStore(db).hydrate_records(frame['records'])
                # Preserve full reference witnesses before strict execution/catalog
                # filters. A display price alone cannot prove a benchmark pair.
                captured_refs=reference_prices(frame['records'])
                records_by_source={hashed(r['quote']['source']):r for r in frame['records'] if r['quote']['venue']=='pinnacle'}
                for ref in captured_refs:
                    ref['original_record']=deepcopy(records_by_source[ref['id']])
                    ref['game_key']='reference:'+hashed([ref['source']['provider'],ref['source']['native_event_id']])
                out['references'].extend(captured_refs)
                out['sources'].update(frame['source_status'])
                for neighborhood in neighborhoods(frame):
                    context=ReadContext(Store(None),at=at,frame=neighborhood,tolerate_invalid_catalog=True,
                        reuse_catalog_inputs=ordinary,capture_binding=capture_binding if ordinary else None)
                    for catalog in context.catalog_bundles():
                        if monotonic()-start>120:raise SnapshotOperationError('Snapshot capture exceeded two minutes; prior result retained')
                        try:bundle=context.observation_bundles(game=catalog['game_key'])[0]
                        except (ValueError,KeyError,TypeError) as exc:
                            out['issues'].append(dict(game=catalog['game_key'],reason=str(exc)[:180]));continue
                        if price_basis:remember_catalog(out['_price_basis'],context,catalog)
                        game=dict(catalog['catalog_event'],game_key=catalog['game_key'])
                        out['games'].append(game)
                        records={hashed(r['quote']['source']):r for r in bundle['records']}
                        refs=reference_prices(bundle['records'])
                        for ref in refs:ref['game_key']=game['game_key']
                        reference_games={r['id']:r['game_key'] for r in refs}
                        for ref in captured_refs:
                            if ref['id'] in reference_games:ref['game_key']=reference_games[ref['id']]
                        for event,group,q in entries(bundle['state_inputs']):
                            record=records[hashed(q['source'])]
                            row=captured_price(event,group,q,record,game,league)
                            out['quotes'].append(row)
                    out['issues'].extend(context.catalog_errors)
        out['epoch']=str(db.execute('SELECT epoch FROM current_row_epoch WHERE singleton').fetchone()['epoch'])
        out['sources']={r['venue']:r['state'] for r in db.execute('SELECT venue,state FROM current_source_status').fetchall()}
    out['id']=uuid4().hex
    out['capture_seconds']=round(monotonic()-start,3)
    return out


def probability(row,settings,at):
    from app.collection.current_benchmark import calculate,validate_reference
    if row['league']=='NCAAB' or row['venue'] in ('kalshi','polymarket_us'):
        ref=row.get('snapshot_benchmark')
        return (ref['probability'],None) if ref else (None,row.get('snapshot_benchmark_missing','Exact two-sided Pinnacle reference unavailable'))
    q=row.get('benchmark_quote')
    if not q:return None,'Exact two-sided '+settings['benchmark_venue'].title()+' reference unavailable'
    try:
        validate_reference(q['sharp_reference'],q['binding']['selection'],venue=settings['benchmark_venue'])
        value=calculate(q,stamp(at),allow_last_known=True)
        if value.get('value') is None:return None,value.get('reason')
        p=value['basis']['probability']
        return wire(F(int(p['numerator']),int(p['denominator']))),None
    except (ValueError,KeyError,TypeError,ArithmeticError) as exc:return None,str(exc)


def calculate(inputs,value=None):
    from app.dashboard.current_contract import price
    settings,policy=assumptions(value)
    rows=[];pairs=[];oppositions={}
    from app.comparison.snapshot_benchmark import bind
    from app.comparison import snapshot_named_benchmark as named
    benchmark_refs=named.references(inputs['quotes'],inputs['references'],settings)
    named_quotes=named.bind(inputs['quotes'],benchmark_refs,settings)
    projected,benchmark_diagnostics=bind(named_quotes,benchmark_refs,settings,inputs['captured_at'])
    game_keys={old['game_key']:new['game_key'] for old,new in zip(inputs['quotes'],projected)}
    from app.comparison.snapshot_identity import games as projected_games
    games=projected_games(inputs,projected)
    references=[dict(r,game_key=game_keys.get(r.get('game_key'),r.get('game_key'))) for r in inputs['references']]
    for original in projected:
        from app.comparison.calculation_control import checkpoint
        checkpoint()
        row={k:v for k,v in original.items() if k not in ('benchmark_quote','original_record','native_contract')}
        row['game_title']=games.get(row['game_key'],{}).get('title',row['game_title'])
        record=original.get('original_record') or {}
        participant=record.get('selection',{}).get('participant')
        row['participant_label']=next((name for name,pid in record.get('event',{}).get('participants',{}).items() if pid==participant),None)
        row['probability'],row['probability_missing']=probability(original,settings,inputs['captured_at'])
        supported=row['common_odds'].get('supported') and (bool(row.get('snapshot_benchmark')) or row['snapshot_supported'] if 'snapshot_supported' in row else row['binding'].get('verified'))
        cost=price(original) if supported else None
        if cost is not None and cost<=0:cost=None
        row['cost_per_normal_claim']=wire(cost)
        p=None if row['probability'] is None else F(row['probability'])
        row['gross_return_percent']=None if p is None or cost is None else wire(100*(p/cost-1))
        row['math']=dict(available=False,missing=['supported price and selection']) if cost is None else funded([cost],[p],[row['venue']],settings,policy)
        row['net_return_percent']=row['math'].get('buffered_return_percent')
        row['input_basis']=dict(price='observed captured original',probability='unavailable' if p is None else 'configured proportional no-vig decisive benchmark; not an observed probability',fees='unavailable' if settings['fees'][row['venue']] is None else 'configured hypothetical upfront rate',scenario='unavailable' if settings['scenario']=='unavailable' else 'configured hypothetical settlement scenario',sizing='unavailable' if settings['sizing']=='unavailable' else 'configured fractional top-price size; observed depth not used',buffer='configured once on deployed capital')
        row['gross_profit_per_claim']=None if p is None or cost is None else wire(p-cost)
        from app.comparison.snapshot_fee_scope import applicability
        row['fee_applicability']=applicability(record) if record else None
        from app.comparison.conditional_benchmark import snapshot_metric
        row['conditional_trade_benchmark']=snapshot_metric(row,at=inputs['captured_at'])
        row['conditional_return_percent']=row['conditional_trade_benchmark'].get('return_percent')
        from app.comparison.snapshot_conservative import metric as conservative_metric
        row['conservative_trade_benchmark']=conservative_metric(row,at=inputs['captured_at'])
        row['conservative_return_percent']=row['conservative_trade_benchmark'].get('return_percent')
        from app.dashboard.u0_display import quote_display
        ref=original.get('reference')
        row['reference_odds']=None if not ref else dict(quote_display(ref['selected_odds'],'decimal_odds'),source_at=ref['source_at'],role='reference_only')
        if row['reference_odds']:row['reference_odds'].pop('what_if',None)
        from app.comparison.snapshot_metrics import disclose
        disclose(row,original,benchmark_refs)
        row['kind']='single';rows.append(row)
        # Conditional opposing scenarios require supported exact identity and
        # the same occurrence, scoring, domain and exact threshold. NO/Short
        # keep their own explicit predicates; never infer opponent by label.
        contract=original.get('native_contract') or {};facts=contract.get('same_outcome') or {}
        pred=facts.get('predicate')
        op = pred.get('operator') if pred else None
        if row.get('snapshot_identity') and pred and F(pred['threshold']).denominator!=1:op={'ge':'gt','le':'lt'}.get(op,op)
        if cost is not None and row['same_outcome']['supported'] and pred and op in ('gt','lt'):
            key=hashed([row['game_key'],row['market']['market'],row['market']['period'],facts.get('scoring') or contract.get('scope'),pred['domain'],pred.get('subject_id'),str(F(pred['threshold']))])
            oppositions.setdefault(key,{}).setdefault(op,[]).append(row)
    for sides in oppositions.values():
        for a in sides.get('gt',[]):
            for b in sides.get('lt',[]):
                if a['id']==b['id'] or a['venue']==b['venue'] and not (a.get('snapshot_identity') and b.get('snapshot_identity')):continue
                m=funded([a['cost_per_normal_claim'],b['cost_per_normal_claim']],[a['probability']],[a['venue'],b['venue']],settings,policy)
                pairs.append(dict(id=hashed([a['id'],b['id']]),kind='pair',game_key=a['game_key'],game_title=a['game_title'],league=a['league'],start_at=a['start_at'],market=a['market'],legs=[a['id'],b['id']],venues=[a['venue'],b['venue']],math=m,
                    minimum_return_percent=m.get('scenario_minimum_percent'),
                    snapshot_identities=[a.get('snapshot_identity'),b.get('snapshot_identity')]))
    groups={}
    for row in rows:
        ident=row['same_outcome']
        key=hashed([row['game_key'],ident['key']]) if ident['supported'] else row['id']
        groups.setdefault(key,[]).append(row)
    for peers in groups.values():
        for row in peers:
            choices=[F(p['cost_per_normal_claim']) for p in peers if p['id']!=row['id'] and (p['venue']!=row['venue'] or row.get('snapshot_identity')) and p['cost_per_normal_claim'] is not None]
            row['price_difference_cents']=None if not choices or row['cost_per_normal_claim'] is None else wire(100*(min(choices)-F(row['cost_per_normal_claim'])))
    return dict(id=uuid4().hex,snapshot_id=inputs['id'],captured_at=inputs['captured_at'],assumptions=settings,
        calculated_at=utc(),rows=rows,pairs=pairs,games=list(games.values()),references=references,sources=inputs['sources'],issues=inputs['issues'],
        counts=dict(observations=len(rows),gross_numeric=sum(r['gross_return_percent'] is not None for r in rows),
            conditional_numeric=sum(r['conditional_return_percent'] is not None for r in rows),
            conservative_numeric=sum(r.get('conservative_return_percent') is not None for r in rows),
        net_numeric=sum(r['net_return_percent'] is not None for r in rows),pairs=len(pairs),
            unmatched=sum(not r['same_outcome']['supported'] for r in rows)),provider_requests=0,
        capture_seconds=inputs['capture_seconds'],benchmark_diagnostics=benchmark_diagnostics,
        scope=dict(leagues=list(SPORTS),families=['winner','spread','total'],period='full_game',horizon_hours=72),
        live_eligibility='not assessed; captured math does not establish current source availability or executable size')


def current(db,result_id=None):
    with db.transaction():
        row=db.execute("""UPDATE comparison_snapshot_result SET lease_until=now()+interval '2 hours'
            WHERE id=COALESCE(%s,(SELECT result_id FROM comparison_snapshot_head))
            RETURNING snapshot_id,result""",(result_id,)).fetchone()
        if row is None:return None
        db.execute("UPDATE comparison_snapshot SET lease_until=now()+interval '2 hours' WHERE id=%s",(row['snapshot_id'],))
    return unpack(row['result'],db=db)


def prune(db):
    """Serialize with capture, and skip a result whose reader is renewing its lease."""
    with db.transaction():
        if not db.execute('SELECT pg_try_advisory_xact_lock(901153) held').fetchone()['held']:
            return
        db.execute('DELETE FROM comparison_live_lease WHERE expires_at<now()')
        # Remove expired composites first, then their now-unreferenced members.
        for _ in range(2):
            db.execute('''WITH newest AS (SELECT id FROM comparison_snapshot WHERE NOT automatic ORDER BY captured_at DESC,id DESC LIMIT 2),
                keep_latest AS (SELECT DISTINCT ON (r.snapshot_id) r.id FROM comparison_snapshot_result r
                    JOIN comparison_snapshot s ON s.id=r.snapshot_id
                    WHERE (NOT s.automatic AND s.id IN (SELECT id FROM newest)) OR s.lease_until>=now()
                    ORDER BY r.snapshot_id,r.calculated_at DESC,r.id DESC)
                DELETE FROM comparison_snapshot_result WHERE id IN (
                    SELECT id FROM comparison_snapshot_result WHERE lease_until<now()
                    AND id NOT IN (SELECT result_id FROM comparison_snapshot_head)
                    AND id NOT IN (SELECT result_id FROM comparison_snapshot_review)
                    AND id NOT IN (SELECT result_id FROM comparison_live_head WHERE result_id IS NOT NULL)
                    AND id NOT IN (SELECT result_id FROM comparison_live_component)
                    AND id NOT IN (SELECT member_id FROM comparison_live_member)
                AND id NOT IN (SELECT result_id FROM comparison_live_lease)
                    AND id NOT IN (SELECT id FROM keep_latest) FOR UPDATE SKIP LOCKED)''')
        db.execute('''DELETE FROM comparison_snapshot WHERE lease_until<now()
            AND id NOT IN (SELECT snapshot_id FROM comparison_snapshot_result)
            AND (automatic OR id NOT IN (SELECT id FROM comparison_snapshot WHERE NOT automatic ORDER BY captured_at DESC,id DESC LIMIT 2))''')


def replace(db, *, action, value=None, expected=None):
    # Session lock serializes finite operations across HTTP workers. Readers
    # continue seeing the prior committed head until this one atomically lands.
    if not db.execute('SELECT pg_try_advisory_lock(901153) locked').fetchone()['locked']:
        raise SnapshotOperationError('Another snapshot operation is running; previous result retained')
    try:
        prior=current(db)
        if expected is not None and (prior is None or prior['id']!=expected):raise SnapshotOperationError('Snapshot changed; reload before applying settings')
        if action=='recalculate':
            if prior is None:raise SnapshotOperationError('Capture prices before recalculating')
            inputs=unpack(db.execute('SELECT inputs FROM comparison_snapshot WHERE id=%s',(prior['snapshot_id'],)).fetchone()['inputs'])
        elif action=='refresh':inputs=capture(db)
        else:raise SnapshotOperationError('Unknown snapshot operation')
        result=calculate(inputs,value if value is not None else prior['assumptions'] if prior else None)
        packed_inputs=pack(inputs) if action=='refresh' else b''
        packed_result=pack(result)
        from app.collection.current_storage_policy import SQL_BYTE_CAP, sql_usage
        from .storage_maintenance import REWRITE_RUNWAY_BYTES
        # TOAST chunks, indexes and ordinary concurrent ingestion need runway.
        estimated_write=(len(packed_inputs)+len(packed_result))*2
        if sql_usage(db)+estimated_write+REWRITE_RUNWAY_BYTES>=SQL_BYTE_CAP:
            raise SnapshotOperationError('Insufficient SQL headroom for snapshot; previous result retained')
        with db.transaction():
            if action=='refresh':db.execute('INSERT INTO comparison_snapshot(id,captured_at,inputs) VALUES (%s,%s,%s)',(inputs['id'],inputs['captured_at'],packed_inputs))
            db.execute('INSERT INTO comparison_snapshot_result(id,snapshot_id,assumptions,result) VALUES (%s,%s,%s,%s)',(result['id'],inputs['id'],Jsonb(result['assumptions']),packed_result))
            db.execute('INSERT INTO comparison_snapshot_head(singleton,result_id) VALUES (true,%s) ON CONFLICT(singleton) DO UPDATE SET result_id=EXCLUDED.result_id',(result['id'],))
            prune(db)
        return result
    finally:db.execute('SELECT pg_advisory_unlock(901153)')
