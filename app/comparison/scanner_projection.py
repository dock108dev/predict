"""One bounded, replaceable global opportunity projection, never per-user finance.

Capture/reconciliation and finance are separate phases. Evaluation completion is
accepted only against the still-current exact pair dependencies and generation.
"""
from collections import OrderedDict, deque
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction as F
from threading import RLock
from time import perf_counter
from uuid import uuid4

from .current_dependencies import digest, encoded, instant
from .scanner_readiness import Selection
from .scanner_finance import VERSION as EVALUATOR, BASES, evaluate, dependencies, opportunity_identity
from .estimated_policy import DEFAULT_POLICY
from .calculation_control import checkpoint

VERSION = 'predict-opportunity-scanner-1'
RECEIPT_VERSION = 'predict-scanner-evaluation-receipt-2'
MAX_PAIRS = 2048
MAX_ROWS = 4096
MAX_CACHE_BYTES = 16 * 1024 * 1024
MAX_DISPLAY_BYTES = 4 * 1024 * 1024
MAX_DISPLAY_PAIRS = MAX_PAIRS
MAX_DISPLAY_ROWS = MAX_ROWS
MAX_DEPENDENCY_PROOF_BYTES = 2 * 1024 * 1024
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_PAYLOAD = 2 * 1024 * 1024
MAX_JOURNAL_BYTES = 4 * 1024 * 1024
MAX_JOURNAL = 128
MAX_PAGE = 100
MAX_WORK_PER_TURN = 16
MAX_TURN_SECONDS = .5


@dataclass(frozen=True)
class Filters:
    venues: tuple = ()
    sports: tuple = ()
    leagues: tuple = ()
    markets: tuple = ()
    periods: tuple = ()
    category: str = 'covered_outcome_arb'
    minimum_edge: str | None = None
    minimum_size: str | None = None

    def __post_init__(self):
        if self.category not in BASES:
            raise ValueError('scanner_category_unsupported')
        for k in ('venues','sports','leagues','markets','periods'):
            v = getattr(self,k)
            if not isinstance(v,tuple) or len(v)>16 or len(v)!=len(set(v)) or any(not isinstance(x,str) or not 1<=len(x)<=64 for x in v):
                raise ValueError('scanner_filter_invalid')
        if self.venues:
            Selection(venues=self.venues)
        for k in ('minimum_edge','minimum_size'):
            value = getattr(self,k)
            if value is not None and (not isinstance(value,str) or len(value)>64 or abs(F(value))>10**9 or (k=='minimum_size' and F(value)<0)):
                raise ValueError('scanner_filter_invalid')

    def to_dict(self):
        from dataclasses import asdict
        return asdict(self)


def validate_receipt(receipt, pair, frame, dependency_revision, *, evaluator_revision, at, _instruments=None):
    """Trusted v2 reuse proof; calculation and revalidation clocks stay distinct.

    v1 receipts keep their exact whole-scope revision and clock semantics. v2
    explicitly records an original calculation plus current dependency proof.
    No HTTP path accepts either receipt type.
    """
    fields = {'version','pair_id','readiness_revision','dependency_revision','evaluated_at',
              'revalidated_at','qualifying','evaluator_revision','original_readiness_revision'}
    if set(receipt) != fields or receipt['version'] != RECEIPT_VERSION or type(receipt['qualifying']) is not bool:
        raise ValueError('scanner_receipt_invalid')
    if (pair['id'] != receipt['pair_id'] or pair['input_check']['state'] != 'ready' or
        receipt['readiness_revision'] != frame['revision'] or receipt['dependency_revision'] != dependency_revision or
        receipt['evaluator_revision'] != evaluator_revision or not receipt['original_readiness_revision']):
        raise ValueError('scanner_receipt_dependency_conflict')
    evaluated, verified, now = map(instant,(receipt['evaluated_at'],receipt['revalidated_at'],at))
    if evaluated > verified or verified > now or now >= instant(pair['expires_at']):
        raise ValueError('scanner_receipt_clock_conflict')
    by_id = _instruments if _instruments is not None else {i['id']:i for i in frame['instruments']}
    if any(instant(c)>verified for key in pair['legs'] for k,c in by_id[key]['clocks'].items()
           if c and k in ('source_at','received_at','book_at','book_received_at','provider_book_at','provider_market_at')):
        raise ValueError('scanner_receipt_clock_conflict')
    if any(instant(c)>evaluated for key in pair['legs'] for k,c in by_id[key]['clocks'].items()
           if c and k in ('source_at','book_at','provider_book_at','provider_market_at')):
        raise ValueError('scanner_receipt_original_clock_conflict')
    return True


