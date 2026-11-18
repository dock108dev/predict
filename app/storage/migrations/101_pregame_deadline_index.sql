CREATE INDEX current_pregame_deadline ON current_pregame_calculation(valid_until) WHERE reason IS NULL;
