-- Source admission owns these exact witnesses. Cohort publication deletes its
-- work in the same transaction as the derived projection.
CREATE TABLE public.pregame_cohort_work (
    id text PRIMARY KEY,
    observed_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    received_at text NOT NULL,
    receipt_sha256 text NOT NULL,
    collection_run jsonb NOT NULL,
    event_ids text[] NOT NULL,
    witnesses jsonb NOT NULL,
    snapshot jsonb,
    retry_after timestamptz,
    last_error text
);
CREATE INDEX pregame_cohort_work_order ON public.pregame_cohort_work (retry_after NULLS FIRST,observed_at,id);
