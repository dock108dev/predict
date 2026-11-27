CREATE TABLE public.paper_campaign_retirement (
    campaign_id text PRIMARY KEY REFERENCES public.paper_campaign(id),
    cutoff_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (recorded_at <= cutoff_at)
);
CREATE TRIGGER paper_campaign_retirement_immutable BEFORE UPDATE OR DELETE
    ON public.paper_campaign_retirement FOR EACH ROW
    EXECUTE FUNCTION public.research_record_immutable();
