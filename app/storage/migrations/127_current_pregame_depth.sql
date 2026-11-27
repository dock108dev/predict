-- Current public-book evidence is independent of the quote and paper ledgers.
CREATE TABLE public.current_pregame_depth (
    contract_id text PRIMARY KEY REFERENCES public.current_contract_storage(id) ON DELETE CASCADE,
    contract_revision text NOT NULL,
    receipt_id text NOT NULL,
    known_at timestamptz NOT NULL,
    valid_until timestamptz NOT NULL,
    published_at timestamptz NOT NULL,
    receipt jsonb NOT NULL,
    valuations jsonb NOT NULL,
    CHECK (known_at <= published_at AND known_at < valid_until),
    CHECK (jsonb_typeof(receipt) = 'object' AND jsonb_typeof(valuations) = 'object')
);
CREATE INDEX current_pregame_depth_expiry ON public.current_pregame_depth(valid_until);
CREATE INDEX current_pregame_depth_publication ON public.current_pregame_depth(published_at DESC);
