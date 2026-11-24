ALTER TABLE public.mens_d1_attempt
    DROP CONSTRAINT mens_d1_attempt_reserved_credits_check,
    ADD CONSTRAINT mens_d1_attempt_reserved_credits_check CHECK (
        reserved_credits > 0 OR (
            reserved_credits = 0 AND source = 'college_basketball_data'
            AND disposition = 'not_dispatched' AND settled_at IS NOT NULL
            AND charged_credits IS NOT DISTINCT FROM 0 AND reserved_storage_bytes = 0
        )
    );
