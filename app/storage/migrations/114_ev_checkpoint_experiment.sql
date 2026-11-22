-- Two-checkpoint experiment evidence is append-only; scheduling telemetry is bounded.
CREATE TABLE public.ev_experiment_record (
    id text PRIMARY KEY,
    kind text NOT NULL CHECK(kind IN ('policy','schedule','checkpoint','comparison','outcome','attempt','blob')),
    game_id text,
    checkpoint text,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    payload_bytes integer NOT NULL CHECK(payload_bytes>0),
    refs text[] NOT NULL DEFAULT '{}',
    payload jsonb NOT NULL
);
CREATE INDEX ev_experiment_records_game ON public.ev_experiment_record(game_id,kind,recorded_at,id);
CREATE TRIGGER ev_experiment_record_immutable BEFORE UPDATE OR DELETE ON public.ev_experiment_record
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();
CREATE TABLE public.ev_experiment_accounting (
    singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
    policy_id text REFERENCES public.ev_experiment_record(id),
    activated_at timestamptz,
    discovery_refusals bigint NOT NULL DEFAULT 0,
    last_refused_at timestamptz,
    last_reason text CHECK(octet_length(last_reason)<=160),
    last_source_event_id text CHECK(octet_length(last_source_event_id)<=256)
);
INSERT INTO public.ev_experiment_accounting(singleton) VALUES(true);
CREATE TABLE public.ev_experiment_game (
    id text PRIMARY KEY,
    policy_id text NOT NULL REFERENCES public.ev_experiment_record(id),
    provider text NOT NULL,
    source_event_id text NOT NULL,
    event jsonb NOT NULL,
    discovered_at timestamptz NOT NULL,
    first_observed_at timestamptz NOT NULL,
    schedule_id text NOT NULL REFERENCES public.ev_experiment_record(id),
    early_id text REFERENCES public.ev_experiment_record(id),
    late_id text REFERENCES public.ev_experiment_record(id),
    outcome_id text REFERENCES public.ev_experiment_record(id),
    comparison_id text REFERENCES public.ev_experiment_record(id),
    retained_cases integer NOT NULL DEFAULT 0,
    unique_payload_bytes bigint NOT NULL DEFAULT 0,
    raw_checkpoint_bytes bigint NOT NULL DEFAULT 0,
    late_reserved_bytes bigint NOT NULL DEFAULT 0,
    state text NOT NULL DEFAULT 'tracking',
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(provider,source_event_id)
) WITH(fillfactor=80,autovacuum_vacuum_scale_factor=0.02,autovacuum_vacuum_threshold=50);
CREATE TABLE public.ev_experiment_task (
    game_id text NOT NULL REFERENCES public.ev_experiment_game(id),
    checkpoint text NOT NULL CHECK(checkpoint IN ('early','late','outcome')),
    schedule_id text NOT NULL REFERENCES public.ev_experiment_record(id),
    state text NOT NULL DEFAULT 'pending',
    target_at timestamptz NOT NULL,
    deadline_at timestamptz NOT NULL,
    token text,
    claimed_at timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    slot_index integer NOT NULL DEFAULT 0,
    skipped_windows integer NOT NULL DEFAULT 0,
    refusals bigint NOT NULL DEFAULT 0,
    first_refused_at timestamptz,
    last_refused_at timestamptz,
    last_reason text CHECK(octet_length(last_reason)<=160),
    attempted_bytes integer,
    result_id text REFERENCES public.ev_experiment_record(id),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY(game_id,checkpoint)
) WITH(fillfactor=80,autovacuum_vacuum_scale_factor=0.02,autovacuum_vacuum_threshold=50);
CREATE INDEX ev_experiment_task_due ON public.ev_experiment_task(state,target_at,checkpoint);
