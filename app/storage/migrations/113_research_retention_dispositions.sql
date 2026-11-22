-- Bounded mutable retention telemetry; source/research evidence stays immutable.
-- One slot per declared case/horizon, reserved before any capture can be refused.
CREATE TABLE public.research_retention_disposition (
    cohort_id text NOT NULL REFERENCES public.research_record(id),
    case_key text NOT NULL CHECK(octet_length(case_key)<=256),
    slot text NOT NULL,
    observation_refusals bigint NOT NULL DEFAULT 0 CHECK(observation_refusals>=0),
    capture_refusals bigint NOT NULL DEFAULT 0 CHECK(capture_refusals>=0),
    observation_first_refused_at timestamptz,
    observation_last_refused_at timestamptz,
    capture_first_refused_at timestamptz,
    capture_last_refused_at timestamptz,
    observation_recovered_at timestamptz,
    capture_recovered_at timestamptz,
    last_reason text CHECK(octet_length(last_reason)<=160),
    last_input_fingerprint text CHECK(octet_length(last_input_fingerprint)<=64),
    last_attempted_bytes integer CHECK(last_attempted_bytes>=0),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(cohort_id,case_key,slot)
) WITH(fillfactor=80,autovacuum_vacuum_scale_factor=0.02,autovacuum_vacuum_threshold=50);
INSERT INTO public.research_retention_disposition(cohort_id,case_key,slot)
SELECT r.id,c->>'case_key',h#>>'{}' FROM public.research_record r
CROSS JOIN LATERAL jsonb_array_elements(r.payload->'population') c
CROSS JOIN LATERAL jsonb_array_elements(r.payload->'horizons') h
WHERE r.kind='cohort';
CREATE TABLE public.research_retention_accounting (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
    installed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    coverage_started_at timestamptz,
    prior_first_observed_refusal_at timestamptz,
    prior_evidence_reference text CHECK(octet_length(prior_evidence_reference)<=1024),
    prior_refused_attempts bigint,
    prior_affected_cases bigint,
    declaration_refusals bigint NOT NULL DEFAULT 0 CHECK(declaration_refusals>=0),
    last_declaration_refused_at timestamptz,
    last_declaration_reason text CHECK(octet_length(last_declaration_reason)<=160),
    last_declaration_population integer
);
INSERT INTO public.research_retention_accounting(singleton) VALUES(true);
