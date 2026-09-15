-- ====================================================================
-- CampusPulse — Adversarial QA & Security Remediation Migration
-- Run this in the Supabase SQL Editor to resolve all audit defects.
--
-- Fixes applied:
--   REG-01: Capacity calculation excludes cancelled registrations
--   REG-02: Allows re-registration if prior registration was cancelled
--   REG-03: Denies direct user INSERT on registrations, enforcing RPC
--   STUD-01: Blocks direct student self-marking of 'attended' status
--   STUD-02: Requires payment_status='paid' for paid events at check-in
--   SOC-01: Grants society heads SELECT access to attendee profiles
--   QR-01: Enforces event date and status validity during check-in
--   UX-02: Provides get_event_reg_counts() RPC for accurate UI capacity
-- ====================================================================


-- ── 1. RLS: Allow Society Heads to view student attendee profiles (SOC-01) ─────
DROP POLICY IF EXISTS "profiles_select_society_roster" ON profiles;
CREATE POLICY "profiles_select_society_roster"
  ON profiles FOR SELECT
  USING (
    EXISTS (
      SELECT 1 FROM registrations r
      JOIN events e ON e.id = r.event_id
      JOIN societies s ON s.id = e.society_id
      WHERE r.student_id = profiles.id
        AND s.head_id = auth.uid()
    )
  );


-- ── 2. RLS: Force all registrations through register_for_event RPC (REG-03) ───
-- Disallow direct client INSERTs so that capacity race conditions are impossible.
DROP POLICY IF EXISTS "registrations_insert_own" ON registrations;
DROP POLICY IF EXISTS "registrations_insert_deny_direct" ON registrations;
CREATE POLICY "registrations_insert_deny_direct"
  ON registrations FOR INSERT
  WITH CHECK (false);


-- ── 3. Trigger: Prevent direct self-marking of attendance (STUD-01) ─────────────
CREATE OR REPLACE FUNCTION public.prevent_direct_attendance_tampering()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  -- Prevent student or non-superuser from directly setting status='attended'
  IF NEW.registration_status = 'attended' AND (OLD.registration_status IS DISTINCT FROM 'attended') THEN
    IF current_user NOT IN ('postgres', 'supabase_admin') THEN
      RAISE EXCEPTION 'Attendance can only be recorded via the official check-in console.'
        USING ERRCODE = 'insufficient_privilege';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_prevent_direct_attendance_tampering ON registrations;
CREATE TRIGGER trg_prevent_direct_attendance_tampering
  BEFORE UPDATE ON registrations
  FOR EACH ROW
  EXECUTE FUNCTION public.prevent_direct_attendance_tampering();


-- ── 4. Trigger: Update fallback capacity check to exclude cancelled (REG-01) ──
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
  -- 1. Event must be approved
  SELECT status, registration_deadline, capacity
    INTO ev_status, ev_deadline, ev_capacity
    FROM events
    WHERE id = NEW.event_id;

  IF ev_status IS DISTINCT FROM 'approved' THEN
    RAISE EXCEPTION 'REGISTRATION_CLOSED: Event is not open for registration.'
      USING ERRCODE = 'check_violation';
  END IF;

  -- 2. Registration deadline must not have passed
  IF ev_deadline IS NOT NULL AND ev_deadline < CURRENT_DATE THEN
    RAISE EXCEPTION 'REGISTRATION_CLOSED: Registration deadline has passed.'
      USING ERRCODE = 'check_violation';
  END IF;

  -- 3. Capacity check (excludes cancelled registrations - REG-01)
  IF ev_capacity IS NOT NULL THEN
    SELECT COUNT(*) INTO reg_count
      FROM registrations
      WHERE event_id = NEW.event_id
        AND registration_status IN ('confirmed', 'attended');

    IF reg_count >= ev_capacity THEN
      RAISE EXCEPTION 'CAPACITY_EXCEEDED: This event is fully booked.'
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;

  RETURN NEW;
END;
$$;


