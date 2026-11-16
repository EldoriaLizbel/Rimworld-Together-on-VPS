-- Seed a fresh installation only. Never replace accounts in an existing database.
\getenv admin_password RIMWORLD_ADMIN_PASSWORD

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
LOCK TABLE public.user_profile IN SHARE ROW EXCLUSIVE MODE;
INSERT INTO public.user_profile (username, nickname, password, role)
SELECT 'rimworldtogether', 'Server Administrator', crypt(:'admin_password', gen_salt('bf', 12)), 'superuser'
WHERE NOT EXISTS (SELECT 1 FROM public.user_profile)
ON CONFLICT (username) DO NOTHING;

COMMIT;
