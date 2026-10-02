"""One complete US event response, independently assessed without book admission.

The historical source is an explicit comparison baseline, never current state or
current applicability. A transport failure or catalog bound prevents semantic
claims. Closed/started complete responses still answer the delivery question.
"""
import base64
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path

from app.dashboard.session_projection import stable
from . import native_review_contract as review
from .native_payload import TRANSPORT_CONTRACT, parse, validate_envelope

POLICY = 'polymarket-us-metadata-delivery-v1'
SLICE = 'us-event-delivery-diagnostic-v1'
CONTRACT = dict(policy=POLICY, sports=['NHL'], discovery_only=True,
                generations=1, slice=SLICE)
TARGET = dict(event_id='127804', market_id='1061481')
REQUEST = dict(method='GET', host='https://gateway.polymarket.us',
               path='/v1/events/127804', params={})
WINDOW_BASIS = 'independent metadata-only diagnostic approval window; no paired-book applicability'
BASELINE_FILE = 'evidence/native-nyi-tor-20260930-v3/review-templates.json'
BASELINE_FILE_SHA256 = '2eb3e1e88b3c4a12f85283388f27451f6d72db174afbc04900b2d9021bf54fd7'
BASELINE_REVIEW_SHA256 = '9ea006bb8c3061ec3d5e077b90267a0005fc3c314665e8cc6d9189e2a71c5d61'
BASELINE_EVENT_SHA256 = '0fe52ab806ec06ad4d1868dbd6291faf6540ac32878ecfe346945a5c7f532735'
BASELINE_MARKET_SHA256 = 'cadb79eb1166da475183901c43eae3f1c0e3766b98af428162fff4fa762647b4'
BASELINE_CONTRACT_SHA256 = '507afbd995038277095c724454e3ceb048a793c339f2c5101607b0ef15e9c479'
BASELINE_PROVENANCE_SHA256 = 'b095c0e2d5fbed5d54e9e814585213ef5224a1ac6305c16d726ec8022ff9ddcd'
BASELINE_KEYS = frozenset(('review_file', 'review_file_sha256', 'review_sha256',
                          'event_metadata_sha256', 'market_metadata_sha256',
                          'event', 'market', 'semantic_review_contract', 'provenance'))


def enabled(spec):
    return spec.get('native_discovery', {}).get('slice') == SLICE


def _stamp(value):
    if not isinstance(value, str):
        raise ValueError('Diagnostic UTC timestamp required')
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() != timedelta(0):
        raise ValueError('Diagnostic UTC timestamp required')
    return result


def baseline_from_review(path=BASELINE_FILE):
    """Copy the sealed US baseline; do not modify its historical review."""
    raw = Path(path).read_bytes()
    if sha256(raw).hexdigest() != BASELINE_FILE_SHA256:
        raise ValueError('Historical diagnostic baseline file changed')
    records = json.loads(raw)
    record = next(r for r in records if r['sha256'] == BASELINE_REVIEW_SHA256)
    source = record['sources']['polymarket_us']
    baseline = dict(review_file=BASELINE_FILE, review_file_sha256=BASELINE_FILE_SHA256,
                    review_sha256=record['sha256'],
                    event_metadata_sha256=source['event_metadata_sha256'],
                    market_metadata_sha256=source['native_metadata_sha256'],
                    event=deepcopy(source['catalog_evidence']['event']['native_metadata']),
                    market=deepcopy(source['metadata']),
                    semantic_review_contract=deepcopy(source['semantic_review_contract']),
                    provenance=deepcopy(source['provenance']))
    _validate_baseline(baseline)
    return baseline


