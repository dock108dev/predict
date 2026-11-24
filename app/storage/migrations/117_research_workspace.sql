-- Versioned research interpretations and paper runs reference retained capture evidence.
CREATE TABLE public.research_workspace_catalog (
    version text PRIMARY KEY,
    id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('theory', 'claim')),
    supersedes text REFERENCES public.research_workspace_catalog(version),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    payload_bytes integer NOT NULL CHECK (payload_bytes > 0),
    payload jsonb NOT NULL
);
CREATE TABLE public.research_workspace_definition (
    version text PRIMARY KEY,
    id text NOT NULL,
    supersedes text REFERENCES public.research_workspace_definition(version),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    payload_bytes integer NOT NULL CHECK (payload_bytes > 0),
    payload jsonb NOT NULL
);
CREATE TABLE public.research_workspace_run (
    id text PRIMARY KEY,
    definition_version text NOT NULL REFERENCES public.research_workspace_definition(version),
    game_date date NOT NULL,
    report_revision text NOT NULL,
    observed_at timestamptz NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    supersedes text REFERENCES public.research_workspace_run(id),
    summary jsonb NOT NULL,
    payload_bytes integer NOT NULL CHECK (payload_bytes > 0),
    payload jsonb NOT NULL,
    UNIQUE (definition_version, game_date, report_revision)
);
CREATE INDEX research_workspace_run_date
    ON public.research_workspace_run (definition_version, game_date, observed_at DESC);
CREATE TABLE public.research_workspace_finding (
    version text PRIMARY KEY,
    id text NOT NULL,
    run_id text NOT NULL REFERENCES public.research_workspace_run(id),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    payload_bytes integer NOT NULL CHECK (payload_bytes > 0),
    payload jsonb NOT NULL
);
CREATE INDEX research_workspace_finding_run ON public.research_workspace_finding (run_id);
CREATE TRIGGER research_workspace_catalog_immutable BEFORE UPDATE OR DELETE ON public.research_workspace_catalog
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();
CREATE TRIGGER research_workspace_definition_immutable BEFORE UPDATE OR DELETE ON public.research_workspace_definition
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();
CREATE TRIGGER research_workspace_run_immutable BEFORE UPDATE OR DELETE ON public.research_workspace_run
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();
CREATE TRIGGER research_workspace_finding_immutable BEFORE UPDATE OR DELETE ON public.research_workspace_finding
    FOR EACH ROW EXECUTE FUNCTION public.research_record_immutable();

-- Registrations use the actual migration clock. The pilot date is the Eastern game date.
INSERT INTO public.research_workspace_catalog(version,id,kind,payload_bytes,payload)
SELECT version,id,kind,octet_length(payload::text),payload FROM (VALUES
  ('t10-positive-ev-v1', 't10-positive-ev', 'theory', $seed$ {
    "title": "T−10 positive EV strategy",
    "statement": "Selecting college basketball opportunities with recorded EV ≥4%, under the defined sizing and venue-selection policy, produces positive net returns over repeated use.",
    "scope": "College basketball full-game offers meeting the versioned T−10 capture and paper selection policies.",
    "status": "open",
    "claim_ids": ["net-ev-law", "t10-selection", "fee-sizing", "evidence-quality", "positive-net-returns"],
    "risk_objectives": [{
      "statement": "≤1% modeled probability of a losing 12-month period",
      "threshold": "1/100", "estimate": null, "status": "not_established",
      "missing_assumptions": ["Finite starting capital and funding policy", "Seasonal opportunity frequency and turnover", "Allocation under overlapping exposure and bankroll constraints", "Dependence within games, venues and days", "Out-of-sample probability calibration and return distribution", "Achievable size, fills, fees and settlement"]
    }]
  }$seed$::jsonb),
  ('net-ev-law-v1', 'net-ev-law', 'claim', $seed$ {
    "title": "Net expected value from state cashflows",
    "statement": "For exhaustive cashflow states, net EV equals the probability-weighted net profit divided by committed capital.",
    "type": "mathematical_validity", "scope": "An exact, explicitly specified probability and cashflow model.",
    "status": "conditional_identity", "assumptions": ["Exhaustive mutually exclusive states", "Positive committed capital", "Probabilities sum to one", "Receipts reflect the stated fee assumptions"],
    "dependencies": [], "supporting_evidence": [{"label": "Definition of expectation applied to net cashflow and normalized by committed capital"}],
    "contrary_evidence": [], "challenge": "A counterexample satisfying the assumptions would challenge the derivation. Incomplete cashflow states or invalid probabilities challenge applicability."
  }$seed$::jsonb),
  ('t10-selection-v1', 't10-selection', 'claim', $seed$ {
    "title": "The T−10 screen uses the frozen population",
    "statement": "Eligible recorded tickets use valid frozen T−10 evidence, the exact threshold and stable ticket identities across both venue variants.",
    "type": "implementation_verification", "scope": "The retrospective paper replay and its frozen definition.",
    "status": "under_examination", "assumptions": ["Eligible checkpoint meets the recorded causal clocks", "Exact offer and venue identities are retained"],
    "dependencies": ["net-ev-law"], "supporting_evidence": [], "contrary_evidence": [],
    "challenge": "A ticket using an early, stale, superseded or out-of-window receipt, a below-threshold exact EV, or a duplicate identity."
  }$seed$::jsonb),
  ('fee-sizing-v1', 'fee-sizing', 'claim', $seed$ {
    "title": "Kelly sizing uses modeled fees at the ticket amount",
    "statement": "The configured Kelly fraction and sizing reference reprice the captured fee and cashflows at the modeled amount.",
    "type": "implementation_verification", "scope": "Supported binary paper offers with frozen fee inputs.",
    "status": "under_examination", "assumptions": ["Frozen fee terms apply to the paper model", "Captured price is available at the modeled amount in the paper model"],
    "dependencies": ["net-ev-law"], "supporting_evidence": [], "contrary_evidence": [],
    "challenge": "A sized witness fails independent arithmetic, fee repricing, quantity grids or the final exact EV cutoff."
  }$seed$::jsonb),
  ('evidence-quality-v1', 'evidence-quality', 'claim', $seed$ {
    "title": "Capture coverage and result linkage are auditable",
    "statement": "Missing captures remain visible and modeled sporting grades point to retained result evidence.",
    "type": "implementation_verification", "scope": "Tracked games and retained source checkpoints and sporting results.",
    "status": "under_examination", "assumptions": ["Unknown games stay distinct from known missing captures", "A sporting result matches the captured schedule and market"],
    "dependencies": ["t10-selection"], "supporting_evidence": [], "contrary_evidence": [],
    "challenge": "A capture failure appears complete, a grade cannot be traced to its score, or a sporting result is presented as venue settlement."
  }$seed$::jsonb),
  ('positive-net-returns-v1', 'positive-net-returns', 'claim', $seed$ {
    "title": "Positive net returns over repeated use",
    "statement": "Selection and sizing produce positive net returns across a representative repeated population after applicable costs.",
    "type": "empirical_support", "scope": "Repeated use on a representative college basketball population.",
    "status": "open", "assumptions": ["Stable applicable fees and execution assumptions", "Representative out-of-sample evidence", "Dependent tickets are modeled together"],
    "dependencies": ["net-ev-law", "t10-selection", "fee-sizing", "evidence-quality"],
    "supporting_evidence": [], "contrary_evidence": [],
    "challenge": "Representative prospectively declared evidence of nonpositive net return, or model and execution gaps that invalidate estimated net return."
  }$seed$::jsonb)
) AS seed(version,id,kind,payload);

