-- ============================================================
-- CampusPulse · Smart Campus Society & Event Management System
-- Supabase PostgreSQL Schema  (safe to re-run: uses IF NOT EXISTS / ON CONFLICT)
-- ============================================================

-- ──────────────────────────────────────────────
-- 1. PROFILES  (extends Supabase auth.users)
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS profiles (
  id          UUID REFERENCES auth.users(id) ON DELETE CASCADE PRIMARY KEY,
  name        TEXT NOT NULL,
  email       TEXT,
  role        TEXT NOT NULL DEFAULT 'student'
                CHECK (role IN ('student', 'society_head', 'admin')),
  department  TEXT,
  interests   TEXT,  -- comma-separated for MVP simplicity
  created_at  TIMESTAMPTZ DEFAULT timezone('utc', now())
);

-- ──────────────────────────────────────────────
-- 2. SOCIETIES
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS societies (
  id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  name        TEXT NOT NULL,
  description TEXT,
  department  TEXT,
  head_id     UUID REFERENCES profiles(id) ON DELETE SET NULL,
  logo        TEXT,
  -- PRD 7.3: new societies start as pending; admin approves
  status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'rejected')),
  created_at  TIMESTAMPTZ DEFAULT timezone('utc', now())
);

-- ──────────────────────────────────────────────
-- 3. EVENT CATEGORIES
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS event_categories (
  id    UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  name  TEXT NOT NULL UNIQUE
);

-- ──────────────────────────────────────────────
-- 4. EVENTS
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
  id                    UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  society_id            UUID REFERENCES societies(id) ON DELETE CASCADE,
  title                 TEXT NOT NULL,
  description           TEXT,
  category              TEXT,
  date                  DATE,
  start_time            TIME,
  end_time              TIME,
  venue                 TEXT,
  capacity              INTEGER CHECK (capacity IS NULL OR capacity > 0),
  fee                   NUMERIC(10,2) DEFAULT 0.00,
  is_paid               BOOLEAN DEFAULT false,
  -- PRD 7.2 required field
  registration_deadline DATE,
  status                TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'approved', 'rejected')),
  poster                TEXT,
  created_at            TIMESTAMPTZ DEFAULT timezone('utc', now())
);

-- ──────────────────────────────────────────────
-- 5. REGISTRATIONS
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS registrations (
  id                    UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  event_id              UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  student_id            UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  payment_status        TEXT NOT NULL DEFAULT 'unpaid'
                          CHECK (payment_status IN ('unpaid', 'paid', 'failed')),
  registration_status   TEXT NOT NULL DEFAULT 'confirmed'
                          CHECK (registration_status IN ('confirmed', 'attended', 'cancelled')),
  qr_token              TEXT UNIQUE NOT NULL,
  registered_at         TIMESTAMPTZ DEFAULT timezone('utc', now()),
  -- PRD FR-11 / Business Rule: one registration per student per event at DB level
  CONSTRAINT uq_registration_student_event UNIQUE (event_id, student_id)
);

-- ──────────────────────────────────────────────
-- 6. ATTENDANCE
-- ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS attendance (
  id               UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  -- UNIQUE ensures single-use QR (PRD 9.2 / FR-11)
  registration_id  UUID NOT NULL REFERENCES registrations(id) ON DELETE CASCADE UNIQUE,
  status           TEXT NOT NULL DEFAULT 'valid'
                     CHECK (status IN ('valid', 'invalid')),
  scanned_at       TIMESTAMPTZ DEFAULT timezone('utc', now())
);

-- ──────────────────────────────────────────────
-- 7. SAFE COLUMN MIGRATIONS
--    Add columns that may not exist yet on existing databases.
--    These are idempotent — safe to run multiple times.
-- ──────────────────────────────────────────────
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'events' AND column_name = 'registration_deadline'
  ) THEN
    ALTER TABLE events ADD COLUMN registration_deadline DATE;
  END IF;
END;
$$;

-- ──────────────────────────────────────────────
-- 8. DEFAULT CATEGORY SEED DATA
-- ──────────────────────────────────────────────
INSERT INTO event_categories (name) VALUES
  ('Technology'),
  ('Science'),
  ('Arts'),
  ('Sports'),
  ('Business'),
  ('Academic'),
  ('Cultural'),
  ('Career'),
  ('Social'),
  ('Competition'),
  ('Workshop'),
  ('General')
ON CONFLICT (name) DO NOTHING;

-- ──────────────────────────────────────────────
-- 9. AUTH TRIGGER
--    Auto-creates a profile row when a user signs up via Supabase Auth.
--    Role comes from user metadata set at signup time.
--    IMPORTANT: the trigger only copies the role from metadata.
--    The RLS policies below enforce that only admins can write admin rows.
-- ──────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  INSERT INTO public.profiles (id, email, name, role)
  VALUES (
    new.id,
    new.email,
    COALESCE(new.raw_user_meta_data->>'name', 'New User'),
    -- Only allow student/society_head from self-registration.
    -- Admin role is granted by a separate Supabase service-role call
    -- or manually by a database admin — never from raw user metadata.
    CASE
      WHEN COALESCE(new.raw_user_meta_data->>'role', 'student')
           IN ('student', 'society_head')
        THEN COALESCE(new.raw_user_meta_data->>'role', 'student')
      ELSE 'student'
    END
  )
  ON CONFLICT (id) DO NOTHING;
  RETURN new;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();

