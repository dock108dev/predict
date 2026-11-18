-- Fee-qualified prices are independent of sportsbook probability estimates.
CREATE TABLE current_pregame_price (
    contract_id text PRIMARY KEY REFERENCES current_contract_storage(id) ON DELETE CASCADE,
    game_key text NOT NULL, start_at timestamptz NOT NULL, valid_until timestamptz NOT NULL,
    payload jsonb NOT NULL, record jsonb NOT NULL, fee_input jsonb NOT NULL
);
CREATE INDEX current_pregame_price_game ON current_pregame_price(game_key,start_at);
-- Rebuild affected games under the existing owner; no new source requests.
INSERT INTO current_pregame_work(provider,native_event_id)
    SELECT DISTINCT e.provider,e.native_event_id FROM current_event e
    ON CONFLICT(provider,native_event_id) DO UPDATE SET revision=current_pregame_work.revision+1,error=NULL;