def _validate_baseline(value):
    if not isinstance(value, dict) or set(value) != BASELINE_KEYS:
        raise ValueError('Exact historical diagnostic baseline required')
    required = dict(review_file=BASELINE_FILE, review_file_sha256=BASELINE_FILE_SHA256,
                    review_sha256=BASELINE_REVIEW_SHA256,
                    event_metadata_sha256=BASELINE_EVENT_SHA256,
                    market_metadata_sha256=BASELINE_MARKET_SHA256)
    if any(value[k] != v for k, v in required.items()):
        raise ValueError('Historical diagnostic baseline reference changed')
    for field, expected in (('event', BASELINE_EVENT_SHA256),
                            ('market', BASELINE_MARKET_SHA256),
                            ('semantic_review_contract', BASELINE_CONTRACT_SHA256),
                            ('provenance', BASELINE_PROVENANCE_SHA256)):
        if stable(value[field]) != expected:
            raise ValueError('Historical diagnostic baseline contents changed')
    review.validate('polymarket_us', value['semantic_review_contract'],
                    value['event'], value['market'])


def validate_spec(spec):
    if spec.get('native_discovery') != CONTRACT:
        raise ValueError('Exact metadata-only discovery contract required')
    diagnostic = spec.get('us_metadata_diagnostic')
    if (not isinstance(diagnostic, dict) or set(diagnostic) !=
            {'policy', 'target', 'request', 'historical_baseline', 'validity_window'} or
            diagnostic['policy'] != POLICY or diagnostic['target'] != TARGET or
            diagnostic['request'] != REQUEST):
        raise ValueError('Exact US metadata-only diagnostic contract required')
    _validate_baseline(diagnostic['historical_baseline'])
    window = diagnostic['validity_window']
    if (not isinstance(window, dict) or set(window) != {'start', 'expires', 'basis'} or
            window['basis'] != WINDOW_BASIS):
        raise ValueError('Independent metadata-only diagnostic validity window required')
    start, expires = _stamp(window['start']), _stamp(window['expires'])
    if not timedelta(0) < expires-start <= timedelta(hours=24):
        raise ValueError('Finite diagnostic validity window of at most 24 hours required')
    if spec.get('native_review_records'):
        raise ValueError('Metadata-only diagnostic cannot admit paired reviews')
    if any(value is not None for value in spec.get('assessment_revisions', {}).values()):
        raise ValueError('Diagnostic economics remain unavailable')


def _id(value):
    return str(value) if type(value) in (str, int) else None


def _scalar(value):
    # State strings are a report, not a second unbounded raw metadata copy.
    if value is None or type(value) in (bool, int, float):
        return value
    if isinstance(value, str) and len(value) <= 256:
        return value
    return {'unsupported_type_or_length': type(value).__name__}


def _state(value, event=False):
    fields = ('active', 'closed', 'archived', 'hidden', 'period', 'live', 'ended') if event else (
        'active', 'closed', 'archived', 'hidden', 'status', 'ep3Status')
    return {k: dict(present=k in value, value=_scalar(value.get(k))) for k in fields}


def _identity(expected, event, market):
    if _id(event.get('id')) != TARGET['event_id']:
        return False, 'different_selected_event_identity'
    if any(event.get(k) != expected['event'].get(k) for k in ('slug', 'ticker')):
        return False, 'different_selected_event_identity'
    teams = event.get('teams')
    if (not isinstance(teams, list) or any(not isinstance(t, dict) for t in teams) or
            any(sum(_id(t.get('id')) == team for t in teams) != 1 for team in ('1494', '1490'))):
        return False, 'missing_duplicate_or_malformed_selected_event_teams'
    for team_id in ('1494', '1490'):
        current_team = next(t for t in teams if _id(t.get('id')) == team_id)
        expected_team = next(t for t in expected['event']['teams'] if _id(t.get('id')) == team_id)
        if any(current_team.get(k) != expected_team.get(k) for k in ('name', 'safeName', 'league')):
            return False, 'conflicting_selected_event_team_identity'
    if not isinstance(market, dict) or _id(market.get('id')) != TARGET['market_id']:
        return False, 'absent_selected_market_in_complete_response'
    if any(market.get(k) != expected['market'].get(k) for k in (
            'slug', 'marketType', 'sportsMarketType', 'sportsMarketTypeV2')):
        return False, 'different_selected_market_identity'
    sides = market.get('marketSides')
    if not isinstance(sides, list) or len(sides) != 2 or any(not isinstance(s, dict) for s in sides):
        return False, 'unsupported_selected_market_sides'
    expected_sides = expected['market']['marketSides']
    for target in expected_sides:
        matches = [s for s in sides if _id(s.get('id')) == _id(target['id'])]
        if len(matches) != 1:
            return False, 'missing_duplicate_or_changed_selected_market_side'
        side = matches[0]
        if (type(side.get('long')) is not bool or side['long'] != target['long'] or
                _id(side.get('marketId')) != TARGET['market_id'] or
                _id(side.get('teamId')) != _id(target['teamId']) or
                not isinstance(side.get('team'), dict) or
                _id(side['team'].get('id')) != _id(target['teamId']) or
                any(side['team'].get(k) != target['team'].get(k) for k in ('name', 'safeName', 'league'))):
            return False, 'conflicting_selected_market_side_identity'
    return True, 'exact_selected_event_market_side_identity'


