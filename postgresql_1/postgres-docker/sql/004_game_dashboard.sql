\getenv api_password RIMWORLD_API_DB_PASSWORD
\if :{?api_password}
\else
  \set api_password ''
\endif

BEGIN;

CREATE TABLE IF NOT EXISTS public.world_config (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    revision text NOT NULL,
    settings jsonb NOT NULL,
    world_initialized boolean NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.world_config ADD COLUMN IF NOT EXISTS boot_id uuid;

CREATE TABLE IF NOT EXISTS public.server_log (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    epoch uuid NOT NULL,
    boot_id uuid NOT NULL,
    stream text NOT NULL,
    byte_offset bigint NOT NULL,
    occurred_at timestamptz NOT NULL,
    category text NOT NULL,
    description text NOT NULL,
    UNIQUE (stream, byte_offset)
);
CREATE INDEX IF NOT EXISTS server_log_timeline_idx
    ON public.server_log (epoch, occurred_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS public.player_data (
    username text PRIMARY KEY,
    colony_name text,
    colonist_count integer,
    settlement_tiles integer[] NOT NULL DEFAULT '{}',
    last_login timestamptz,
    last_save timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);

SELECT format('CREATE ROLE rimworld_api LOGIN PASSWORD %L', :'api_password')
WHERE length(:'api_password') > 0
  AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rimworld_api') \gexec
SELECT format('ALTER ROLE rimworld_api LOGIN PASSWORD %L', :'api_password')
WHERE length(:'api_password') > 0 \gexec

SELECT 'GRANT USAGE ON SCHEMA public TO rimworld_api',
       format('GRANT CONNECT ON DATABASE %I TO rimworld_api', current_database()),
       'GRANT SELECT (username, role) ON public.user_profile TO rimworld_api',
       'GRANT SELECT, INSERT, UPDATE, DELETE ON public.world_config, public.server_log, public.player_data TO rimworld_api',
       'GRANT USAGE ON SEQUENCE public.server_log_id_seq TO rimworld_api'
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rimworld_api') \gexec

COMMIT;
