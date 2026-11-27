-- Native inventory and current books do not rewrite acquired SGO evidence or
-- frozen paper results. Saved native evidence is immutable by revision.
CREATE TABLE public.native_trading_sgo_game (
    sgo_event_id text PRIMARY KEY,
    canonical_game_id text NOT NULL UNIQUE
);
CREATE TABLE public.native_trading_snapshot (
    id text PRIMARY KEY,
    offer_id text NOT NULL,
    created_at timestamptz NOT NULL,
    payload_bytes integer NOT NULL CHECK (payload_bytes > 0),
    payload jsonb NOT NULL,
    CHECK (jsonb_typeof(payload) = 'object')
);
CREATE TABLE public.native_trading_offer (
    id text PRIMARY KEY,
    venue text NOT NULL CHECK (venue IN ('novig','kalshi','polymarket_us','prophetx')),
    native_event_id text NOT NULL,
    native_market_id text NOT NULL,
    native_outcome_id text NOT NULL,
    canonical_game_id text NOT NULL,
    league text NOT NULL,
    family text NOT NULL,
    line_role text NOT NULL,
    starts_at timestamptz NOT NULL,
    discovered_at timestamptz NOT NULL,
    published_at timestamptz NOT NULL,
    snapshot_id text NOT NULL REFERENCES public.native_trading_snapshot(id),
    book jsonb NOT NULL,
    record jsonb NOT NULL,
    game_link jsonb NOT NULL,
    book_valid_until timestamptz,
    reference_valid_until timestamptz,
    net_ev numeric,
    active boolean NOT NULL DEFAULT true,
    UNIQUE (venue,native_event_id,native_market_id,native_outcome_id)
);
CREATE INDEX native_trading_slate ON public.native_trading_offer(starts_at,venue,league,family);
CREATE INDEX native_trading_snapshot_offer ON public.native_trading_snapshot(offer_id,created_at);
CREATE INDEX native_trading_snapshot_age ON public.native_trading_snapshot(created_at);
CREATE INDEX native_trading_current_snapshot ON public.native_trading_offer(snapshot_id);
