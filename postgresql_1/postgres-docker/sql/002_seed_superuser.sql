-- Initialize or explicitly reset the application accounts in local nonprod.
\getenv admin_password RIMWORLD_ADMIN_PASSWORD

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
LOCK TABLE public.user_profile IN SHARE ROW EXCLUSIVE MODE;
DELETE FROM public.user_profile;

INSERT INTO public.user_profile (username, nickname, password, role)
VALUES ('rimworldtogether', 'Server Administrator', crypt(:'admin_password', gen_salt('bf', 12)), 'superuser');

COMMIT;