-- ── 5. Function: register_for_event (REG-01, REG-02, STUD-02) ───────────────────
CREATE OR REPLACE FUNCTION public.register_for_event(
  p_event_id UUID,
  p_qr_token TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_student_id    UUID := auth.uid();
  v_event         events%ROWTYPE;
  v_reg_count     INTEGER;
  v_existing_id   UUID;
  v_existing_status TEXT;
  v_new_reg_id    UUID;
BEGIN
  -- 1. Caller must be authenticated
  IF v_student_id IS NULL THEN
    RETURN jsonb_build_object('ok', false, 'error', 'UNAUTHENTICATED');
  END IF;

  -- 2. Lock the event row to prevent concurrent race on capacity
  SELECT * INTO v_event
    FROM events
    WHERE id = p_event_id
    FOR UPDATE;

  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'error', 'EVENT_NOT_FOUND');
  END IF;

  -- 3. Event must be in a registrable state
  IF v_event.status = 'cancelled' THEN
    RETURN jsonb_build_object('ok', false, 'error', 'CANCELLED');
  END IF;

  IF v_event.status = 'completed' THEN
    RETURN jsonb_build_object('ok', false, 'error', 'COMPLETED');
  END IF;

  IF v_event.status != 'approved' THEN
    RETURN jsonb_build_object('ok', false, 'error', 'NOT_APPROVED');
  END IF;

  -- 4. Registration deadline check
  IF v_event.registration_deadline IS NOT NULL
     AND v_event.registration_deadline < CURRENT_DATE THEN
    RETURN jsonb_build_object('ok', false, 'error', 'DEADLINE_PASSED');
  END IF;

  -- 5. Duplicate registration check & Cancelled Re-activation (REG-02)
  SELECT id, registration_status INTO v_existing_id, v_existing_status
    FROM registrations
    WHERE event_id = p_event_id
      AND student_id = v_student_id
    LIMIT 1;

  IF FOUND THEN
    -- If already confirmed or attended, reject as duplicate
    IF v_existing_status IN ('confirmed', 'attended') THEN
      RETURN jsonb_build_object('ok', false, 'error', 'DUPLICATE');
    END IF;

    -- If prior registration was cancelled, re-activate it under capacity limit
    IF v_existing_status = 'cancelled' THEN
      -- Check capacity first (REG-01)
      IF v_event.capacity IS NOT NULL THEN
        SELECT COUNT(*) INTO v_reg_count
          FROM registrations
          WHERE event_id = p_event_id
            AND registration_status IN ('confirmed', 'attended');

        IF v_reg_count >= v_event.capacity THEN
          RETURN jsonb_build_object('ok', false, 'error', 'CAPACITY_EXCEEDED');
        END IF;
      END IF;

      -- Check QR token uniqueness
      IF EXISTS (SELECT 1 FROM registrations WHERE qr_token = p_qr_token) THEN
        RETURN jsonb_build_object('ok', false, 'error', 'QR_COLLISION');
      END IF;

      -- Re-activate registration
      UPDATE registrations
        SET registration_status = 'confirmed',
            qr_token            = p_qr_token,
            registered_at       = timezone('utc', now()),
            payment_status      = CASE WHEN v_event.is_paid THEN 'unpaid' ELSE 'paid' END
        WHERE id = v_existing_id;

      RETURN jsonb_build_object(
        'ok',              true,
        'registration_id', v_existing_id,
        'qr_token',        p_qr_token
      );
    END IF;
  END IF;

  -- 6. Capacity check: count active registrations only (REG-01)
  IF v_event.capacity IS NOT NULL THEN
    SELECT COUNT(*) INTO v_reg_count
      FROM registrations
      WHERE event_id = p_event_id
        AND registration_status IN ('confirmed', 'attended');

    IF v_reg_count >= v_event.capacity THEN
      RETURN jsonb_build_object('ok', false, 'error', 'CAPACITY_EXCEEDED');
    END IF;
  END IF;

  -- 7. QR token uniqueness
  IF EXISTS (SELECT 1 FROM registrations WHERE qr_token = p_qr_token) THEN
    RETURN jsonb_build_object('ok', false, 'error', 'QR_COLLISION');
  END IF;

  -- 8. Insert new registration (Free events are 'paid', paid events are 'unpaid')
  INSERT INTO registrations (
    id,
    event_id,
    student_id,
    payment_status,
    registration_status,
    qr_token
  ) VALUES (
    gen_random_uuid(),
    p_event_id,
    v_student_id,
    CASE WHEN v_event.is_paid THEN 'unpaid' ELSE 'paid' END,
    'confirmed',
    p_qr_token
  )
  RETURNING id INTO v_new_reg_id;

  RETURN jsonb_build_object(
    'ok',              true,
    'registration_id', v_new_reg_id,
    'qr_token',        p_qr_token
  );

EXCEPTION
  WHEN unique_violation THEN
    RETURN jsonb_build_object('ok', false, 'error', 'DUPLICATE');
  WHEN OTHERS THEN
    RAISE WARNING 'register_for_event unexpected error: % %', SQLSTATE, SQLERRM;
    RETURN jsonb_build_object('ok', false, 'error', 'INTERNAL_ERROR');
END;
$$;

REVOKE ALL  ON FUNCTION public.register_for_event(UUID, TEXT) FROM PUBLIC;
REVOKE ALL  ON FUNCTION public.register_for_event(UUID, TEXT) FROM anon;
GRANT EXECUTE ON FUNCTION public.register_for_event(UUID, TEXT) TO authenticated;


