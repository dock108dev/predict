-- A review reference owns its exact immutable result and, via its FK, the inputs.
CREATE TABLE comparison_snapshot_review (
    result_id text PRIMARY KEY REFERENCES comparison_snapshot_result(id)
);
-- Preserve the existing D02 handoff examples on upgrade, where present.
INSERT INTO comparison_snapshot_review SELECT id FROM comparison_snapshot_result WHERE id IN (
    '7c3c9d53638543f0a0f4aefd3a43eb41',
    '5214a42a1b9b473c9c2c5a0d462e44de',
    '555d7edd9d2341379c3e5380b667a219',
    '0419619b03d048da9b9cc57a7f129043',
    '2cf0127e469849169a445e3c45b00af0',
    '4377c2c0985c4b258f95d4f7787f7a80',
    '1880f68295ea4e0a811f4b5c43b6d596',
    '6d85ef4a65e64eecbac34f294c46abb8',
    '7cfe503f2f6b4202837ecc2909b0945a',
    'cf8c1d5b11714b68b75a2eef94b568eb',
    'f2099cbcbb8644349c6a568eba088b69',
    'd67c585df0134126be4002e9cd85f125',
    '3f6ad8d8d8334ed1881c07bb53a07c66',
    'f50aa7adc12c48d5875750d17ac97c65',
    '1669377e7391475483de82b43beccf49',
    '57f022586aec46e1846b9218b577eb37',
    '47333249250541eb84d48049b2edad0e'
);

-- Trigger cleanup after a small fraction of a replacement, including external images.
ALTER TABLE current_acquisition_image SET (
    autovacuum_vacuum_scale_factor=0.02, toast.autovacuum_vacuum_scale_factor=0.02
);
ALTER TABLE current_acquisition_market SET (
    autovacuum_vacuum_scale_factor=0.02, toast.autovacuum_vacuum_scale_factor=0.02
);