def _term_agreement(expected, current, event=False):
    """The existing review projection, with state reported independently.

    compare() deliberately gates paired reviews on current eligibility. A closed
    event must therefore retain its compare rejection while its independently
    equal material projection may still be reported as agreeing.
    """
    if not review.valid_observations('polymarket_us', current, event=event):
        return False, 'malformed_mutable_observation'
    if review.project('polymarket_us', expected, event=event) != review.project(
            'polymarket_us', current, event=event):
        return False, 'changed_missing_unknown_or_conflicting_terms_require_review'
    return True, 'semantic_material_projection_agrees'


def evaluate(pages, spec, at, admission_error=None):
    """Assess one retained receipt. No partial prefix is interpreted as metadata."""
    validate_spec(spec)
    at = _stamp(at.isoformat() if isinstance(at, datetime) else at)
    baseline = spec['us_metadata_diagnostic']['historical_baseline']
    receipts = [p for p in pages if p.get('source') == 'polymarket_us' and
                p.get('type') == 'prediction_discovery_http']
    row = dict(type='us_metadata_delivery_diagnostic', policy=POLICY,
               assessment_at=at.isoformat(), target=deepcopy(TARGET),
               historical_reference={k: baseline[k] for k in (
                   'review_file', 'review_file_sha256', 'review_sha256',
                   'event_metadata_sha256', 'market_metadata_sha256')},
               validity_window=deepcopy(spec['us_metadata_diagnostic']['validity_window']),
               delivery=dict(transport_complete=False, reason='missing_single_exact_receipt'),
               json=dict(whole_document_valid=None, expected_envelope_valid=None,
                         reason='complete_framing_required'),
               metadata_admission=dict(admitted=False, reason=admission_error or 'complete_validation_required'),
               target_identity=dict(agrees=None, reason='not_admitted'),
               material_terms=dict(event_agrees=None, market_agrees=None, reason='not_admitted'),
               current_state=dict(event=None, market=None, supported=None, reason='not_admitted'),
               pregame_eligibility=dict(eligible=None, reason='not_admitted',
                                        required_start_margin_seconds=300),
               scope=dict(metadata_only=True, books=0, paired_comparisons=False,
                          new_supported_review=False, economics='unavailable'))
    if len(receipts) != 1 or any(p.get('source') == 'kalshi' and p.get('type') ==
                                 'prediction_discovery_http' for p in pages):
        row['delivery']['reason'] = 'diagnostic_request_scope_violation'
        return row
    page = receipts[0]
    if (page.get('path') != REQUEST['path'] or page.get('params') != {} or
            page.get('transport_policy') != TRANSPORT_CONTRACT):
        row['delivery']['reason'] = 'diagnostic_request_scope_violation'
        return row
    usage = page.get('resource_usage', {})
    complete = page.get('complete') is True and page.get('wire_complete') is True
    row['delivery'] = dict(transport_complete=complete, reason=page.get('delivery_reason'),
        status=page.get('status'), received_at=page.get('received_at'),
        body_sha256=page.get('body_sha256'), http_plaintext_sha256=page.get('http_plaintext_sha256'),
        counts={k: usage.get(k) for k in ('wire_bytes', 'entity_bytes_read', 'retained_body_bytes',
            'decoded_bytes', 'http_header_wire_bytes', 'framed_entity_bytes')},
        framing_state=usage.get('http_framing_state'), peer_close_observed=usage.get('peer_close_observed'))
    if not complete:
        row['metadata_admission']['reason'] = admission_error or page.get('delivery_reason') or 'incomplete_delivery'
        return row
    try:
        encoded = page.get('body_b64')
        if not isinstance(encoded, str) or len(encoded) > ((2*1024*1024+2)//3)*4:
            raise ValueError('native_decoded_byte_cap')
        raw = base64.b64decode(encoded, validate=True)
        if sha256(raw).hexdigest() != page.get('body_sha256'):
            raise ValueError('retained_body_hash_mismatch')
        if page.get('redaction_reason') or page.get('delivery_reason') in (
                'native_unsupported_encoding', 'native_credential_echo_suppressed'):
            raise ValueError(page.get('redaction_reason') or page['delivery_reason'])
        document = parse(raw, limits=TRANSPORT_CONTRACT)
        row['json'].update(whole_document_valid=True, reason=None)
        validate_envelope(document, REQUEST['path'])
        row['json']['expected_envelope_valid'] = True
    except (ValueError, TypeError, RecursionError) as exc:
        if isinstance(exc, json.JSONDecodeError):
            text = raw.decode('utf-8')
            incomplete = exc.pos >= len(text.rstrip()) or 'Unterminated' in exc.msg
            reason = 'native_incomplete_json' if incomplete else 'native_malformed_json'
        else:
            reason = str(exc) if str(exc).startswith(('native_', 'retained_')) else 'native_malformed_json'
        if row['json']['whole_document_valid'] is True:
            row['json']['expected_envelope_valid'] = False
        else:
            # Exceeding a parsing bound or losing raw provenance proves no JSON
            # invalidity. Whole-document validity remains unresolved.
            unresolved = reason in ('native_decoded_byte_cap', 'native_json_depth_cap',
                'native_json_structure_cap', 'native_parse_expansion_cap',
                'native_unsupported_encoding', 'native_credential_echo_suppressed',
                'retained_body_hash_mismatch')
            row['json']['whole_document_valid'] = None if unresolved else False
        row['json']['reason'] = reason
        row['metadata_admission']['reason'] = admission_error or page.get('delivery_reason') or reason
        return row
    if page.get('usable_metadata') is not True or page.get('status') != 200 or admission_error:
        row['metadata_admission']['reason'] = admission_error or page.get('delivery_reason') or 'native_unusable_metadata'
        return row
    row['metadata_admission'] = dict(admitted=True, reason='complete_framing_whole_json_and_catalog_admitted')
    event = document['event']
    embedded = event.get('markets')
    selected = [m for m in embedded if isinstance(m, dict) and _id(m.get('id')) == TARGET['market_id']] if isinstance(embedded, list) else []
    if not isinstance(embedded, list) or any(not isinstance(m, dict) for m in embedded):
        identity_reason = 'malformed_embedded_markets_in_complete_response'
        market = None
    elif len(selected) != 1:
        identity_reason = 'duplicate_selected_market_in_complete_response' if len(selected)>1 else 'absent_selected_market_in_complete_response'
        market = None
    else:
        market = selected[0]
        _, identity_reason = _identity(baseline, event, market)
    agrees = identity_reason == 'exact_selected_event_market_side_identity'
    row['target_identity'] = dict(agrees=agrees, reason=identity_reason,
        received_event_id=_scalar(event.get('id')),
        selected_market_occurrences=len(selected), event_metadata_sha256=stable(event),
        market_metadata_sha256=stable(market) if market is not None else None)
    event_terms, event_reason = _term_agreement(baseline['event'], event, event=True)
    market_terms, market_reason = _term_agreement(baseline['market'], market) if market is not None else (False, identity_reason)
    combined_event = review.compare('polymarket_us', baseline['event'], event, event=True)
    combined_market = review.compare('polymarket_us', baseline['market'], market) if market is not None else (False, identity_reason)
    row['material_terms'] = dict(event_agrees=event_terms, market_agrees=market_terms,
        event_reason=event_reason, market_reason=market_reason,
        ordinary_paired_semantic_review=dict(event=dict(admitted=combined_event[0], reason=combined_event[1]),
            market=dict(admitted=combined_market[0], reason=combined_market[1])),
        basis='native-semantic-review-v1 exact presence/type/material projection; unknown changes require review')
    event_state = review.eligibility('polymarket_us', event, event=True)
    market_state = review.eligibility('polymarket_us', market) if market is not None else identity_reason
    row['current_state'] = dict(event=_state(event, event=True),
        market=_state(market) if market is not None else None,
        supported=event_state is None and market_state is None,
        event_reason=event_state, market_reason=market_state)
    starts = [event.get('startTime'), event.get('startDate'), market.get('gameStartTime') if market else None]
    try:
        times = [_stamp(s) for s in starts]
        if len(set(times)) != 1:
            raise ValueError('conflicting_current_schedule')
        scheduled = times[0]
        schedule_reason = None if at+timedelta(seconds=300) < scheduled else 'target_outside_prestart_applicability'
    except (ValueError, TypeError):
        scheduled = None
        schedule_reason = 'missing_malformed_or_conflicting_current_schedule'
    window = spec['us_metadata_diagnostic']['validity_window']
    window_valid = _stamp(window['start']) <= at <= _stamp(window['expires'])
    reason = (identity_reason if not agrees else event_reason if not event_terms else market_reason if not market_terms
              else event_state or market_state or schedule_reason or
              ('outside_diagnostic_validity_window' if not window_valid else None))
    row['pregame_eligibility'] = dict(eligible=reason is None,
        reason=reason or 'current_identity_terms_open_phase_and_five_minute_margin_supported',
        assessment_at=at.isoformat(), scheduled_start=scheduled.isoformat() if scheduled else None,
        required_start_margin_seconds=300, diagnostic_window_valid=window_valid,
        creates_paired_book_applicability=False)
    return row


def verify(rows):
    """Fresh-process recomputation from durable receipt; no prefix reconstruction."""
    started = [r for r in rows if r.get('type') == 'session_started']
    reports = [r for r in rows if r.get('type') == 'us_metadata_delivery_diagnostic']
    if len(started) != 1 or len(reports) != 1:
        raise ValueError('Exactly one durable diagnostic report and start required')
    spec = started[0]['spec']
    report = reports[0]
    reason = report['metadata_admission']['reason']
    # Catalog-resource refusal is independently recorded in the ordinary source
    # stop. Never invent it from a successful receipt during replay.
    admission_error = reason if reason in ('native_source_inventory_cap', 'native_catalog_parse_error') else None
    if admission_error and not any(r.get('type') == 'native_source_terminal' and
            r.get('source') == 'polymarket_us' and r.get('reason') == admission_error for r in rows):
        # continuous also retains this exact reason in catalog selection/health.
        if not any(r.get('source') == 'polymarket_us' and r.get('reason') == admission_error for r in rows):
            raise ValueError('Missing durable diagnostic catalog refusal')
    expected = evaluate(rows, spec, report['assessment_at'], admission_error=admission_error)
    journal_fields = {'source', 'session_id', 'ingress_id', 'observed_at', 'health', 'economics'}
    semantic_report = {k: v for k, v in report.items() if k not in journal_fields}
    if (semantic_report != expected or report.get('source', 'polymarket_us') != 'polymarket_us' or
            report.get('economics') is not None or
            'session_id' in report and report['session_id'] != started[0].get('session_id')):
        raise ValueError('Durable metadata diagnostic assessment changed')
    return dict(verified=True, report_sha256=stable(expected),
                transport_complete=expected['delivery']['transport_complete'],
                whole_document_valid=expected['json']['whole_document_valid'])