def validate_receipts(receipts, frame, dependency_revisions, *, evaluator_revision, at):
    seen=set(); pairs={p['id']:p for p in frame['pairs']}
    instruments={i['id']:i for i in frame['instruments']}
    for receipt in receipts:
        key=receipt.get('pair_id')
        if key in seen:raise ValueError('scanner_receipt_duplicate')
        seen.add(key)
        if key not in pairs or key not in dependency_revisions:raise ValueError('scanner_receipt_membership_conflict')
        validate_receipt(receipt,pairs[key],frame,dependency_revisions[key],evaluator_revision=evaluator_revision,at=at,_instruments=instruments)
    return True


class Projection:
    def __init__(self, *, policy=DEFAULT_POLICY, evaluator=evaluate, clock=None):
        from app.storage.current_games import utc
        self.clock = clock or utc
        self.policy = policy; self.evaluator = evaluator
        self.lock = RLock(); self.epoch = None; self.generation = 0
        self.publication = 0; self.frame = None; self.inputs = {}; self.targets = {}
        self.pending = OrderedDict(); self.cache = {}; self.rows = {}; self.receipts = {}
        self._display_memo = {}; self._display_bytes = 0; self._display_count = 0
        self._dependency_proofs = {}; self._dependency_proof_bytes = 0
        self.journal = deque(); self.journal_bytes = 0
        self.state = 'not_evaluated'; self.errors = []; self.stopped = False
        self.evaluations = 0; self.reuses = 0; self.last_capture_ms = None
        self.published_at = None; self.capture_revision = None; self.sql_observation = None
        self.server_id = str(uuid4())
        from .scanner_transitions import Transitions
        self.transitions = Transitions()
        self.summary_observer = None

    @property
    def evaluator_revision(self):
        return digest(dict(version=EVALUATOR, policy=self.policy.revision,
                           engine=(self.frame or {}).get('engine_binding')))

    def _publish(self, rows, reason):
        old = self.rows
        updates = [rows[k] for k in sorted(rows) if old.get(k) != rows[k]]
        removed = [dict(id=k, reason=reason) for k in sorted(set(old)-set(rows))]
        self.rows = rows; self.publication += 1; self.published_at = self.clock()
        self.transitions.observe(self, reason)
        if self.summary_observer is not None:
            try:
                from .scanner_summaries import observation
                self.summary_observer(observation(self, reason))
            except Exception:
                # An optional observation cannot fail prices, expiry or tickets.
                pass
        delta = dict(revision=self.publication, updates=deepcopy(updates), withdrawals=removed)
        size = len(encoded(delta))
        if size > MAX_JOURNAL_BYTES:
            self.journal.clear(); self.journal_bytes=0
            return
        self.journal.append(delta); self.journal_bytes += size
        while len(self.journal)>MAX_JOURNAL or self.journal_bytes>MAX_JOURNAL_BYTES:
            self.journal_bytes -= len(encoded(self.journal.popleft()))

    def fail(self, reason):
        with self.lock:
            self._clear_display()
            self._clear_dependency_proofs()
            self.generation += 1; self.targets.clear(); self.pending.clear(); self.inputs={}
            self.cache.clear(); self.receipts.clear(); self.state='incomplete'
            self.errors=[str(reason)[:160]]; self.signature=None; self._publish({}, 'capture_failed')

    def stop(self):
        with self.lock:
            if self.stopped:return
            self._clear_display()
            self._clear_dependency_proofs()
            self.stopped=True; self.generation += 1; self.state='stopped'
            self.pending.clear(); self.targets.clear(); self.inputs={}; self.cache.clear(); self.receipts.clear()
            self.signature=None; self._publish({}, 'stopped')

    def ingest(self, frame, inputs, *, capture_ms=None, commit_observation=None, policy=None):
        """Defensively detach ordinary caller inputs after validating capacity."""
        with self.lock:
            if policy is not None:self.policy=policy
            if len(frame['pairs'])>MAX_PAIRS or len(encoded(inputs))>MAX_INPUT_BYTES or len({i['occurrence_id'] for i in frame['instruments']})>500:
                self.fail('scanner_input_capacity'); return
            self._ingest_owned(deepcopy(frame),deepcopy(inputs),capture_ms=capture_ms,
                commit_observation=commit_observation,shared_facts=False)

    def _ingest_capture(self, frame, inputs, *, input_bytes_bound, capture_ms=None,
                        commit_observation=None, policy=None):
        """Take ownership only of a fresh, already-detached readiness capture.

        The private capture owner supplies its conservative JSON byte proof.
        Callers must relinquish both dictionaries; no public or HTTP path can
        substitute an integer for ordinary input validation or detachment.
        """
        if type(input_bytes_bound) is not int or not 2<=input_bytes_bound<=MAX_INPUT_BYTES:
            raise ValueError('scanner_capture_input_bound_invalid')
        with self.lock:
            if policy is not None:self.policy=policy
            if len(frame['pairs'])>MAX_PAIRS or len({i['occurrence_id'] for i in frame['instruments']})>500:
                self.fail('scanner_input_capacity'); return
            self._ingest_owned(frame,inputs,capture_ms=capture_ms,
                commit_observation=commit_observation,shared_facts=True)

    def _ingest_owned(self, frame, inputs, *, capture_ms, commit_observation, shared_facts):
        """Install projection-owned dictionaries while the caller holds lock."""
        self._clear_display()
        if self.epoch != frame['epoch'] or self.stopped:
            self._clear_dependency_proofs()
            self.generation += 1; self.cache.clear(); self.pending.clear(); self.receipts.clear()
            self.signature=None; self._publish({}, 'epoch_changed' if self.epoch != frame['epoch'] else 'restart')
        self.stopped=False; self.epoch=frame['epoch']; self.frame=frame; self.inputs=inputs
        self.last_capture_ms=capture_ms; self.sql_observation=commit_observation
        self.capture_revision=self.frame['input_revision']; self.errors=[]
        instruments = {i['id']:i for i in self.frame['instruments']}
        from . import scanner_finance
        context=digest(dict(policy=self.policy.to_dict(),evaluator=EVALUATOR,
            owner_evaluator=scanner_finance.VERSION,engine=self.frame.get('engine_binding')))
        self._retain_dependency_proofs(instruments,context,shared_facts)
        targets = {}
        for pair in self.frame['pairs']:
            if pair['input_check']['state'] != 'ready' or instant(self.clock())>=instant(pair['expires_at']):
                continue
            if any(k not in self.inputs for k in pair['legs']):
                self.errors.append('scanner_pair_inputs_missing'); continue
            dep=self._target_dependency(pair,instruments,context,shared_facts)
            targets[pair['id']]=dict(pair=pair, dependency=dep)
        for key in tuple(self._dependency_proofs):
            if key not in targets:self._discard_dependency_proof(key)
        # Keep FIFO order for unchanged pending work; unrelated receipts cannot
        # restart the initial scan. Changed keys coalesce in place.
        self.targets=targets
        self.cache={k:v for k,v in self.cache.items() if k in targets and v['dependency']==targets[k]['dependency']}
        self.pending=OrderedDict((k,targets[k]) for k in self.pending if k in targets and k not in self.cache)
        for key,target in targets.items():
            if key not in self.cache:self.pending[key]=target
            else:self.reuses+=1
        self._materialize('input_changed')

    def expire(self):
        with self.lock:
            now=instant(self.clock())
            expired={k for k,t in self.targets.items() if now>=instant(t['pair']['expires_at'])}
            if expired:
                self._clear_display()
                for key in expired:
                    self._discard_dependency_proof(key)
                    self.targets.pop(key,None); self.pending.pop(key,None); self.cache.pop(key,None)
                # Input checks must be recaptured, not recomputed from old models.
                self.errors=['temporal_boundary_recapture_required']
                # Expiry can run inside an unpublished financial batch or from
                # an HTTP reader. Withdraw immediately, but never promote newly
                # completed cache values before the scanner's fresh POST proof.
                self.receipts={k:v for k,v in self.receipts.items() if k not in expired}
                self.state='incomplete'; self.signature=None
                self._publish({k:r for k,r in self.rows.items() if r['pair_id'] not in expired}, 'expired')

    def drain(self, *, maximum=MAX_WORK_PER_TURN, publish=True):
        start=perf_counter(); count=0
        while count<min(maximum,MAX_WORK_PER_TURN) and perf_counter()-start<MAX_TURN_SECONDS:
            checkpoint(); self.expire()
            with self.lock:
                if self.stopped or not self.pending:break
                key,target=self.pending.popitem(last=False); generation=self.generation
                frame=self.frame; inputs=self.inputs
                instruments={i['id']:i for i in frame['instruments']}
                at=self.clock(); evaluator_revision=self.evaluator_revision
            pair_started=perf_counter()
            try:
                value=self.evaluator(target['pair'],instruments,inputs,at=at,policy=self.policy)
                error=None
            except (ValueError,KeyError,TypeError,ArithmeticError) as exc:
                value=None; error=str(exc)[:160]
            done=self.clock(); count+=1
            with self.lock:
                self.evaluations += 1
                current=self.targets.get(key)
                if self.stopped or generation!=self.generation or current is None or current['dependency']!=target['dependency'] or instant(done)>=instant(target['pair']['expires_at']):
                    continue
                record=dict(dependency=target['dependency'],value=value,error=error,evaluated_at=done,
                            calculation_started_at=at,original_readiness_revision=frame['revision'],
                            evaluator_revision=evaluator_revision,calculation_ms=(perf_counter()-pair_started)*1000)
                if len(encoded(record))>MAX_CACHE_BYTES//MAX_PAIRS:
                    record.update(value=None,error='scanner_result_capacity')
                else:record['value']=deepcopy(value)
                self._discard_display(key)
                self.cache[key]=record
        with self.lock:
            if publish and not self.stopped:self._materialize('evaluated')
        return count

    def publish(self):
        with self.lock:
            if not self.stopped:self._materialize('evaluated')

    def _clear_dependency_proofs(self):
        self._dependency_proofs.clear(); self._dependency_proof_bytes=0

    def _discard_dependency_proof(self, key):
        prior=self._dependency_proofs.pop(key,None)
        if prior is not None:self._dependency_proof_bytes-=prior[4]

    def _retain_dependency_proofs(self, instruments, context, shared_facts):
        if not shared_facts:
            self._clear_dependency_proofs(); return
        pairs={p['id']:p for p in self.frame['pairs']}
        for key,prior in tuple(self._dependency_proofs.items()):
            pair=pairs.get(key)
            if (pair is None or tuple(pair['legs'])!=prior[0] or context!=prior[2]
                    or any(leg not in instruments or leg not in self.inputs or
                        instruments[leg] is not facts[0] or self.inputs[leg] is not facts[1]
                        for leg,facts in zip(prior[0],prior[1]))):
                self._discard_dependency_proof(key)

    def _target_dependency(self, pair, instruments, context, shared_facts):
        from app.storage.scanner_preparation import is_immutable_fact
        legs=tuple(pair['legs'])
        facts=tuple((instruments[leg],self.inputs[leg]) for leg in legs)
        immutable=shared_facts and all(is_immutable_fact(value) for values in facts for value in values)
        key=pair['id']; prior=self._dependency_proofs.get(key)
        if immutable and prior is not None and prior[0]==legs and prior[2]==context and all(
                value is previous for values,old in zip(facts,prior[1]) for value,previous in zip(values,old)):
            return prior[3]
        self._discard_dependency_proof(key)
        dependency=dependencies(pair,instruments,self.inputs,self.policy,self.frame.get('engine_binding'))
        if immutable:
            charge=len(encoded(dict(key=key,legs=legs,context=context,dependency=dependency)))+512
            if len(self._dependency_proofs)<MAX_PAIRS and self._dependency_proof_bytes+charge<=MAX_DEPENDENCY_PROOF_BYTES:
                self._dependency_proofs[key]=(legs,facts,context,dependency,charge)
                self._dependency_proof_bytes+=charge
        return dependency

    def _clear_display(self):
        self._display_memo.clear(); self._display_bytes=0; self._display_count=0

    def _discard_display(self, key):
        prior=self._display_memo.pop(key,None)
        if prior is not None:
            self._display_bytes-=prior[2]; self._display_count-=len(prior[1])

    def _display_rows(self, key, record, pair, instruments):
        """Memoize presentation within one owned capture, never receipt authority.

        Charge encoded rows and key plus fixed entry/container allowances. Nested
        financial values remain owned by the separately bounded financial cache.
        Cap exhaustion recomputes presentation; it cannot remove a result.
        """
        prior=self._display_memo.get(key)
        if prior is not None:
            if prior[0] is record:return prior[1]
            self._discard_display(key)
        rows=self._build_display_rows(key,record,pair,instruments)
        size=len(encoded(dict(key=key,rows=rows)))+128+512*len(rows)
        if (len(self._display_memo)<MAX_DISPLAY_PAIRS and self._display_count+len(rows)<=MAX_DISPLAY_ROWS
                and self._display_bytes+size<=MAX_DISPLAY_BYTES):
            self._display_memo[key]=(record,rows,size)
            self._display_bytes+=size; self._display_count+=len(rows)
        return rows

    def _build_display_rows(self, key, c, pair, by_id):
        if not c['value']['rows']:return {}
        legs=[by_id[k] for k in pair['legs']]; identity=opportunity_identity(legs)
        positions=[]
        for instrument in legs:
            quote=self.inputs[instrument['id']]['quote']
            from app.dashboard.comparison_board import common_odds
            price=quote.get('original',{})
            display=common_odds(quote) if all(k in price for k in ('value','units','payout')) else None
            positions.append(dict(native_key=instrument['native_key'],predicate=instrument['predicate'],
                units=instrument['units'],original_price=deepcopy(price),common_odds=display))
        event=self.inputs[pair['legs'][0]]['event']; rows={}
        for category in c['value']['rows']:
            row_id=identity+':'+category['category']; dimension=legs[0]
            rows[row_id]=dict(id=row_id,opportunity_id=identity,pair_id=key,dependency_revision=self.targets[key]['dependency'],
                economic_revision=digest(category),evaluated_at=c['evaluated_at'],
                calculation_started_at=c['calculation_started_at'],calculation_ms=c['calculation_ms'],expires_at=pair['expires_at'],
                occurrence_id=pair['occurrence_id'],**{k:dimension[k] for k in ('sport','league','market','period')},
                venues=sorted(i['venue'] for i in legs),positions=positions,
                event_context={k:deepcopy(event[k]) for k in ('title','participants','start_at') if k in event},
                source_clocks=[i['clocks'] for i in legs],search=c['value'].get('search'),**category)
        return rows

    def _materialize(self, reason):
        if self.frame is None:return
        frame=self.frame; by_id={i['id']:i for i in frame['instruments']}; rows={}; receipts={}
        evaluator_revision=self.evaluator_revision
        errors=list(self.errors)
        for key,c in self.cache.items():
            if key not in self.targets:continue
            target=self.targets[key]; pair=target['pair']
            if instant(self.clock())>=instant(pair['expires_at']):continue
            if c['error']:
                errors.append(c['error']); continue
            receipt=dict(version=RECEIPT_VERSION,pair_id=key,readiness_revision=frame['revision'],
                dependency_revision=target['dependency'],evaluated_at=c['evaluated_at'],revalidated_at=self.clock(),
                original_readiness_revision=c['original_readiness_revision'],qualifying=c['value']['qualifying'],
                evaluator_revision=c['evaluator_revision'])
            validate_receipt(receipt,pair,frame,target['dependency'],evaluator_revision=evaluator_revision,at=self.clock(),_instruments=by_id)
            if c['value'].get('evaluation_complete',True):receipts[key]=receipt
            else:errors.extend(c['value'].get('incomplete_reasons') or ['mandatory_joint_cashflows_unknown'])
            # Receipt/original-clock validation above always precedes memo reuse.
            rows.update(self._display_rows(key,c,pair,by_id))
        if len(rows)>MAX_ROWS or len(encoded(self.cache))>MAX_CACHE_BYTES:
            errors.append('scanner_projection_capacity'); rows={}
        self.receipts=receipts
        complete=bool(frame['pairs']) and len(receipts)==len(frame['pairs']) and not self.pending and not errors and all(s['state']=='ready' for s in frame['scopes'])
        qualifying=sum(r['qualifying'] for r in receipts.values())
        state=('evaluated_positive' if qualifying else 'evaluated_zero') if complete else (
            'partial' if receipts else 'unavailable' if not self.targets else 'not_evaluated')
        if errors:state='incomplete'
        # A coherent publication includes coverage even when rows are unchanged.
        signature=digest(dict(rows=rows,state=state,errors=sorted(set(errors)),revision=frame['revision'],checked=len(receipts)))
        if getattr(self,'signature',None)!=signature:
            self.signature=signature; self.state=state; self.errors=sorted(set(errors))[:32]
            self._publish(rows,reason)

    def _options(self):
        # Only installed adapter dimensions with an admitted configured scope.
        scopes=(self.frame or {}).get('scopes',[])
        eligible=[s for s in scopes if s.get('supported') and s.get('configured') and s.get('authorized')]
        return {plural:sorted({s[singular] for s in eligible}) for plural,singular in
                (('venues','venue'),('sports','sport'),('leagues','league'),('markets','market'),('periods','period'))}

    def view(self, *, filters=None, offset=0, limit=50, since=None, epoch=None, query_id=None, expected_revision=None):
        filters=filters or Filters()
        if type(offset) is not int or not 0<=offset<=MAX_ROWS or type(limit) is not int or not 1<=limit<=MAX_PAGE:
            raise ValueError('scanner_page_capacity')
        if since is not None and (type(since) is not int or since<0):raise ValueError('scanner_revision_invalid')
        self.expire()
        with self.lock:
            options=self._options(); unsupported=[]
            for name in options:
                unsupported.extend(f'{name}:{x}' for x in getattr(filters,name) if x not in options[name])
            def matches(row):
                if row['category']!=filters.category:return False
                if filters.venues and not set(row['venues']).issubset(filters.venues):return False
                for plural,singular in (('sports','sport'),('leagues','league'),('markets','market'),('periods','period')):
                    if getattr(filters,plural) and row[singular] not in getattr(filters,plural):return False
                return (filters.minimum_edge is None or F(row['metric']['value'])>=F(filters.minimum_edge)) and (
                    filters.minimum_size is None or F(row['supported_capital_usd'])>=F(filters.minimum_size))
            rows=sorted((r for r in self.rows.values() if matches(r)),key=lambda r:(-F(r['metric']['value']),r['occurrence_id'],r['id']))
            query=digest(dict(filters=filters.to_dict(),offset=offset,limit=limit,server=self.server_id))
            contiguous=(since==self.publication or bool(self.journal) and self.journal[0]['revision']<=since+1<=self.publication) if since is not None else False
            resync=since is not None and (epoch!=self.epoch or query_id!=query or not contiguous or since>self.publication)
            if expected_revision is not None and expected_revision!=self.publication:
                raise ValueError('scanner_page_revision_changed')
            page=rows[offset:offset+limit]
            # Equivalent bounded incremental protocol: on a valid cursor replace
            # one globally ranked compact page atomically. IDs absent from this
            # page leave the view (withdrawal/filter/rank); no ambiguous patches.
            changed=since is None or resync or since!=self.publication
            frame=self.frame or {}
            instruments={i['id']:i for i in frame.get('instruments',[])}
            def selected(pair):
                legs=[instruments[k] for k in pair['legs']]
                if filters.venues and not {i['venue'] for i in legs}.issubset(filters.venues):return False
                return all(not getattr(filters,plural) or legs[0][singular] in getattr(filters,plural)
                    for plural,singular in (('sports','sport'),('leagues','league'),('markets','market'),('periods','period')))
            selected_pairs=[p for p in frame.get('pairs',[]) if selected(p)]
            evaluated=sum(p['id'] in self.receipts for p in selected_pairs)
            relevant_scopes=[s for s in frame.get('scopes',[]) if all(not getattr(filters,plural) or s[singular] in getattr(filters,plural) for plural,singular in
                (('venues','venue'),('sports','sport'),('leagues','league'),('markets','market'),('periods','period')))]
            complete=bool(selected_pairs) and evaluated==len(selected_pairs) and not unsupported and not self.errors and all(s['state']=='ready' for s in relevant_scopes) and not self.stopped
            selected_qualifying=sum(self.receipts[p['id']]['qualifying'] for p in selected_pairs if p['id'] in self.receipts)
            coverage_state=('evaluated_positive' if selected_qualifying else 'evaluated_zero') if complete else ('partial' if evaluated else self.state)
            out=dict(version=VERSION,mode='snapshot' if since is None else 'resync' if resync else 'replace_page' if changed else 'unchanged',
                server_id=self.server_id,epoch=self.epoch,publication_revision=self.publication,query_id=query,
                policy=self.policy.to_dict(),readiness_policy_revision=frame.get('policy_revision'),filters=filters.to_dict(),
                metric_basis=BASES[filters.category],filter_options=options,unsupported_filters=unsupported,
                rows=deepcopy(page) if changed else [],ranked_ids=[r['id'] for r in page],
                total_matching=len(rows),offset=offset,limit=limit,next_offset=offset+limit if offset+limit<len(rows) else None,
                expires_at=min((r['expires_at'] for r in page),key=instant,default=None),published_at=self.published_at,
                coverage=dict(state=coverage_state,complete=complete,compatible_pairs=len(selected_pairs),evaluated_pairs=evaluated,
                    qualifying_pairs=selected_qualifying if evaluated else None,no_qualifying_opportunities=complete and not selected_qualifying,
                    readiness_state=frame.get('state','not_evaluated'),errors=self.errors,scopes=deepcopy(relevant_scopes)),
                causal=dict(readiness_revision=frame.get('revision'),input_revision=self.capture_revision,
                    sql_post_commit_observation=deepcopy(self.sql_observation),capture_ms=self.last_capture_ms,
                    projection_published_at=self.published_at),
                bounds=dict(pairs=MAX_PAIRS,rows=MAX_ROWS,cache_bytes=MAX_CACHE_BYTES,input_bytes=MAX_INPUT_BYTES,
                    payload_bytes=MAX_PAYLOAD,journal_entries=MAX_JOURNAL,journal_bytes=MAX_JOURNAL_BYTES,
                    workers=1,work_per_turn=MAX_WORK_PER_TURN,maximum_page=MAX_PAGE),
                provider_requests=0)
            if len(encoded(out))>MAX_PAYLOAD:
                out.update(rows=[],ranked_ids=[],mode='resync',total_matching=0,next_offset=None)
                out['coverage'].update(state='incomplete',complete=False,no_qualifying_opportunities=False,errors=['scanner_payload_capacity'])
            return out