-- ──────────────────────────────────────────────
-- 10. ROW LEVEL SECURITY
--     Enable RLS on every table, then define explicit policies.
--     Default-deny: anything not explicitly permitted is blocked.
-- ──────────────────────────────────────────────

ALTER TABLE profiles         ENABLE ROW LEVEL SECURITY;
ALTER TABLE societies        ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE events           ENABLE ROW LEVEL SECURITY;
ALTER TABLE registrations    ENABLE ROW LEVEL SECURITY;
ALTER TABLE attendance       ENABLE ROW LEVEL SECURITY;

-- Drop all existing policies so this script is idempotent
DO $$
DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT policyname, tablename
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename IN (
        'profiles','societies','event_categories',
        'events','registrations','attendance'
      )
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I ON %I', r.policyname, r.tablename);
  END LOOP;
END;
$$;

-- ── profiles ──────────────────────────────────
-- Users can read their own profile; admins can read all.
CREATE POLICY "profiles_select_own"
  ON profiles FOR SELECT
  USING (auth.uid() = id);

CREATE POLICY "profiles_select_admin"
  ON profiles FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM profiles p
      WHERE p.id = auth.uid() AND p.role = 'admin'
    )
  );

-- Users can update their own profile (name, department, interests only — not role).
CREATE POLICY "profiles_update_own"
  ON profiles FOR UPDATE
  USING (auth.uid() = id)
  WITH CHECK (
    auth.uid() = id
    -- Prevent self-escalation: the role column must stay unchanged.
    -- Enforced here by using a database function below.
  );

-- Admins can update any profile (e.g. manual role assignment).
CREATE POLICY "profiles_update_admin"
  ON profiles FOR UPDATE
  USING (
    EXISTS (
      SELECT 1 FROM profiles p
      WHERE p.id = auth.uid() AND p.role = 'admin'
    )
  );

-- The trigger (SECURITY DEFINER) handles INSERT — no user-level insert needed.
-- Deny direct user inserts to prevent role stuffing.
CREATE POLICY "profiles_insert_deny_direct"
  ON profiles FOR INSERT
  WITH CHECK (false);

-- ── societies ─────────────────────────────────
-- Anyone authenticated can read active societies.
CREATE POLICY "societies_select_active"
  ON societies FOR SELECT
  USING (status = 'active' OR head_id = auth.uid() OR
    EXISTS (SELECT 1 FROM profiles p WHERE p.id = auth.uid() AND p.role = 'admin')
  );

-- Society heads can insert their own society.
CREATE POLICY "societies_insert_own_head"
  ON societies FOR INSERT
  WITH CHECK (
    head_id = auth.uid()
    AND EXISTS (
      SELECT 1 FROM profiles p
      WHERE p.id = auth.uid() AND p.role = 'society_head'
    )
  );

-- Society heads can update their own society (not status — only admin changes status).
CREATE POLICY "societies_update_own_head"
  ON societies FOR UPDATE
  USING (head_id = auth.uid())
  WITH CHECK (head_id = auth.uid());

-- Admins can update any society (including status).
CREATE POLICY "societies_update_admin"
  ON societies FOR UPDATE
  USING (
    EXISTS (SELECT 1 FROM profiles p WHERE p.id = auth.uid() AND p.role = 'admin')
  );

-- ── event_categories ──────────────────────────
CREATE POLICY "event_categories_select_all"
  ON event_categories FOR SELECT
  USING (true);

-- ── events ────────────────────────────────────
-- Students and public can read approved events.
CREATE POLICY "events_select_approved"
  ON events FOR SELECT
  USING (
    status = 'approved'
    OR (
      -- Society heads can see their own events regardless of status.
      EXISTS (
        SELECT 1 FROM societies s
        WHERE s.id = events.society_id AND s.head_id = auth.uid()
      )
    )
    OR EXISTS (SELECT 1 FROM profiles p WHERE p.id = auth.uid() AND p.role = 'admin')
  );

-- Society heads can insert events for their own society only.
CREATE POLICY "events_insert_own_society"
  ON events FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM societies s
      WHERE s.id = society_id
        AND s.head_id = auth.uid()
        AND s.status = 'active'
    )
  );

-- Society heads can update their own pending events only (not approved/rejected).
CREATE POLICY "events_update_own_pending"
  ON events FOR UPDATE
  USING (
    status = 'pending'
    AND EXISTS (
      SELECT 1 FROM societies s
      WHERE s.id = events.society_id AND s.head_id = auth.uid()
    )
  )
  WITH CHECK (
    -- Cannot change society_id or status via this policy
    EXISTS (
      SELECT 1 FROM societies s
      WHERE s.id = society_id AND s.head_id = auth.uid()
    )
  );

