-- Saved selections and derived sporting reports have independent lifecycles.
CREATE TABLE public.paper_result_report (
    id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES public.research_workspace_run(id),
    grading_rule text NOT NULL,
    evidence_revision text NOT NULL,
    supersedes text,
    observed_at timestamptz,
    processed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    status text NOT NULL,
    payload_bytes integer NOT NULL CHECK (payload_bytes > 0),
    payload jsonb NOT NULL,
    UNIQUE (run_id, id),
    UNIQUE (run_id, grading_rule, evidence_revision),
    FOREIGN KEY (run_id, supersedes) REFERENCES public.paper_result_report(run_id, id)
);
CREATE INDEX paper_result_report_history ON public.paper_result_report(run_id, processed_at DESC, id);
CREATE TRIGGER paper_result_report_immutable BEFORE UPDATE OR DELETE ON public.paper_result_report
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();

CREATE TABLE public.paper_result_job (
    run_id text PRIMARY KEY REFERENCES public.research_workspace_run(id),
    league text,
    game_date date NOT NULL,
    generation bigint NOT NULL DEFAULT 1,
    processed_generation bigint NOT NULL DEFAULT 0,
    current_result_id text,
    applied_rule text,
    due_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    lease_token text,
    lease_until timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    FOREIGN KEY (run_id, current_result_id) REFERENCES public.paper_result_report(run_id, id)
);
CREATE INDEX paper_result_job_date ON public.paper_result_job(league, game_date);
CREATE INDEX paper_result_job_due ON public.paper_result_job(due_at, run_id)
    WHERE generation > processed_generation;

CREATE TABLE public.paper_result_dependency (
    run_id text NOT NULL REFERENCES public.paper_result_job(run_id),
    dependency text NOT NULL,
    PRIMARY KEY (run_id, dependency)
);
CREATE INDEX paper_result_dependency_lookup ON public.paper_result_dependency(dependency, run_id);

-- Retention transactions insert one small event and never update or lock a job.
-- Dispatch and its fan-out commit together, independently of source ingestion.
CREATE TABLE public.paper_result_input (
    id text PRIMARY KEY,
    game_date date,
    game_key text,
    provider_key text,
    retained_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    dispatched_at timestamptz,
    CHECK (game_date IS NOT NULL OR game_key IS NOT NULL OR provider_key IS NOT NULL)
);
CREATE INDEX paper_result_input_ready ON public.paper_result_input(retained_at, id)
    WHERE dispatched_at IS NULL;
CREATE INDEX paper_result_input_pending_date ON public.paper_result_input(game_date)
    WHERE dispatched_at IS NULL AND game_date IS NOT NULL;
CREATE INDEX paper_result_input_pending_game ON public.paper_result_input(game_key)
    WHERE dispatched_at IS NULL AND game_key IS NOT NULL;
CREATE INDEX paper_result_input_pending_provider ON public.paper_result_input(provider_key)
    WHERE dispatched_at IS NULL AND provider_key IS NOT NULL;

