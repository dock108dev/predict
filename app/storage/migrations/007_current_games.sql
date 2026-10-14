-- Current-specific exact payloads; no legacy [0,1] price or serializer reuse.
CREATE TABLE current_envelope (
 id text PRIMARY KEY, payload_sha256 text NOT NULL, payload text NOT NULL,
 source text NOT NULL, kind text NOT NULL, retained_at timestamptz NOT NULL
);
CREATE TABLE current_import_cursor (path text PRIMARY KEY, byte_offset bigint NOT NULL CHECK(byte_offset>=0));
CREATE TABLE current_source_projection (source text NOT NULL, kind text NOT NULL, native_id text NOT NULL,
 observed_at timestamptz NOT NULL, envelope_id text NOT NULL REFERENCES current_envelope(id), payload text NOT NULL,
 PRIMARY KEY(source,kind,native_id));
CREATE TABLE current_game_projection (game_key text PRIMARY KEY, input_version text NOT NULL,
 payload text NOT NULL, updated_at timestamptz NOT NULL);
CREATE TABLE current_game_snapshot (id text PRIMARY KEY, game_key text NOT NULL, input_version text NOT NULL,
 policy_version text NOT NULL, as_of timestamptz NOT NULL, payload_sha256 text NOT NULL, payload text NOT NULL);
CREATE TABLE current_game_result (id text PRIMARY KEY, snapshot_id text NOT NULL REFERENCES current_game_snapshot(id),
 payload_sha256 text NOT NULL, payload text NOT NULL, calculated_at timestamptz NOT NULL);
CREATE TABLE current_latest_result (game_key text NOT NULL, policy_version text NOT NULL,
 input_version text NOT NULL, result_id text NOT NULL REFERENCES current_game_result(id), PRIMARY KEY(game_key,policy_version));
CREATE INDEX current_envelope_source ON current_envelope(source,retained_at);
CREATE INDEX current_game_snapshot_game ON current_game_snapshot(game_key,as_of);
CREATE TRIGGER immutable_current_envelope BEFORE UPDATE OR DELETE ON current_envelope FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
CREATE TRIGGER immutable_current_game_snapshot BEFORE UPDATE OR DELETE ON current_game_snapshot FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
CREATE TRIGGER immutable_current_game_result BEFORE UPDATE OR DELETE ON current_game_result FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
