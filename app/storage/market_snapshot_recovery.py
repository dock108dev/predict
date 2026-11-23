"""Link only authentically reconstructable retained checkpoint acquisitions.

No network, new arithmetic result, changed fee setting or rewritten historical
record. A missing original response or ambiguous ledger witness remains legacy.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from app.comparison import current_pregame as math
from app.comparison.acquisition import calculation, provenance
from app.collection.sportsgameodds_adapter import parse_page
from app.collection.original_receipts import read as original
from app.research import experiment
from . import acquisition_snapshot as owner
from .store import ROOT, encoded, hashed, stamp


def _economic(value):
    if isinstance(value, list):
        return [_economic(item) for item in value]
    if isinstance(value, dict):
        return {key:_economic(item) for key,item in value.items()
                if key not in ('acquisition','required_input_prices','input_revision','baseline_id')}
    return value


def bind(snapshot, page, checkpoint_id):
    """Add proven provenance to a copy while retaining captured EV and version."""
    if encoded(snapshot['raw_quotes']) != encoded(page.quotes):
        raise ValueError('retained_page_quote_membership_differs')
    if snapshot['receipt_sha256'] != page.receipt_sha256:
        raise ValueError('retained_page_receipt_differs')
    result = deepcopy(snapshot)
    witness = provenance(page)
    if not witness:
        raise ValueError('retained_ledger_identity_required')
    references = result['references']
    if any(entry['facts']['receipt_sha256'] != page.receipt_sha256
           or stamp(entry['facts']['received_at']) != stamp(page.received_at) for entry in references):
        raise ValueError('retained_reference_membership_differs')
    for entry in references:
        entry['facts']['acquisition'] = witness
        entry['revision'] = hashed({key:value for key,value in entry['facts'].items()
                                   if key not in ('received_at','receipt_sha256')})
    inputs = math.ReferenceInputs({page.events[0]['event_id']:references},
                                  books=math.COHERENT_POLICIES[math.EXPANSION_POLICY])
    for offer in result['offers']:
        record = offer['record']
        if (record['quote']['provenance']['sha256'] != page.receipt_sha256
                or stamp(record['quote']['times']['received_at']) != stamp(page.received_at)):
            raise ValueError('retained_offer_membership_differs')
        record.setdefault('comparison_source_metadata',{})['acquisition'] = witness
        payload = offer.get('calculation_payload')
        at = stamp((payload or {}).get('calculated_at') or result['times'].get('inputs_cutoff')
                   or result['times']['known_at'])
        for key,function in (('screen_reference',math.reference),('coherent_reference',math.qualified_coherent_reference)):
            previous = offer.get(key)
            if previous and (previous.get('probability') is not None or previous.get('probabilities')):
                bound = function(record,inputs,at=at)
                if _economic(bound) != _economic(previous):
                    raise ValueError('retained_reference_policy_differs')
                offer[key] = bound
        if payload is None:
            continue
        reference = payload.get('reference')
        if reference:
            bound = math.reference(record,inputs,at=at)
            if _economic(bound) != _economic(reference):
                raise ValueError('retained_reference_policy_differs')
            payload['reference'] = bound
            if offer.get('screen_reference'):
                offer['screen_reference'] = bound
            payload['acquisition'] = calculation(record,bound)
        elif payload.get('raw',{}).get('net_ev') is not None:
            raise ValueError('retained_numeric_reference_missing')
        for key in ('coherent_probability',):
            previous = payload.get(key)
            if previous and previous.get('probabilities'):
                bound = math.qualified_coherent_reference(record,inputs,at=at)
                if _economic(bound) != _economic(previous):
                    raise ValueError('retained_coherent_policy_differs')
                payload[key] = bound
                if offer.get('coherent_reference'):
                    offer['coherent_reference'] = bound
        # Stored arithmetic, fee mode and original calculation revision survive.
    result['acquisition'] = dict(result.get('acquisition') or {}, **witness,
        linked_checkpoint_id=checkpoint_id, arithmetic='original_captured_result_unchanged')
    return result


def recover(db, *, ledger_path=None, receipt_root=None):
    """Use the original durable reservation identity/order, never rounded time IDs."""
    ledger_path = Path(ledger_path or ROOT/'.local/predict-odds/sportsgameodds-ledger.sqlite3')
    if not ledger_path.is_file():
        return dict(linked=0, skipped=dict(retained_ledger_missing=1), provider_requests=0)
    receipt_root = receipt_root or ledger_path.parent/'original-responses'
    skipped, linked = Counter(), 0
    with sqlite3.connect(ledger_path.as_uri()+'?mode=ro',uri=True) as ledger:
        ledger.row_factory = sqlite3.Row
        ids = db.execute("SELECT id FROM public.ev_experiment_record WHERE kind='checkpoint' ORDER BY recorded_at,id").fetchall()
        for row in ids:
            checkpoint = experiment._value(experiment._get(db,row['id']),experiment._closure(db,[row['id']]))
            snapshot = checkpoint.get('snapshot') or {}
            acquisition = snapshot.get('acquisition') or {}
            descriptor = acquisition.get('original_response') or {}
            try:
                metadata, body = original(descriptor['id'],root=receipt_root)
                params = snapshot['request_scope']
                if metadata != descriptor or metadata['request_scope'] != params:
                    raise ValueError('retained_original_descriptor_differs')
                candidates = list(ledger.execute('''SELECT r.id,r.rowid reservation_order,r.created_at,t.query
                    FROM sgo_object_reservation r JOIN sgo_request_trace t ON t.reservation_id=r.id
                    WHERE t.http_status=200 AND t.response_sha256=? AND t.response_at=? AND r.status='resolved' ''',
                    (metadata['receipt_sha256'],stamp(metadata['received_at']).timestamp())))
                candidates = [item for item in candidates if json.loads(item['query']) == params]
                if len(candidates) != 1:
                    raise ValueError('retained_ledger_membership_unproven')
                attempt = candidates[0]
                if (db.execute('SELECT 1 FROM public.market_pull WHERE pull_id=%s',(attempt['id'],)).fetchone()
                        or db.execute('SELECT 1 FROM public.market_pull_receipt WHERE attempt_id=%s',
                                      (attempt['id'],)).fetchone()):
                    skipped['already_linked'] += 1
                    continue
                parsed = parse_page(body,metadata['received_at'],venues=set(params['bookmakerID'].split(',')))
                if len(parsed.events) != 1 or parsed.events[0]['event_id'] != params['eventIDs']:
                    raise ValueError('retained_explicit_event_membership_unproven')
                page = replace(parsed,pull_id=attempt['id'],attempt_id=attempt['id'],request_scope=params,
                               received_at=metadata['received_at'])
                frozen = bind(snapshot,page,row['id'])
                # SQLite reservation rowid is durable request-start ordering in
                # the existing single ledger. Negative legacy order keeps any
                # actual new manifest ahead of all recovered older operations.
                order = -9_000_000_000_000_000_000 + attempt['reservation_order']
                with db.transaction():
                    owner.start(db,params,pull_id=page.pull_id,started_order=order,
                        at=datetime.fromtimestamp(attempt['created_at'],timezone.utc),event=checkpoint.get('event'))
                    owner.publish(db,page,frozen,details=dict(linked_checkpoint_id=row['id'],
                        legacy_order_source='original_sgo_reservation_rowid', original_response=metadata))
                linked += 1
            except (KeyError,ValueError,OSError,sqlite3.Error) as exc:
                skipped[str(exc)[:120] or type(exc).__name__] += 1
    return dict(linked=linked, skipped=dict(skipped), provider_requests=0)


if __name__ == '__main__':
    from .store import connect
    with connect() as db:
        print(json.dumps(recover(db),sort_keys=True))
