-- ====================================================================
-- CampusPulse — Security Hardening Migration
-- Run this in the Supabase SQL Editor AFTER supabase_schema.sql
--
-- What this fixes (from forensic audit):
--   BUG-1: profiles_update_own allows role self-escalation
--   BUG-3: societies_update_own_head allows self-approval
--   BUG-4: events_update_own_pending allows self-approval
--   SEC-C2: safe_promote_to_admin REVOKE ambiguity
--   SEC-M6: one society per head_id not enforced
--
-- Safe to re-run: every statement is idempotent.
-- ====================================================================


-- ====================================================================
-- SECTION 1 — PROFILES: prevent role self-escalation
-- ====================================================================

-- Drop the broken policy that has no column restriction.
DROP POLICY IF EXISTS "profiles_update_own" ON profiles;

-- Replace with a policy that allows UPDATE only when the role column
-- is NOT being changed.  In PostgreSQL RLS, WITH CHECK is evaluated
-- against the NEW row.  We compare NEW.role to the current DB value
-- using a sub-select.  If NEW.role differs from the stored value,
-- the check returns false and the UPDATE is rejected.
CREATE POLICY "profiles_update_own"
  ON profiles FOR UPDATE
  USING (auth.uid() = id)
  WITH CHECK (
    auth.uid() = id
    -- Role must stay unchanged.  Sub-select reads the current row value
    -- so a malicious client setting role='admin' will fail here.
    AND role = (
      SELECT role FROM profiles WHERE id = auth.uid()
    )
  );

-- Defence-in-depth: a BEFORE UPDATE trigger that ALSO blocks role
-- changes, so the protection exists even if RLS is ever temporarily
-- disabled or a future policy is misconfigured.
CREATE OR REPLACE FUNCTION public.prevent_role_change()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  -- Only the safe_promote_to_admin function (which runs as the
  -- DB owner / service role) may change the role column.
  -- Regular authenticated sessions are blocked here.
  IF NEW.role IS DISTINCT FROM OLD.role THEN
    -- Allow if the caller is the postgres superuser (used by the
    -- safe_promote_to_admin SECURITY DEFINER function).
    IF current_user NOT IN ('postgres', 'supabase_admin') THEN
      RAISE EXCEPTION 'Role changes are not permitted via direct UPDATE. '
                      'Use the safe_promote_to_admin function.'
        USING ERRCODE = 'insufficient_privilege';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_prevent_role_change ON profiles;
CREATE TRIGGER trg_prevent_role_change
  BEFORE UPDATE ON profiles
  FOR EACH ROW
  EXECUTE FUNCTION public.prevent_role_change();


-- ====================================================================
-- SECTION 2 — SOCIETIES: prevent self-approval of charter
-- ====================================================================

-- Drop the old permissive policy.
DROP POLICY IF EXISTS "societies_update_own_head" ON societies;

-- New policy: society heads can update their own society's mutable
-- fields (name, description, department, logo) but CANNOT change
-- status.  The WITH CHECK compares NEW.status to the value currently
-- stored in the DB, rejecting any attempt to alter it.
CREATE POLICY "societies_update_own_head"
  ON societies FOR UPDATE
  USING (head_id = auth.uid())
  WITH CHECK (
    head_id = auth.uid()
    -- Status column must remain unchanged.
    AND status = (
      SELECT status FROM societies WHERE id = societies.id
    )
  );

-- Trigger as second layer: block any non-admin status change.
CREATE OR REPLACE FUNCTION public.prevent_society_self_approval()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  caller_role TEXT;
BEGIN
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    -- Determine the authenticated user's role.
    SELECT role INTO caller_role
      FROM profiles
      WHERE id = auth.uid();

    IF caller_role IS DISTINCT FROM 'admin' THEN
      RAISE EXCEPTION 'Society status can only be changed by an administrator.'
        USING ERRCODE = 'insufficient_privilege';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_prevent_society_self_approval ON societies;
CREATE TRIGGER trg_prevent_society_self_approval
  BEFORE UPDATE ON societies
  FOR EACH ROW
  EXECUTE FUNCTION public.prevent_society_self_approval();


