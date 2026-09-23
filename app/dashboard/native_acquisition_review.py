"""Hash-bound facts from one closed acquisition, never historical fee defaults."""
import hashlib
import json
from pathlib import Path

VERSION = 'atl-gb-native-review-2'
ROOT = Path(__file__).resolve().parents[2] / 'evidence/b6-native-acquisition-20260923-v1'
HASHES = {
    '01-response.bin': 'd2ec6e7db2b70feea6054737ba97640f52ccb01ae95a0fc99773ce72d58319ee',
    '02-response.bin': '4d755a11d76cd85bec7a4758a2d226815fd2a935a5563dbafae35ee9d373da45',
    '03-response.bin': '7183ba45e69878326333f1ce4b8ba9cb07e65d04624969d27a1dd1afef4f109a',
    'requests.json': '2b6efd8386f5ef0d676f2ecfbb886f633116456295eafac29820dbe40f4f8294',
    'result.json': '780ac022fa89056f1db7023dbaec4e91342b214e953e5ee49cc49d1ab152cebe',
}
HISTORICAL_FEE_GAP = 'Kalshi current fee metadata acquired; historical fee baseline and schedule applicability remain unestablished'


def facts(root=ROOT):
    captured = {}
    for name, expected in HASHES.items():
        data = (root / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Acquisition evidence hash mismatch: ' + name)
        captured[name] = data
    series = json.loads(captured['01-response.bin'])['series']
    changes = json.loads(captured['02-response.bin'])
    requests = json.loads(captured['requests.json'])
    result = json.loads(captured['result.json'])
    return dict(
        acquisition='b6-native-acquisition-20260923-v1',
        evidence_sha256=dict(HASHES),
        historical_cutoff='2026-09-23T15:09:37.623609+00:00',
        observed_at=requests[0]['end_utc'],
        summary='Three GET attempts; stopped on HTTP 429. Current Kalshi series metadata and an empty event fee history were retained. Five request slots unused; no retry.',
        kalshi=dict(
            series=series['ticker'], event='KXNFLGAME-26SEP24ATLGB',
            markets=['KXNFLGAME-26SEP24ATLGB-ATL', 'KXNFLGAME-26SEP24ATLGB-GB'],
            observed_fee_type=series['fee_type'],
            observed_fee_multiplier=str(series['fee_multiplier']),
            metadata_last_updated=series['last_updated_ts'],
            metadata_time_meaning="Series metadata last updated; not an explicit fee scheduled/effective timestamp or a version history.",
            event_history_pagination_complete=changes['cursor'] == '',
            returned_event_overrides=changes['event_fee_changes'],
            event_history_scope='Exact event query; no overrides returned at acquisition time. Empty history does not establish the historical series fee baseline.',
            precedence='Retained endpoint definitions: event overrides layer over series; null override fields fall back to their corresponding series field. No override record was returned to apply.',
            historical_fee_baseline_qualified=False,
            contract_terms_url=series['contract_terms_url'],
            contract_filing_url=series['contract_url'],
            contract_document_retrieved=False,
            contract_link_basis='Exact KXNFLGAME response identifies this current terms URL. Its contents, effective version and precedence were not retrieved because the attempt had already stopped.',
            fee_schedule_http_status=requests[2]['status'],
            fee_schedule_body_is_document=False,
        ),
        fee_and_rule_qualification=dict(
            applicable_historical_schedules=False,
            kalshi_account_balance_precision=None,
            account_fee_or_rebate_terms=None,
            resting_order_split=None,
            exact_entry_fees=None,
            applicable_fee_bounds=None,
            settlement_charges=None,
            us_market='779756', us_event='108683',
            us_retained_coefficient='0.0695', prior_document_theta='0.06',
            us_coefficient_conflict_resolved=False,
            us_exact_contract_document_reference=None,
            exceptional_settlement_equivalence=False,
            limitation='No new fee formula, rounding assumption, rebate, zero settlement charge or numerical fee bound is established by the two successful responses. Prior documentation scenarios are not applicable historical fees.',
        ),
        historical_state_qualified=False,
        historical_clock_offset_qualified=False,
        c3_c4_freshness_failures_preserved=True,
        original_fee_engine_audit='Preserved: the original engine has no eligible historical metadata context. Current metadata is shown as acquired evidence, not injected as a fabricated scheduled baseline.',
        execution=dict(consumed=result['consumed'], requests=result['requests'], unused_slots=8-result['requests'],
                       stop_reason=result['stop_reason'], retry_allowed=result['retry_allowed'],
                       elapsed_seconds=result['elapsed_seconds'], credentials_accessed=False, credits=0),
    )


def annotate(result):
    evidence = facts()
    review = result['retained_review']
    review['version'] = VERSION
    review['acquired_evidence'] = evidence
    review['note'] = 'Retrospective review using separately acquired, hash-bound metadata. Historical fees, state, settlement and clocks remain unqualified; original calculations and review v1 are preserved.'
    for candidate in result['candidates']:
        for leg in candidate['legs']:
            leg['reasons'] = [HISTORICAL_FEE_GAP if x == 'fee metadata: scoped Kalshi series and event fee metadata required' else x for x in leg['reasons']]
        candidate['reasons'] = [HISTORICAL_FEE_GAP if x == 'fee metadata: scoped Kalshi series and event fee metadata required' else x for x in candidate['reasons']]
    leg = result['ev']['leg']
    leg['reasons'] = [HISTORICAL_FEE_GAP if x == 'fee metadata: scoped Kalshi series and event fee metadata required' else x for x in leg['reasons']]
    return result
