-- Compute immutable contract fingerprints only when contract facts change.
-- Read-time comparisons retain exactly the prior hashing semantics.
ALTER TABLE current_contract ADD COLUMN contract_dependency text;
ALTER TABLE current_contract ADD COLUMN metric_dependency text;
CREATE FUNCTION current_contract_dependencies() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.contract_dependency := encode(sha256(convert_to((NEW.facts #- '{comparison_source_metadata,observed_at}')::text,'UTF8')),'hex');
    NEW.metric_dependency := encode(sha256(convert_to(jsonb_build_array(NEW.facts-'orientation_evidence'-'comparison_source_metadata',
        NEW.facts#>'{comparison_source_metadata,same_outcome}',NEW.facts#>'{comparison_source_metadata,scoring_scope}',
        NEW.facts#>'{comparison_source_metadata,native_market_type}',NEW.facts#>'{comparison_source_metadata,series_id}')::text,'UTF8')),'hex');
    RETURN NEW;
END;
$$;
CREATE TRIGGER current_contract_dependencies BEFORE INSERT OR UPDATE OF facts ON current_contract
    FOR EACH ROW EXECUTE FUNCTION current_contract_dependencies();
UPDATE current_contract SET facts=facts;
ALTER TABLE current_contract ALTER COLUMN contract_dependency SET NOT NULL;
ALTER TABLE current_contract ALTER COLUMN metric_dependency SET NOT NULL;
