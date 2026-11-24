-- Daily Sporting Reference acquisition is isolated from odds authority.
CREATE TABLE public.mens_d1_source_state (
    source text PRIMARY KEY,
    state text NOT NULL,
    reason text,
    checked_at timestamptz NOT NULL,
    budget jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE public.mens_d1_job (
    source text NOT NULL,
    game_date date NOT NULL,
    purpose text NOT NULL,
    kind text NOT NULL CHECK(kind IN ('schedule','results','detail')),
    due_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL CHECK(expires_at > due_at),
    next_attempt_at timestamptz NOT NULL,
    state text NOT NULL DEFAULT 'pending'
        CHECK(state IN ('pending','running','succeeded','failed','expired','coalesced')),
    attempts integer NOT NULL DEFAULT 0,
    last_attempt_at timestamptz,
    last_success_at timestamptz,
    last_reason text,
    input jsonb NOT NULL DEFAULT '{}',
    PRIMARY KEY(source, game_date, purpose)
);
CREATE INDEX mens_d1_job_due ON public.mens_d1_job(source, next_attempt_at)
    WHERE state IN ('pending','running');

CREATE TABLE public.mens_d1_attempt (
    id text PRIMARY KEY,
    source text NOT NULL,
    game_date date NOT NULL,
    purpose text NOT NULL,
    request_url text NOT NULL,
    request_reason text NOT NULL,
    account_window text NOT NULL,
    admitted_at timestamptz NOT NULL,
    reserved_credits integer NOT NULL CHECK(reserved_credits>0),
    reserved_storage_bytes integer NOT NULL CHECK(reserved_storage_bytes>=0),
    settled_at timestamptz,
    disposition text NOT NULL DEFAULT 'reserved'
        CHECK(disposition IN ('reserved','dispatched','not_dispatched','unknown')),
    charged_credits integer CHECK(charged_credits>=0),
    error text,
    FOREIGN KEY(source,game_date,purpose) REFERENCES public.mens_d1_job(source,game_date,purpose)
);
CREATE INDEX mens_d1_attempt_window ON public.mens_d1_attempt(source,account_window,admitted_at);
CREATE INDEX mens_d1_attempt_storage_reserved ON public.mens_d1_attempt(id)
    WHERE reserved_storage_bytes>0;

CREATE TABLE public.mens_d1_receipt (
    id text PRIMARY KEY,
    attempt_id text NOT NULL UNIQUE REFERENCES public.mens_d1_attempt(id),
    observed_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    body_sha256 text NOT NULL,
    body bytea NOT NULL,
    metadata jsonb NOT NULL
);
CREATE TRIGGER mens_d1_receipt_immutable BEFORE UPDATE OR DELETE ON public.mens_d1_receipt
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();

CREATE TABLE public.mens_d1_revision (
    id text PRIMARY KEY,
    immutable_sequence bigserial UNIQUE NOT NULL,
    source text NOT NULL,
    game_date date NOT NULL,
    kind text NOT NULL CHECK(kind IN ('schedule','results','detail')),
    revision text NOT NULL,
    receipt_id text NOT NULL UNIQUE REFERENCES public.mens_d1_receipt(id),
    observed_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    parser_version text NOT NULL,
    membership_version text,
    facts jsonb NOT NULL
);
CREATE INDEX mens_d1_revision_date ON public.mens_d1_revision(source,game_date,kind,observed_at DESC,immutable_sequence DESC);
CREATE TRIGGER mens_d1_revision_immutable BEFORE UPDATE OR DELETE ON public.mens_d1_revision
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();

CREATE TABLE public.mens_d1_binding (
    id text PRIMARY KEY,
    schedule_revision_id text NOT NULL REFERENCES public.mens_d1_revision(id),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    facts jsonb NOT NULL
);
CREATE INDEX mens_d1_binding_schedule ON public.mens_d1_binding(schedule_revision_id,recorded_at DESC);
CREATE TRIGGER mens_d1_binding_immutable BEFORE UPDATE OR DELETE ON public.mens_d1_binding
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();
