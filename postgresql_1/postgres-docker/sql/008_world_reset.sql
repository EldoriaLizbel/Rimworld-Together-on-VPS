BEGIN;
ALTER TABLE public.world_config ADD COLUMN IF NOT EXISTS world_reset_id uuid;
COMMIT;
