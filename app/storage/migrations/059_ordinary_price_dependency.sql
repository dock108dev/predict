-- Material quote identity excludes confirmation/receipt-only changes. Compute
-- once at ingestion rather than hashing the entire slate on every viewer poll.
ALTER TABLE current_offer ADD COLUMN price_dependency text;
CREATE FUNCTION current_offer_price_dependency() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.price_dependency := encode(sha256(convert_to(
        ((NEW.facts - ARRAY['times','book_confirmation','provenance']) ||
         jsonb_build_object('provenance',(NEW.facts->'provenance')-'sha256'))::text,
        'UTF8')),'hex');
    RETURN NEW;
END;
$$;
CREATE TRIGGER current_offer_price_dependency_write
BEFORE INSERT OR UPDATE ON current_offer
FOR EACH ROW EXECUTE FUNCTION current_offer_price_dependency();
UPDATE current_offer SET facts=facts;
ALTER TABLE current_offer ALTER COLUMN price_dependency SET NOT NULL;
