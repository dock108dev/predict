-- Exact complete-book evidence is distinct from the original price/book clock.
ALTER TABLE current_native_book ADD COLUMN confirmation jsonb;
