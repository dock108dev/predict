"""Additional fail-closed gates for explicitly versioned future observations.

Receipt checks do not become source-clock claims. This module can veto an existing
calculation, never make an unqualified fee/settlement calculation qualified.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
import hashlib

VERSION = 'native-prerequisites-1'

def stamp(value):
    if not isinstance(value,str):raise ValueError('timestamp string required')
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.utcoffset() is None:raise ValueError('timezone required')
    return result

def number(value):
    if not isinstance(value,str):raise ValueError('decimal string required')
    d=Decimal(value)
    if not d.is_finite() or len(d.as_tuple().digits)>24 or abs(d.as_tuple().exponent)>12:raise ValueError('bounded finite number required')
    return d

def seconds(a,b):
    delta=stamp(a)-stamp(b)
    return Decimal(delta.days*86400+delta.seconds)+Decimal(delta.microseconds)/1000000

def retained(record):
    try:
        return hashlib.sha256(record['raw_text'].encode()).hexdigest()==record['raw_sha256']
    except (KeyError,TypeError,AttributeError):return False

def proof(record,kind,scope,at):
    """A reviewed, retained native claim with explicit validity, never an inferred date."""
    if not isinstance(record,dict):return False
    try:
        body=record['retained_text'].encode()
        return (record['kind']==kind and record['scope']==scope and
                record['source_kind']=='native_document' and record['review_status']=='reviewed' and
                record['conflict'] is False and record['supported'] is True and
                record['url'].startswith('https://') and
                hashlib.sha256(body).hexdigest()==record['sha256'] and
                bool(record['passage']) and record['passage'] in record['retained_text'] and
                stamp(record['effective_from'])<=stamp(at)<stamp(record['effective_to']) and
                bool(record['precedence']) and stamp(record['retrieved_at']) is not None)
    except (KeyError,TypeError,ValueError,AttributeError):return False

def evaluate(point,contexts):
    with localcontext() as arithmetic:
        arithmetic.prec=100
        return _evaluate(point,contexts)

def _evaluate(point,contexts):
    reasons=[];intervals=[];rows=[]
    if not isinstance(contexts,dict):contexts={}
    for card in point['cards']:
        book=card.get('book')
        if not book:reasons.append('Book unavailable');continue
        ctx=contexts.get(book['id']) or {};issues=[]
        if not isinstance(ctx,dict):ctx={}
        scope=ctx.get('scope')
        # A context must bind the native ref in this exact retained book.
        ref=book.get('native_qualification_scope')
        if not ref or scope!=ref:issues.append('Native state/time/fee/rule scope unavailable or mismatched')
        at=point['at'];docs=ctx.get('documents') or {}
        if not isinstance(docs,dict):docs={}
        if card.get('connection')!='connected' or book.get('sync')!='synchronized':issues.append('Book connection/synchronization unavailable')
        if book.get('market_state') not in ('active','unknown'):issues.append('Native book state is not active')
        for kind in ('state_semantics','timestamp_semantics','fees','settlement'):
            if not proof(docs.get(kind),kind,scope,at):issues.append(kind+' provenance unavailable, conflicting or outside effective interval')
        state=ctx.get('state',{})
        try:
            if (state['value']!='active' or state['book_id']!=book['id'] or
                state['source_kind']!='native_observation' or not retained(state) or
                state['connection_epoch']!=ctx['connection_epoch'] or state['connection_epoch']!=book.get('connection_epoch') or
                not state['continuity_verified'] or
                not stamp(state['valid_from'])<=stamp(at)<=stamp(state['valid_until']) or
                not stamp(state['observed_at'])<=stamp(state['valid_from'])<=stamp(at)):
                raise ValueError('invalid state')
        except (KeyError,TypeError,ValueError):issues.append('Active state validity/continuity at cutoff unestablished')
        try:
            age=seconds(at,book['received_at'])
            if age!=number(str(card['age_seconds'])):issues.append('Receipt age disagrees with original timestamps')
            if age<0 or age>15:issues.append('Receipt stale at cutoff (15-second limit)')
            clock=ctx['clock']
            # Bounds express local UTC minus exchange clock. They require retained
            # local+source offset evidence; a server Date header is insufficient.
            low=number(clock['offset_min_seconds']);high=number(clock['offset_max_seconds'])
            if (low>high or clock['kind']!='bounded_relative_clock' or not retained(clock) or
                clock['connection_epoch']!=ctx['connection_epoch'] or
                not stamp(clock['valid_from'])<=stamp(at)<=stamp(clock['valid_until']) or
                not clock['local_clock_continuity_verified']):raise ValueError('unknown clock')
            if ctx['source_timestamp_meaning']!='book_state_as_of' or not ctx['source_time_progress_verified']:
                raise ValueError('unsupported timestamp meaning/progress')
            source=book['source_at']
            # age = local cutoff - (exchange timestamp + relative clock offset).
            raw_age=seconds(at,source);amin=raw_age-high;amax=raw_age-low
            if amin<0 or amax>15:issues.append('Source age interval fails 15-second freshness limit')
            if stamp(source)>stamp(book['received_at']) and low>=0:issues.append('Source timestamp after receipt')
            epoch='1970-01-01T00:00:00+00:00'
            earliest=seconds(source,epoch)+low;latest=seconds(source,epoch)+high
            if seconds(clock['valid_from'],epoch)>earliest or seconds(clock['valid_until'],epoch)<latest:raise ValueError('Clock bound does not cover source observation')
            intervals.append((earliest,latest))
            clock_result={'age_min_seconds':str(amin),'age_max_seconds':str(amax)}
        except (KeyError,TypeError,ValueError,InvalidOperation):
            issues.append('Timestamp semantics or bounded clock uncertainty unavailable');clock_result=None
        rows.append(dict(book_id=book['id'],reasons=issues,source_age=clock_result,
            provenance={kind:{k:doc.get(k) for k in ('url','sha256','scope','effective_from','effective_to','retrieved_at','precedence','review_status','conflict','supported')} for kind,doc in docs.items() if isinstance(doc,dict)},
            state_evidence_sha256=state.get('raw_sha256') if isinstance(state,dict) else None,
            clock_evidence_sha256=(ctx.get('clock') or {}).get('raw_sha256') if isinstance(ctx.get('clock'),dict) else None))
        reasons.extend(issues)
    try:
        receipts=[stamp(c['book']['received_at']) for c in point['cards'] if c.get('book')]
        if len(receipts)<2 or (max(receipts)-min(receipts)).total_seconds()>5:reasons.append('Receipt alignment exceeds 5 seconds or is unavailable')
    except (KeyError,TypeError,ValueError):reasons.append('Receipt alignment unavailable')
    if len(intervals)!=len(point['cards']) or len(intervals)<2:
        reasons.append('Source alignment interval unavailable')
    elif max(hi for lo,hi in intervals)-min(lo for lo,hi in intervals)>5:
        reasons.append('Worst-case source alignment exceeds 5 seconds')
    return dict(version=VERSION,prerequisites_supported=not reasons,reasons=list(dict.fromkeys(reasons)),books=rows,
                limitation='Additional veto only; does not establish net fees, settlement equivalence, fillability or beta readiness.')

def apply(result,point,contexts):
    gate=evaluate(point,contexts);result['future_qualification']=gate
    if not gate['prerequisites_supported']:
        for c in result['candidates']:
            c['reasons']=list(dict.fromkeys(c['reasons']+gate['reasons']))
            c['usable']=False;c['current_executable']=False;c['positive_normal_scenario']=False
            for key in ('profit','return_pct','worst_case_all_outcomes'):c[key]=None
        result['ev']['expected_profit']=None;result['ev']['return_pct']=None;result['ev']['break_even_pct']=None
        result['ev']['leg']['reasons']=list(dict.fromkeys(result['ev']['leg']['reasons']+gate['reasons']))
    return result