INSERT INTO public.research_workspace_definition(version,id,payload_bytes,payload)
SELECT 'ncaab-t10-paper-v1','ncaab-t10-paper',octet_length(payload::text),payload
FROM (VALUES ($seed$ {
    "title": "College basketball T−10 pipeline pilot",
    "question": "Can retained T−10 captures be screened, sized, recorded and traced to coverage, exposure, and modeled sporting outcomes in both venue variants?",
    "claim_ids": ["net-ev-law", "t10-selection", "fee-sizing", "evidence-quality", "positive-net-returns"],
    "claim_versions": ["net-ev-law-v1", "t10-selection-v1", "fee-sizing-v1", "evidence-quality-v1", "positive-net-returns-v1"],
    "designation": "retrospective_replay",
    "registration": "Registered when this workflow is installed. The pilot retrospectively examines the November 23, 2026 Eastern game population.",
    "assumptions": ["Fixed sizing reference with no aggregate cap or intraday compounding", "Modeled size at captured prices without execution or depth verification", "Captured fee terms repriced at the modeled amount", "Decisive sporting results model cashflows and keep venue settlement unverified"],
    "evaluation_criteria": ["Account for tracked, captured, missing and unknown games", "Screen and reprice each eligible offer with the recorded exact EV and Kelly policies", "Trace both alternative venue variants to shared observations and exact result evidence", "Show unresolved exposure separately and compare expected profit and modeled P/L for the same resolved tickets", "Evaluate the pipeline only; repeated profitability and the 12-month loss probability remain unexamined"],
    "policy": {
      "version": "paper-tminus10-quarter-kelly-4pct-1", "league": "NCAAB",
      "default_date": "2026-11-23", "timezone": "America/New_York",
      "minimum_ev": "1/25", "reference_bankroll_usd": "10000", "kelly_multiplier": "1/4",
      "sizing_scale_usd": "2500", "baseline": "-110 at 4% EV commits $110 before extra fees",
      "checkpoint": "late", "target_seconds_before_start": 600, "tolerance_seconds": 60,
      "portfolios": ["best_venue", "all_venues"], "intraday_compounding": false, "budget_cap": null,
      "execution": "paper_only; unlimited size at captured posted price; no depth proof",
      "selection": "unrounded captured screening EV >= 4%; recheck at sized cash commitment",
      "fees": "preserve each capture's actual fee mode; never silently enable or disable fees",
      "duplicates": "one ticket per exact bet per venue; best_venue removes venue identity only",
      "settlement": "decisive sporting results model win/loss; pushes, voids and unverified changes unresolved"
    }
  }$seed$::jsonb)) AS seed(payload);
