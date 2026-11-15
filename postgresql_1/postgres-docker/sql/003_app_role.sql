-- The web service can manage application accounts with its own database login.
\getenv web_password RIMWORLD_WEB_DB_PASSWORD

BEGIN;

SELECT format('CREATE ROLE rimworld_web LOGIN PASSWORD %L', :'web_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rimworld_web') \gexec
SELECT format('ALTER ROLE rimworld_web WITH LOGIN PASSWORD %L', :'web_password') \gexec

SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO rimworld_web', current_database()) \gexec
GRANT USAGE ON SCHEMA public TO rimworld_web;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_profile TO rimworld_web;

COMMIT;
