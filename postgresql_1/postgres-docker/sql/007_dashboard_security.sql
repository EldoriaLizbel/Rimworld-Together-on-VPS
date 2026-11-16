BEGIN;
CREATE TABLE IF NOT EXISTS public.dashboard_sessions (
    token_hash text PRIMARY KEY,
    username text NOT NULL REFERENCES public.user_profile(username) ON DELETE CASCADE ON UPDATE CASCADE,
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS dashboard_sessions_expiry_idx ON public.dashboard_sessions (expires_at);
CREATE TABLE IF NOT EXISTS public.dashboard_login_budget (
    bucket text PRIMARY KEY,
    attempts integer NOT NULL CHECK (attempts > 0),
    expires_at timestamptz NOT NULL
);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.dashboard_sessions, public.dashboard_login_budget TO rimworld_web;
COMMIT;