-- ── 6. Function: validate_attendance (STUD-02, QR-01) ──────────────────────────
CREATE OR REPLACE FUNCTION public.validate_attendance(
  p_qr_token TEXT,
  p_event_id UUID
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_caller_id   UUID := auth.uid();
  v_society_id  UUID;
  v_head_id     UUID;
  v_event       events%ROWTYPE;
  v_reg         registrations%ROWTYPE;
  v_attendee    TEXT;
BEGIN
  -- 1. Caller must be authenticated
  IF v_caller_id IS NULL THEN
    RETURN jsonb_build_object('ok', false, 'error', 'UNAUTHENTICATED');
  END IF;

  -- 2. Fetch event and verify caller is the society head owning the event
  SELECT * INTO v_event
    FROM events
    WHERE id = p_event_id;

  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'error', 'INVALID_EVENT');
  END IF;

  SELECT head_id INTO v_head_id
    FROM societies
    WHERE id = v_event.society_id;

  IF v_head_id IS DISTINCT FROM v_caller_id THEN
    RETURN jsonb_build_object('ok', false, 'error', 'NOT_SOCIETY_HEAD');
  END IF;

  -- 3. Temporal QR check: reject expired/completed events (QR-01)
  IF v_event.date < CURRENT_DATE OR v_event.status = 'completed' THEN
    RETURN jsonb_build_object('ok', false, 'error', 'EVENT_EXPIRED');
  END IF;

  -- 4. Fetch and lock the registration row
  SELECT * INTO v_reg
    FROM registrations
    WHERE qr_token = p_qr_token
      AND event_id = p_event_id
    FOR UPDATE;

  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'error', 'INVALID_TOKEN');
  END IF;

  -- 5. Registration status check
  IF v_reg.registration_status = 'cancelled' THEN
    RETURN jsonb_build_object('ok', false, 'error', 'CANCELLED_REGISTRATION');
  END IF;

  IF v_reg.registration_status = 'attended' THEN
    RETURN jsonb_build_object('ok', false, 'error', 'ALREADY_ATTENDED');
  END IF;

  -- 6. Payment status check for paid events (STUD-02)
  IF v_event.is_paid AND v_reg.payment_status != 'paid' THEN
    RETURN jsonb_build_object('ok', false, 'error', 'UNPAID_REGISTRATION');
  END IF;

  -- 7. Check for existing attendance row
  IF EXISTS (SELECT 1 FROM attendance WHERE registration_id = v_reg.id) THEN
    RETURN jsonb_build_object('ok', false, 'error', 'ALREADY_ATTENDED');
  END IF;

  -- 8. Fetch attendee display name
  SELECT name INTO v_attendee FROM profiles WHERE id = v_reg.student_id;

  -- 9. Atomically record attendance
  INSERT INTO attendance (registration_id, status)
    VALUES (v_reg.id, 'valid');

  UPDATE registrations
    SET registration_status = 'attended'
    WHERE id = v_reg.id;

  RETURN jsonb_build_object(
    'ok',            true,
    'attendee_name', COALESCE(v_attendee, 'Student'),
    'event_title',   COALESCE(v_event.title, 'Campus Event')
  );

EXCEPTION
  WHEN unique_violation THEN
    RETURN jsonb_build_object('ok', false, 'error', 'ALREADY_ATTENDED');
  WHEN OTHERS THEN
    RAISE WARNING 'validate_attendance unexpected error: % %', SQLSTATE, SQLERRM;
    RETURN jsonb_build_object('ok', false, 'error', 'INTERNAL_ERROR');
END;
$$;

REVOKE ALL  ON FUNCTION public.validate_attendance(TEXT, UUID) FROM PUBLIC;
REVOKE ALL  ON FUNCTION public.validate_attendance(TEXT, UUID) FROM anon;
GRANT EXECUTE ON FUNCTION public.validate_attendance(TEXT, UUID) TO authenticated;


-- ── 7. Function: get_event_reg_counts (UX-02) ──────────────────────────────────
-- Allows student dashboard to accurately query live capacity without exposing student rows
CREATE OR REPLACE FUNCTION public.get_event_reg_counts(p_event_ids UUID[])
RETURNS TABLE (event_id UUID, reg_count BIGINT)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT r.event_id, COUNT(*)::BIGINT AS reg_count
  FROM registrations r
  WHERE r.event_id = ANY(p_event_ids)
    AND r.registration_status IN ('confirmed', 'attended')
  GROUP BY r.event_id;
$$;

REVOKE ALL  ON FUNCTION public.get_event_reg_counts(UUID[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_event_reg_counts(UUID[]) TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_event_reg_counts(UUID[]) TO anon;
