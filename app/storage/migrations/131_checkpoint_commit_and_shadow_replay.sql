CREATE TABLE public.ev_experiment_checkpoint_commit (
    checkpoint_id text PRIMARY KEY REFERENCES public.ev_experiment_record(id),
    game_id text NOT NULL REFERENCES public.ev_experiment_game(id),
    schedule_id text NOT NULL REFERENCES public.ev_experiment_record(id),
    target_at timestamptz NOT NULL,
    deadline_at timestamptz NOT NULL,
    checkpoint_recorded_at timestamptz NOT NULL,
    pull_id text NOT NULL,
    attempt_id text NOT NULL,
    receipt_sha256 text NOT NULL CHECK (length(receipt_sha256)=64),
    received_at timestamptz NOT NULL,
    commit_observed_at timestamptz NOT NULL,
    CHECK (target_at<=received_at AND received_at<=checkpoint_recorded_at
           AND checkpoint_recorded_at<=deadline_at AND checkpoint_recorded_at<=commit_observed_at)
);
CREATE TRIGGER ev_experiment_checkpoint_commit_immutable BEFORE UPDATE OR DELETE
    ON public.ev_experiment_checkpoint_commit
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();

CREATE TABLE public.research_run_official_shadow (
    run_id text PRIMARY KEY REFERENCES public.research_workspace_run(id),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
    payload_bytes integer NOT NULL CHECK (payload_bytes>0)
);
CREATE TRIGGER research_run_official_shadow_immutable BEFORE UPDATE OR DELETE
    ON public.research_run_official_shadow
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();