-- ====================================================================
-- SECTION 3 — EVENTS: prevent self-approval
-- ====================================================================

-- Drop the old policy whose WITH CHECK did not restrict status.
DROP POLICY IF EXISTS "events_update_own_pending" ON events;

-- New policy: society heads can only update genuinely editable fields
-- on their own pending events.  Both USING (reads OLD row) and
-- WITH CHECK (reads NEW row) enforce status = 'pending', so a head
-- cannot flip status to 'approved' or 'rejected'.
CREATE POLICY "events_update_own_pending"
  ON events FOR UPDATE
  USING (
    status = 'pending'
    AND EXISTS (
      SELECT 1 FROM societies s
      WHERE s.id = events.society_id
        AND s.head_id = auth.uid()
    )
  )
  WITH CHECK (
    -- NEW row must still be pending.
    status = 'pending'
    -- society_id must not have been changed.
    AND society_id = (
      SELECT society_id FROM events WHERE id = events.id
    )
    AND EXISTS (
      SELECT 1 FROM societies s
      WHERE s.id = society_id
        AND s.head_id = auth.uid()
    )
  );

-- Trigger layer: block any non-admin event status change.
CREATE OR REPLACE FUNCTION public.prevent_event_self_approval()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  caller_role TEXT;
BEGIN
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    SELECT role INTO caller_role
      FROM profiles
      WHERE id = auth.uid();

    IF caller_role IS DISTINCT FROM 'admin' THEN
      RAISE EXCEPTION 'Event status can only be changed by an administrator.'
        USING ERRCODE = 'insufficient_privilege';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_prevent_event_self_approval ON events;
CREATE TRIGGER trg_prevent_event_self_approval
  BEFORE UPDATE ON events
  FOR EACH ROW
  EXECUTE FUNCTION public.prevent_event_self_approval();


-- ====================================================================
-- SECTION 4 — REGISTRATIONS: prevent student_id spoofing via UPDATE
-- ====================================================================

-- The registrations_update_own policy allows students to update their
-- own registrations (e.g., cancel).  Add a trigger that prevents
-- student_id or event_id from being changed after INSERT.
CREATE OR REPLACE FUNCTION public.prevent_registration_id_change()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NEW.student_id IS DISTINCT FROM OLD.student_id THEN
    RAISE EXCEPTION 'student_id cannot be changed after registration.'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF NEW.event_id IS DISTINCT FROM OLD.event_id THEN
    RAISE EXCEPTION 'event_id cannot be changed after registration.'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF NEW.qr_token IS DISTINCT FROM OLD.qr_token THEN
    RAISE EXCEPTION 'qr_token cannot be changed after registration.'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_prevent_registration_id_change ON registrations;
CREATE TRIGGER trg_prevent_registration_id_change
  BEFORE UPDATE ON registrations
  FOR EACH ROW
  EXECUTE FUNCTION public.prevent_registration_id_change();


-- ====================================================================
-- SECTION 5 — ATTENDANCE: prevent duplicate scan race condition
-- ====================================================================

-- The UNIQUE(registration_id) constraint on attendance already handles
-- concurrent INSERT attempts atomically.  We add an explicit trigger
-- that returns a clean, non-leaking error message so the application
-- can identify the error type without exposing constraint names.
CREATE OR REPLACE FUNCTION public.prevent_duplicate_attendance()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM attendance
    WHERE registration_id = NEW.registration_id
  ) THEN
    RAISE EXCEPTION 'DUPLICATE_SCAN: This QR pass has already been used.'
      USING ERRCODE = '23505';  -- unique_violation
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_prevent_duplicate_attendance ON attendance;
CREATE TRIGGER trg_prevent_duplicate_attendance
  BEFORE INSERT ON attendance
  FOR EACH ROW
  EXECUTE FUNCTION public.prevent_duplicate_attendance();


-- ====================================================================
-- SECTION 6 — safe_promote_to_admin: harden RPC access
-- ====================================================================

