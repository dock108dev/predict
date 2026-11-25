-- Decisions annotate retained research evidence and preserve each prior review.
CREATE TABLE public.research_issue_disposition (
    sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{64}$'),
    game_date date NOT NULL,
    issue_id text NOT NULL CHECK (issue_id ~ '^[0-9a-f]{64}$'),
    evidence_revision text NOT NULL CHECK (evidence_revision ~ '^[0-9a-f]{64}$'),
    supersedes text REFERENCES public.research_issue_disposition(id),
    status text NOT NULL CHECK (status IN ('open', 'resolved_by_evidence', 'accepted_historical_gap',
        'accepted_source_limitation', 'excluded_by_scope', 'assigned_another_date')),
    reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 1000),
    actor text NOT NULL CHECK (length(actor) BETWEEN 1 AND 120),
    decided_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    evidence jsonb NOT NULL,
    issue jsonb NOT NULL
);
CREATE INDEX research_issue_disposition_day ON public.research_issue_disposition (game_date, sequence);
CREATE TRIGGER research_issue_disposition_immutable BEFORE UPDATE OR DELETE ON public.research_issue_disposition
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();
