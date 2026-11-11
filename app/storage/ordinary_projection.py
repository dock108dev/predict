"""Compact immutable publication members for list and replay views."""


def compact_row(row):
    """Keep list/drawer inputs; full semantic proof stays in the exact member."""
    row = dict(row)
    for key in ('common_odds', 'reference_odds', 'snapshot_identity'):
        row.pop(key, None)
    row['selection'] = {k:v for k,v in row.get('selection', {}).items()
        if k in ('participant','predicate','signed_line','result_interpretation','label')}
    row['same_outcome'] = {k:v for k,v in row.get('same_outcome', {}).items() if k != 'key'}
    if row.get('reference_calculation'):
        row['reference_calculation'] = {k:v for k,v in row['reference_calculation'].items()
            if k not in ('authority','occurrence')}
    return row


def compact_member(part):
    """Same exact list projection as legacy root composition; private input."""
    for row in part['rows']:
        # Ordinary sorting needs compact prices/results. Full binding,
        # depth and provenance graphs remain in this immutable member,
        # reached by evidence_result_id instead of duplicated per head.
        for field in ('binding','observed_depth','occurrence_match','occurrence_link',
                      'provider_clocks','observation_time_evidence','source_health',
                      'input_basis','native_contract_id','observation_revision','fee_applicability'):
            row.pop(field,None)
        # Full financial provenance belongs to the immutable selected
        # member. The root keeps exact numeric inputs, IDs and clocks,
        # without copying the same rules/occurrence graph on every row.
        if row.get('snapshot_benchmark'):
            row['snapshot_benchmark']={k:v for k,v in row['snapshot_benchmark'].items()
                if k in ('bookmaker','ids','odds','selected','selected_odds','probability',
                    'source_at','received_at','method','conditioning','selected_predicate')}
            row['reference']=None
        disclosure=row.get('reference_calculation')
        if disclosure and disclosure.get('occurrence'):
            disclosure['occurrence']={k:v for k,v in disclosure['occurrence'].items()
                if k in ('occurrence','method','scoring','scoring_basis','equality_basis')}
        for name in ('conditional_trade_benchmark','conservative_trade_benchmark'):
            metric=row.get(name)
            if not metric:continue
            for field in ('applicability','fee_scenarios','rounding_trace','policy'):
                metric.pop(field,None)
            if metric.get('evidence'):
                metric['evidence']={k:v for k,v in metric['evidence'].items()
                    if k in ('version','source_url','sha256','path','reviewed_at','review_before',
                        'fee_rate','series_id','event_id','metadata_revision')}
        if row.get('book_confirmation'):
            row['book_confirmation']={k:row['book_confirmation'][k] for k in ('confirmed_at','basis')}
        row['evidence_result_id']=part['id']
        row['captured_at']=part['captured_at']
    part['rows'] = [compact_row(row) for row in part['rows']]
    for pair in part['pairs']:
        pair['evidence_result_id']=part['id']
    part['references']=[{k:v for k,v in r.items() if k!='original_record'} for r in part['references']]
    for row in part['rows']:
        row['publication_policy']=part['publication']['policy']
        row['publication_epoch']=part['publication']['epoch']
    return part


