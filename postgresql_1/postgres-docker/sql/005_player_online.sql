BEGIN;

CREATE TABLE IF NOT EXISTS public.player_online_sample (
    sampled_at timestamptz PRIMARY KEY,
    boot_id uuid NOT NULL,
    online_players text[] NOT NULL,
    player_count integer GENERATED ALWAYS AS (cardinality(online_players)) STORED,
    session_counts jsonb NOT NULL,
    last_log_id bigint NOT NULL
);
CREATE INDEX IF NOT EXISTS player_online_sample_boot_time_idx
    ON public.player_online_sample (boot_id, sampled_at DESC);

SELECT 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.player_online_sample TO rimworld_api'
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rimworld_api') \gexec

COMMIT;
