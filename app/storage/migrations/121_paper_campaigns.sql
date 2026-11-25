-- Scheduled paper experiments retain immutable configuration and dated run pointers.
CREATE TABLE public.paper_campaign (
    id text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    payload jsonb NOT NULL,
    payload_bytes integer NOT NULL CHECK (payload_bytes > 0)
);
CREATE TRIGGER paper_campaign_immutable BEFORE UPDATE OR DELETE ON public.paper_campaign
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();
CREATE TABLE public.paper_campaign_day (
    campaign_id text NOT NULL REFERENCES public.paper_campaign(id),
    game_date date NOT NULL,
    next_check_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_until timestamptz,
    run_id text REFERENCES public.research_workspace_run(id),
    fingerprint text,
    state text NOT NULL DEFAULT 'scheduled',
    last_error text,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (campaign_id, game_date)
);
CREATE INDEX paper_campaign_day_due ON public.paper_campaign_day(next_check_at, game_date);
