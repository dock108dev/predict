-- Role corrections append evidence and retain every original checkpoint.
ALTER TABLE public.ev_experiment_game
    ADD COLUMN baseline_correction_id text REFERENCES public.ev_experiment_record(id);
