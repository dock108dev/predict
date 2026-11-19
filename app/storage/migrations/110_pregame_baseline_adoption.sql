-- Fee edits also advance revisions; a revision is not an adoption sentinel.
ALTER TABLE pregame_monitor.current_pregame_revision
    ADD COLUMN baseline_initialized boolean NOT NULL DEFAULT false;
-- Existing collectors start their collection runs only after startup adoption.
UPDATE pregame_monitor.current_pregame_revision SET baseline_initialized=true
WHERE EXISTS(SELECT 1 FROM pregame_monitor.current_event)
   OR EXISTS(SELECT 1 FROM activity_collection_run);