CREATE FUNCTION public.paper_result_is_run(document jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT COALESCE(jsonb_typeof(document#>'{report,portfolios}') = 'object'
        AND left(document#>>'{report,policy,execution}', 10) = 'paper_only'
        AND jsonb_typeof(document#>'{report,games}') = 'array'
        AND jsonb_typeof(document#>'{report,portfolios,best_venue,tickets}') = 'array'
        AND jsonb_typeof(document#>'{report,portfolios,all_venues,tickets}') = 'array', false)
$$;

CREATE FUNCTION public.paper_result_register(key text, day date, document jsonb) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.paper_result_job(run_id, league, game_date)
    VALUES (key, document#>>'{report,policy,league}', day)
    ON CONFLICT DO NOTHING;
    INSERT INTO public.paper_result_dependency(run_id, dependency)
    SELECT key, 'game:' || (game->>'game_id')
    FROM jsonb_array_elements(document#>'{report,games}') game
    WHERE game->>'game_id' IS NOT NULL
    UNION
    SELECT key, 'provider:' || tracked.provider || ':' || tracked.source_event_id
    FROM jsonb_array_elements(document#>'{report,games}') game
    JOIN public.ev_experiment_game tracked ON tracked.id = game->>'game_id'
    UNION
    SELECT key, 'provider:sportsgameodds:' || (game->>'provider_event_id')
    FROM jsonb_array_elements(document#>'{report,population,games}') game
    WHERE game->>'provider_event_id' IS NOT NULL
    ON CONFLICT DO NOTHING;
END;
$$;

CREATE FUNCTION public.paper_result_saved_run() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM public.paper_result_register(NEW.id, NEW.game_date, NEW.payload);
    RETURN NULL;
END;
$$;
CREATE TRIGGER paper_result_saved_run AFTER INSERT ON public.research_workspace_run
    FOR EACH ROW WHEN (public.paper_result_is_run(NEW.payload))
    EXECUTE FUNCTION public.paper_result_saved_run();

CREATE FUNCTION public.paper_result_daily_input() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.paper_result_input(id, game_date) VALUES ('daily:' || NEW.id, NEW.game_date)
    ON CONFLICT DO NOTHING;
    RETURN NULL;
END;
$$;
CREATE TRIGGER paper_result_daily_input AFTER INSERT ON public.mens_d1_revision
    FOR EACH ROW EXECUTE FUNCTION public.paper_result_daily_input();

CREATE FUNCTION public.paper_result_official_input() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.paper_result_input(id, game_date)
    SELECT 'official:' || NEW.id, revision.game_date FROM public.mens_d1_revision revision
    WHERE revision.id = NEW.schedule_revision_id ON CONFLICT DO NOTHING;
    RETURN NULL;
END;
$$;
CREATE TRIGGER paper_result_official_input AFTER INSERT ON public.mens_d1_binding
    FOR EACH ROW WHEN (NEW.facts->>'kind' = 'official-game-corroboration-1')
    EXECUTE FUNCTION public.paper_result_official_input();

CREATE FUNCTION public.paper_result_game_input() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.paper_result_input(id, game_date, game_key, provider_key)
    VALUES ('game:' || NEW.id || ':' || NEW.schedule_id || ':' || COALESCE(NEW.outcome_id, '-'),
            CASE WHEN NEW.event->>'league' = 'NCAAB'
                 THEN ((NEW.event->>'starts_at')::timestamptz AT TIME ZONE 'America/New_York')::date END,
            'game:' || NEW.id,
            'provider:' || NEW.provider || ':' || NEW.source_event_id)
    ON CONFLICT DO NOTHING;
    RETURN NULL;
END;
$$;
CREATE TRIGGER paper_result_game_input AFTER UPDATE OF outcome_id, schedule_id ON public.ev_experiment_game
    FOR EACH ROW WHEN (
        NEW.outcome_id IS DISTINCT FROM OLD.outcome_id
        OR NEW.schedule_id IS DISTINCT FROM OLD.schedule_id
    ) EXECUTE FUNCTION public.paper_result_game_input();

CREATE FUNCTION public.paper_result_sgo_event(document jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT CASE WHEN COALESCE(document#>>'{data,source_result,source}',
                               document#>>'{source_result,source}') = 'sportsgameodds'
                THEN COALESCE(document#>>'{data,source_result,event_id}',
                              document#>>'{source_result,event_id}') END
$$;
CREATE INDEX paper_result_legacy_sgo_lookup ON public.research_record
    (public.paper_result_sgo_event(payload), recorded_at DESC)
    WHERE kind = 'sporting' AND public.paper_result_sgo_event(payload) IS NOT NULL;

CREATE FUNCTION public.paper_result_legacy_input() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.paper_result_input(id, provider_key)
    VALUES ('legacy:' || NEW.id, 'provider:sportsgameodds:' || public.paper_result_sgo_event(NEW.payload))
    ON CONFLICT DO NOTHING;
    RETURN NULL;
END;
$$;
CREATE TRIGGER paper_result_legacy_input AFTER INSERT ON public.research_record
    FOR EACH ROW WHEN (NEW.kind = 'sporting' AND public.paper_result_sgo_event(NEW.payload) IS NOT NULL)
    EXECUTE FUNCTION public.paper_result_legacy_input();
