-- Logical acquisition identities and immutable terminal game/market snapshots.
CREATE TABLE public.market_pull (
    pull_id text PRIMARY KEY,
    started_order bigserial UNIQUE NOT NULL,
    requested_at timestamptz NOT NULL,
    request_scope jsonb NOT NULL,
    state text NOT NULL CHECK(state IN ('in_progress','complete','partial','failed','cancelled','refused')),
    details jsonb NOT NULL DEFAULT '{}',
    allocation_bytes bigint GENERATED ALWAYS AS
        (octet_length(request_scope::text)+octet_length(details::text)+256) STORED
);
CREATE TABLE public.market_pull_receipt (
    pull_id text NOT NULL REFERENCES public.market_pull(pull_id),
    attempt_id text NOT NULL,
    receipt_sha256 text NOT NULL,
    received_at timestamptz NOT NULL,
    membership jsonb NOT NULL,
    allocation_bytes bigint GENERATED ALWAYS AS (octet_length(membership::text)+256) STORED,
    PRIMARY KEY(pull_id,attempt_id)
);
CREATE TABLE public.market_pull_scope (
    pull_id text NOT NULL REFERENCES public.market_pull(pull_id),
    event_id text NOT NULL,
    family text NOT NULL CHECK(family IN ('moneyline','spread','total')),
    period text NOT NULL DEFAULT 'full_game',
    coverage jsonb NOT NULL,
    state text NOT NULL CHECK(state IN ('in_progress','complete','partial','failed','cancelled','refused')),
    snapshot jsonb,
    allocation_bytes bigint GENERATED ALWAYS AS
        (octet_length(coverage::text)+COALESCE(octet_length(snapshot::text),0)+256) STORED,
    PRIMARY KEY(pull_id,event_id,family,period)
);
CREATE INDEX market_pull_scope_event ON public.market_pull_scope(event_id,family,period);
CREATE TABLE public.market_pull_evidence (
    pull_id text PRIMARY KEY REFERENCES public.market_pull(pull_id),
    body bytea NOT NULL,
    sha256 text NOT NULL,
    raw_bytes integer NOT NULL CHECK(raw_bytes>0),
    allocation_bytes bigint GENERATED ALWAYS AS (octet_length(body)+256) STORED
);
CREATE TRIGGER market_pull_evidence_immutable BEFORE UPDATE OR DELETE ON public.market_pull_evidence
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();
CREATE FUNCTION public.market_snapshot_terminal() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.state <> 'in_progress' AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'terminal acquisition snapshots are immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER market_pull_scope_terminal BEFORE UPDATE ON public.market_pull_scope
    FOR EACH ROW EXECUTE FUNCTION public.market_snapshot_terminal();
CREATE TRIGGER market_pull_receipt_immutable BEFORE UPDATE OR DELETE ON public.market_pull_receipt
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();