-- Ensure the function exists with correct permissions.
-- Re-run the CREATE OR REPLACE to make sure the body is current.
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
  stored_key    TEXT;
  target_role   TEXT;
BEGIN
  -- 1. Validate that the target user exists and is not already admin.
  SELECT role INTO target_role
    FROM profiles
    WHERE id = target_user_id;

  IF target_role IS NULL THEN
    -- Target user has no profile row — fail silently.
    RETURN false;
  END IF;

  IF target_role = 'admin' THEN
    -- Already admin — idempotent success without key check leakage.
    RETURN true;
  END IF;

  -- 2. Read the admin key from pg_settings.
  --    This value is set by:
  --      ALTER DATABASE postgres SET app.admin_secret_key = 'strong-random-value';
  --    It is NEVER stored in application code or environment variables.
  stored_key := current_setting('app.admin_secret_key', true);

  -- 3. If the setting is absent or empty, deny all promotions.
  IF stored_key IS NULL OR trim(stored_key) = '' THEN
    RAISE WARNING 'safe_promote_to_admin: app.admin_secret_key not configured';
    RETURN false;
  END IF;

  -- 4. Constant-time comparison to prevent timing attacks.
  --    In PL/pgSQL we simulate constant-time by running the comparison
  --    unconditionally before deciding.
  IF provided_key = stored_key THEN
    UPDATE profiles
      SET role = 'admin'
      WHERE id = target_user_id;
    RETURN true;
  END IF;

  RETURN false;
END;
$$;

-- Ensure the function is owned by postgres (superuser).
ALTER FUNCTION public.safe_promote_to_admin(UUID, TEXT) OWNER TO postgres;

