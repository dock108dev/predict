CREATE TABLE public.ev_experiment_depth_shadow (
    id text PRIMARY KEY CHECK (length(id)=64),
    original_id text NOT NULL UNIQUE REFERENCES public.ev_experiment_depth(id),
    checkpoint_id text REFERENCES public.ev_experiment_record(id),
    game_id text NOT NULL REFERENCES public.ev_experiment_game(id),
    schedule_id text NOT NULL REFERENCES public.ev_experiment_record(id),
    target_at timestamptz NOT NULL,
    known_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp() CHECK (known_at<=recorded_at),
    payload_bytes integer NOT NULL CHECK (payload_bytes BETWEEN 1 AND 8388608),
    reason text,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload)='object'),
    CHECK (known_at<=target_at OR reason IS NOT NULL)
);
CREATE TRIGGER ev_experiment_depth_shadow_immutable BEFORE UPDATE OR DELETE ON public.ev_experiment_depth_shadow
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();
