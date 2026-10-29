-- Keep source-clock revision distinct from exact stored ladder contents.
ALTER TABLE current_native_book ADD COLUMN depth_revision text;
