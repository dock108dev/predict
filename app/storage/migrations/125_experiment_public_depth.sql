CREATE TABLE public.ev_experiment_depth (
    id text PRIMARY KEY CHECK (length(id)=64),
    game_id text NOT NULL REFERENCES public.ev_experiment_game(id),
    schedule_id text NOT NULL REFERENCES public.ev_experiment_record(id),
    target_at timestamptz NOT NULL,
    kind text NOT NULL CHECK (kind IN ('decision','followup')),
    origin_id text REFERENCES public.ev_experiment_depth(id),
    cutoff_at timestamptz NOT NULL,
    known_at timestamptz NOT NULL CHECK (known_at<=cutoff_at),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (known_at<=recorded_at),
    payload_bytes integer NOT NULL CHECK (payload_bytes BETWEEN 1 AND 524288),
    payload jsonb NOT NULL,
    CHECK ((kind='decision' AND cutoff_at=target_at AND origin_id IS NULL) OR
           (kind='followup' AND cutoff_at>target_at AND origin_id IS NOT NULL)),
    UNIQUE(game_id,schedule_id,target_at,kind)
);
CREATE INDEX ev_experiment_depth_followup ON public.ev_experiment_depth(origin_id) WHERE kind='followup';
CREATE TRIGGER ev_experiment_depth_immutable BEFORE UPDATE OR DELETE ON public.ev_experiment_depth
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();