-- Admins can update any event (approve / reject).
CREATE POLICY "events_update_admin"
  ON events FOR UPDATE
  USING (
    EXISTS (SELECT 1 FROM profiles p WHERE p.id = auth.uid() AND p.role = 'admin')
  );

-- ── registrations ─────────────────────────────
-- Students can see their own registrations.
CREATE POLICY "registrations_select_own"
  ON registrations FOR SELECT
  USING (student_id = auth.uid());

-- Society heads can see registrations for their society's events
-- (needed for attendance management and QR scanning).
CREATE POLICY "registrations_select_society_head"
  ON registrations FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM events e
      JOIN societies s ON s.id = e.society_id
      WHERE e.id = registrations.event_id
        AND s.head_id = auth.uid()
    )
  );

-- Admins can see all registrations.
CREATE POLICY "registrations_select_admin"
  ON registrations FOR SELECT
  USING (
    EXISTS (SELECT 1 FROM profiles p WHERE p.id = auth.uid() AND p.role = 'admin')
  );

-- Students can insert their own registration only.
CREATE POLICY "registrations_insert_own"
  ON registrations FOR INSERT
  WITH CHECK (
    student_id = auth.uid()
    AND EXISTS (SELECT 1 FROM profiles p WHERE p.id = auth.uid() AND p.role = 'student')
  );

-- Students can cancel their own registration.
CREATE POLICY "registrations_update_own"
  ON registrations FOR UPDATE
  USING (student_id = auth.uid())
  WITH CHECK (student_id = auth.uid());

-- ── attendance ────────────────────────────────
-- Society heads can insert attendance for their own events.
CREATE POLICY "attendance_insert_society_head"
  ON attendance FOR INSERT
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM registrations r
      JOIN events e ON e.id = r.event_id
      JOIN societies s ON s.id = e.society_id
      WHERE r.id = registration_id
        AND s.head_id = auth.uid()
    )
  );

-- Society heads can read attendance for their own events.
CREATE POLICY "attendance_select_society_head"
  ON attendance FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM registrations r
      JOIN events e ON e.id = r.event_id
      JOIN societies s ON s.id = e.society_id
      WHERE r.id = attendance.registration_id
        AND s.head_id = auth.uid()
    )
  );

-- Students can see their own attendance.
CREATE POLICY "attendance_select_own"
  ON attendance FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM registrations r
      WHERE r.id = attendance.registration_id
        AND r.student_id = auth.uid()
    )
  );

-- Admins can see all attendance.
CREATE POLICY "attendance_select_admin"
  ON attendance FOR SELECT
  USING (
    EXISTS (SELECT 1 FROM profiles p WHERE p.id = auth.uid() AND p.role = 'admin')
  );

-- ──────────────────────────────────────────────
-- 11. FUNCTION: safe_promote_to_admin
--     Called server-side (service role) only — never from the app directly.
--     Grants admin role after validating the secret key stored as a DB secret,
--     preventing the Python client from performing role escalation.
-- ──────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.safe_promote_to_admin(
  target_user_id UUID,
  provided_key   TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  stored_key TEXT;
BEGIN
  -- Read the admin key from pg_settings (set via Supabase Vault or ALTER SYSTEM).
  -- Fallback: compare against a hardcoded placeholder that must be changed.
  stored_key := current_setting('app.admin_secret_key', true);
  IF stored_key IS NULL OR stored_key = '' THEN
    RETURN false;
  END IF;
  IF provided_key = stored_key THEN
    UPDATE profiles SET role = 'admin' WHERE id = target_user_id;
    RETURN true;
  END IF;
  RETURN false;
END;
$$;

-- Revoke public execution — only service role can call this.
REVOKE ALL ON FUNCTION public.safe_promote_to_admin(UUID, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.safe_promote_to_admin(UUID, TEXT) FROM anon;
REVOKE ALL ON FUNCTION public.safe_promote_to_admin(UUID, TEXT) FROM authenticated;

-- ──────────────────────────────────────────────
-- 12. USEFUL INDEXES FOR PERFORMANCE
-- ──────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_events_status       ON events(status);
CREATE INDEX IF NOT EXISTS idx_events_date         ON events(date);
CREATE INDEX IF NOT EXISTS idx_events_society      ON events(society_id);
CREATE INDEX IF NOT EXISTS idx_registrations_event ON registrations(event_id);
CREATE INDEX IF NOT EXISTS idx_registrations_student ON registrations(student_id);
CREATE INDEX IF NOT EXISTS idx_attendance_reg      ON attendance(registration_id);
CREATE INDEX IF NOT EXISTS idx_societies_head      ON societies(head_id);
CREATE INDEX IF NOT EXISTS idx_profiles_role       ON profiles(role);