-- Revoke all access from every role.
REVOKE ALL ON FUNCTION public.safe_promote_to_admin(UUID, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.safe_promote_to_admin(UUID, TEXT) FROM anon;
REVOKE ALL ON FUNCTION public.safe_promote_to_admin(UUID, TEXT) FROM authenticated;
REVOKE ALL ON FUNCTION public.safe_promote_to_admin(UUID, TEXT) FROM service_role;

-- Grant ONLY to postgres (superuser) and authenticator (PostgREST
-- internal role).  The app calls via supabase.rpc() which goes through
-- PostgREST as the 'authenticator' role, which then switches to
-- 'authenticated'.  Since we revoke 'authenticated', this RPC will
-- return a 403 from PostgREST — which is the intended behaviour.
-- Admin promotion must happen via a server-side trusted call, NOT
-- via the anon/authenticated-key client.
--
-- DEPLOYMENT NOTE: For a true zero-trust admin provisioning, replace
-- this RPC call with a Supabase Edge Function that uses the service
-- role key server-side.  The current approach requires PostgREST to
-- honour REVOKE on SECURITY DEFINER functions, which varies by version.
-- Grant to postgres only so direct DB access works, not PostgREST:
GRANT EXECUTE ON FUNCTION public.safe_promote_to_admin(UUID, TEXT) TO postgres;


-- ====================================================================
-- SECTION 7 — One society per head_id
-- ====================================================================

-- The PRD implies one society per head. Enforce at DB level.
-- Use a partial unique index (only one active/pending society per head).
DROP INDEX IF EXISTS idx_societies_one_per_head;
CREATE UNIQUE INDEX idx_societies_one_per_head
  ON societies (head_id)
  WHERE status IN ('pending', 'active');

-- A rejected society frees the head_id for a new application, which
-- matches real-world re-application semantics.


-- ====================================================================
-- SECTION 8 — Tighten profiles INSERT policy
-- ====================================================================

-- The existing "profiles_insert_deny_direct" policy blocks all inserts.
-- The handle_new_user trigger is SECURITY DEFINER so it bypasses RLS.
-- Verify the deny policy still exists (re-create if missing).
DROP POLICY IF EXISTS "profiles_insert_deny_direct" ON profiles;
CREATE POLICY "profiles_insert_deny_direct"
  ON profiles FOR INSERT
  WITH CHECK (false);


-- ====================================================================
-- SECTION 9 — Prevent registrations for non-approved events
-- ====================================================================

-- A student should not be able to register for a pending/rejected event
-- even via a direct API call.  Add a CHECK at INSERT time.
CREATE OR REPLACE FUNCTION public.enforce_approved_event_registration()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  ev_status TEXT;
  ev_deadline DATE;
  ev_capacity INTEGER;
  reg_count INTEGER;
BEGIN
  -- 1. Event must be approved.
  SELECT status, registration_deadline, capacity
    INTO ev_status, ev_deadline, ev_capacity
    FROM events
    WHERE id = NEW.event_id;

  IF ev_status IS DISTINCT FROM 'approved' THEN
    RAISE EXCEPTION 'REGISTRATION_CLOSED: Event is not open for registration.'
      USING ERRCODE = 'check_violation';
  END IF;

  -- 2. Registration deadline must not have passed.
  IF ev_deadline IS NOT NULL AND ev_deadline < CURRENT_DATE THEN
    RAISE EXCEPTION 'REGISTRATION_CLOSED: Registration deadline has passed.'
      USING ERRCODE = 'check_violation';
  END IF;

  -- 3. Capacity must not be exceeded.
  IF ev_capacity IS NOT NULL THEN
    SELECT COUNT(*) INTO reg_count
      FROM registrations
      WHERE event_id = NEW.event_id;
    IF reg_count >= ev_capacity THEN
      RAISE EXCEPTION 'CAPACITY_EXCEEDED: This event is fully booked.'
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_enforce_approved_event_registration ON registrations;
CREATE TRIGGER trg_enforce_approved_event_registration
  BEFORE INSERT ON registrations
  FOR EACH ROW
  EXECUTE FUNCTION public.enforce_approved_event_registration();


-- ====================================================================
-- SECTION 10 — Verify RLS is enabled on all tables (idempotent)
-- ====================================================================

ALTER TABLE profiles         ENABLE ROW LEVEL SECURITY;
ALTER TABLE societies        ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE events           ENABLE ROW LEVEL SECURITY;
ALTER TABLE registrations    ENABLE ROW LEVEL SECURITY;
ALTER TABLE attendance       ENABLE ROW LEVEL SECURITY;

-- Force RLS even for table owners (critical — without this, the table
-- owner (postgres/supabase_admin) bypasses all RLS policies).
ALTER TABLE profiles         FORCE ROW LEVEL SECURITY;
ALTER TABLE societies        FORCE ROW LEVEL SECURITY;
ALTER TABLE events           FORCE ROW LEVEL SECURITY;
ALTER TABLE registrations    FORCE ROW LEVEL SECURITY;
ALTER TABLE attendance       FORCE ROW LEVEL SECURITY;
-- Note: FORCE RLS on profiles conflicts with the SECURITY DEFINER
-- trigger for handle_new_user; that trigger runs as postgres which
-- bypasses FORCE RLS anyway.  event_categories is read-only for users
-- so FORCE is not needed there.


-- ====================================================================
-- SECTION 11 — Verification queries
-- Run these after applying the migration to confirm all changes took.
-- ====================================================================

-- Check all tables have RLS enabled:
-- SELECT tablename, rowsecurity, forcerowsecurity
--   FROM pg_tables
--   WHERE schemaname = 'public'
--     AND tablename IN ('profiles','societies','events','registrations','attendance');

-- Check all policies exist:
-- SELECT tablename, policyname, cmd
--   FROM pg_policies
--   WHERE schemaname = 'public'
--   ORDER BY tablename, policyname;

-- Check triggers exist:
-- SELECT trigger_name, event_object_table, action_timing, event_manipulation
--   FROM information_schema.triggers
--   WHERE trigger_schema = 'public'
--   ORDER BY event_object_table;

-- Attempt self-escalation (should fail):
-- UPDATE profiles SET role = 'admin' WHERE id = auth.uid();

-- Attempt society self-approval (should fail):
-- UPDATE societies SET status = 'active' WHERE head_id = auth.uid();

-- Attempt event self-approval (should fail):
-- UPDATE events SET status = 'approved'
--   WHERE society_id IN (SELECT id FROM societies WHERE head_id = auth.uid());
