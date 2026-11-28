ALTER TABLE public.ev_experiment_depth
    DROP CONSTRAINT ev_experiment_depth_payload_bytes_check,
    ADD CONSTRAINT ev_experiment_depth_payload_bytes_check
        CHECK (payload_bytes BETWEEN 1 AND 8388608);
