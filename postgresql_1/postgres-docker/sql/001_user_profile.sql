-- Table: public.user_profile  (database: app_db)
-- รันซ้ำได้ (idempotent)
--   docker compose exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < sql/001_user_profile.sql

BEGIN;

CREATE TABLE IF NOT EXISTS public.user_profile (
    username    text        PRIMARY KEY,
    nickname    text,
    password    text,
    role        text,
    created_at  timestamp   NOT NULL DEFAULT now(),
    last_login  timestamp
);

COMMENT ON TABLE  public.user_profile            IS 'ข้อมูลผู้ใช้ของแอป';
COMMENT ON COLUMN public.user_profile.username   IS 'ชื่อผู้ใช้ (primary key)';
COMMENT ON COLUMN public.user_profile.nickname   IS 'ชื่อเล่น / ชื่อที่แสดง';
COMMENT ON COLUMN public.user_profile.password   IS 'ควรเก็บเป็น hash (เช่น bcrypt/argon2) ห้ามเก็บ plain text';
COMMENT ON COLUMN public.user_profile.role       IS 'บทบาทของผู้ใช้ เช่น admin, user';
COMMENT ON COLUMN public.user_profile.created_at IS 'เวลาที่สร้าง (default = now())';
COMMENT ON COLUMN public.user_profile.last_login IS 'เวลาที่ล็อกอินล่าสุด';

COMMIT;
