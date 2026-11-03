-- Exact candidate fields, maintained with the full contract fingerprints.
ALTER TABLE current_contract ADD COLUMN candidate_projection jsonb;
CREATE OR REPLACE FUNCTION current_contract_dependencies() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.contract_dependency := encode(sha256(convert_to((NEW.facts #- '{comparison_source_metadata,observed_at}')::text,'UTF8')),'hex');
    NEW.metric_dependency := encode(sha256(convert_to(jsonb_build_array(NEW.facts-'orientation_evidence'-'comparison_source_metadata',
        NEW.facts#>'{comparison_source_metadata,same_outcome}',NEW.facts#>'{comparison_source_metadata,scoring_scope}',
        NEW.facts#>'{comparison_source_metadata,native_market_type}',NEW.facts#>'{comparison_source_metadata,series_id}')::text,'UTF8')),'hex');
    NEW.candidate_projection := jsonb_build_object('selection',NEW.facts->'selection',
          'market_identity',NEW.facts->'market_identity','comparison_scope',COALESCE(NEW.facts->'comparison_scope','{}'::jsonb),
          'comparison_source_metadata',jsonb_build_object(
            'same_outcome',COALESCE(NEW.facts#>'{comparison_source_metadata,same_outcome}','{}'::jsonb),
            'scoring_scope',COALESCE(NEW.facts#>'{comparison_source_metadata,scoring_scope}','{}'::jsonb),
            'native_market_type',NEW.facts#>'{comparison_source_metadata,native_market_type}',
            'series_id',NEW.facts#>'{comparison_source_metadata,series_id}'));
    RETURN NEW;
END;
$$;
UPDATE current_contract SET facts=facts;
ALTER TABLE current_contract ALTER COLUMN candidate_projection SET NOT NULL;
