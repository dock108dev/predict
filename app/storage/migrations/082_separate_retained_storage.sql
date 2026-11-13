-- Keep retained records and their foreign keys. Ordinary unqualified SQL
-- resolves only in public. Historical tools explicitly open the archive.
CREATE SCHEMA retained;
SET LOCAL lock_timeout = '5s';
SELECT pg_advisory_xact_lock(903015);
SELECT pg_advisory_xact_lock(903016);

DO $$
DECLARE relation text;
BEGIN
    FOREACH relation IN ARRAY ARRAY[
        'current_calculation_attempt','current_latest_result','current_game_result',
        'current_game_snapshot','current_game_projection','current_source_projection',
        'current_import_cursor','current_envelope','current_domain_head','current_domain_anchor',
        'current_price_latest','current_price_revision','current_price_game','current_price_game_fact',
        'latest_board','latest_board_status','latest_dashboard','current_grid_projection',
        'current_result_unit','current_result_parent_original','current_result_inventory',
        'current_result_work','current_grid_blob','current_grid_read_lease',
        'current_pipeline_attempt','pipeline_generation',
        'artifact','artifact_edge','calculation','calculation_receipt','candidate_observation',
        'capture_session','coverage_event','metadata_version','quote_observation','receipt',
        'reference_source_revision','reference_receipt','reference_quote_revision','reference_gap',
        'fair_price','fair_price_input','opportunity_dependency','opportunity_audit','opportunity_input'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I SET SCHEMA retained', relation);
    END LOOP;
END
$$;
