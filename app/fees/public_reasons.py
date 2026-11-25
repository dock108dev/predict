"""Owner-facing fee evidence reasons and safe diagnostic logging."""

from app.diagnostics import failure

UNAVAILABLE = 'fee_evidence_unavailable'
APPROVAL_UNPARSEABLE = 'fee_approval_unparseable'

# Fee reviewer codes and vetted historical replay reasons. Other evidence
# strings and exception messages use the public fallback.
REASONS = frozenset("""
    fee_evidence_unavailable fee_approval_unparseable
    synthetic_account_terms_unavailable
    conditional_fee_evidence_invalid conditional_fee_evidence_path
    conditional_fee_review_expired_or_not_effective conditional_pregame_ended
    conditional_pregame_straight_mapping_unsupported conditional_invalid_odds
    conditional_standard_contract_mapping_unsupported conditional_fee_price_range_unsupported
    conservative_fee_policy_not_effective conservative_trade_fee_estimate_not_applicable
    fee_quote_receipt_future fee_schedule_unavailable fee_applicability_unavailable
    provider_venue_fee_applicability_unestablished public_fee_schedule_review_required
    public_fee_schedule_refresh_pending reviewed_trade_fee_scenario_unavailable
    reference_probability_unavailable source_price_or_selection_unsupported
    supported_decisive_benchmark_required live_market_fee_evidence_unbound fee_game_phase_unverified
    conditional_fee_proof_required fee_mode_unverified offer_fee_evidence_required
    kalshi_public_fee_evidence_unavailable kalshi_series_fee_scope_unbound
    kalshi_native_fee_identity_conflict kalshi_binary_claim_required kalshi_event_fee_history_incomplete
    kalshi_account_membership_unbound kalshi_account_channel_unbound
    kalshi_account_fact_expired_or_not_effective kalshi_account_evidence_changed
    kalshi_non_direct_intermediary_trade_fees_unbound kalshi_positive_quantity_required
    polymarket_standard_retail_review_unavailable polymarket_account_taker_fee_tier_unbound
    polymarket_fee_product_scope_unbound polymarket_selected_order_grid_unbound
    polymarket_documented_price_outside_range
    polymarket_short_acquisition_price_unbound polymarket_one_claim_quantity_unsupported
    polymarket_selected_fee_coefficient_unbound polymarket_selected_price_grid_conflict
    polymarket_exact_reference_or_settlement_missing pair_size_unsupported
    prophetx_account_fee_model_and_rate_unbound prophetx_public_site_straight_mapping_unsupported
    prophetx_nhl_taker_schedule_required prophetx_positive_quantity_required
    prophetx_nhl_fill_quantity_mismatch prophetx_invalid_nhl_taker_coefficient
    prophetx_invalid_nhl_fill prophetx_nhl_fills_required
    public_fee_page_unparseable reviewed_receipt_changed reviewed_receipt_invalid
    reviewed_reference_changed unsupported_public_fee_product
    fee_approval_unavailable fee_retrieval_failed conflicting_approved_rules fee_terms_require_model_review
    fee_http_status fee_response_freshness_unverified fee_response_encoding_unsupported fee_response_size_limit
    fee_index_unparseable conflicting_straight_fee_documents straight_fee_document_missing
    fee_document_unparseable public_straight_schedule_changed prior_change_requires_explicit_review
    public_product_schedule_changed kalshi_renderer_configuration_invalid kalshi_rendered_origin_unverified
    kalshi_rendered_origin_http_status kalshi_rendered_scope_ambiguous kalshi_rendered_schedule_changed
    kalshi_market_terms_approval_mismatch kalshi_market_terms_ambiguous kalshi_market_terms_changed
    kalshi_rounding_terms_changed fee_refresh_interrupted kalshi_renderer_unconfigured
    fee_metadata_http_status fee_metadata_query_failed fee_series_identity_mismatch fee_event_history_incomplete
    fee_series_history_identity_mismatch fee_event_history_identity_mismatch
    live_financial_model_unverified live_kalshi_series_fee_scope_unbound
    estimate_allocation_input_context_conflict
    estimate_authored_flat_entry_fee_required
    estimate_draw_payout_template_unresolved
    estimate_entry_engine_refused
    estimate_fair_price_invalid
    estimate_fill_quantity_conflict
    estimate_funding_double_count
    estimate_immutable_funding_required
    estimate_native_units_unknown
    estimate_novig_fee_regime_conflict
    estimate_positive_quantity_required
    estimate_price_units_conflict
    estimate_reference_units_native_conflict
    estimate_selected_entry_engine_unbound
    estimate_selected_fee_authority_unresolved
    estimate_selected_fee_expired
    estimate_selected_fee_native_conflict
    estimate_selected_fee_not_effective
    estimate_selected_fee_terms_unresolved
    estimate_selected_payout_binding_unresolved
    estimate_short_collateral_unresolved
    estimate_stake_adapter_invalid
    estimate_stake_adapter_level_bound
    estimate_stake_adapter_quantity_conflict
    estimate_stake_adapter_units_conflict
    estimate_stake_entry_terms_adapter_unresolved
    estimate_stake_fill_conversion_unresolved
    estimate_taker_fill_required
    estimate_three_way_payout_unresolved
    estimate_tie_branch_invalid
    estimate_withheld_attachment_required
""".split())


def public_reason(reason, *, fallback=UNAVAILABLE):
    if isinstance(reason, str) and reason == 'PMUS documented price range .01 through .99':
        return 'polymarket_documented_price_outside_range'
    return reason if reason is None or isinstance(reason, str) and reason in REASONS else fallback


def exception_reason(logger, operation, error, *, fallback=UNAVAILABLE):
    value = public_reason(str(error), fallback=fallback)
    if value == fallback:
        failure(logger, operation, error)
    return value


def public_reason_fields(value, *keys):
    if not isinstance(value, dict):
        return value
    changes = {key: public_reason(value[key]) for key in keys if key in value}
    return dict(value, **changes) if any(value[key] != reason for key, reason in changes.items()) else value


def public_fee_result(value):
    """Project a fee result for display without changing its retained source."""
    if not isinstance(value, dict):
        return value
    result = public_reason_fields(value, 'reason')
    evidence = public_reason_fields(result.get('evidence'), 'unavailable_reason')
    return dict(result, evidence=evidence) if evidence is not result.get('evidence') else result
