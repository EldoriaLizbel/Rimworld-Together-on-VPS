BEGIN;

CREATE TABLE IF NOT EXISTS public.worker_sample (
    sampled_at timestamptz PRIMARY KEY,
    ram_used_bytes bigint CHECK (ram_used_bytes >= 0),
    ram_available_bytes bigint CHECK (ram_available_bytes >= 0),
    game_boot_id uuid,
    game_uptime_seconds integer CHECK (game_uptime_seconds >= 0)
);

SELECT 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.worker_sample TO rimworld_api'
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rimworld_api') \gexec

COMMIT;
