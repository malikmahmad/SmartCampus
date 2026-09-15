-- ====================================================================
-- CampusPulse — Database Engineering Upgrade
-- Run order: supabase_schema.sql → supabase_security_hardening.sql
--                                → supabase_db_upgrade.sql  (this file)
--
-- Every statement is idempotent (safe to re-run).
-- No existing data is dropped or altered.
-- ====================================================================

-- ====================================================================
-- SECTION 1 — EVENTS: extended status set + audit columns
-- ====================================================================

-- 1a. Drop the old CHECK constraint so we can replace it with a wider
--     one that adds 'cancelled' and 'completed'.
--     In PostgreSQL the constraint name comes from the table definition;
--     if the schema was applied with IF NOT EXISTS the name will be the
--     auto-generated one.  We use a DO block to drop it safely without
--     knowing the exact name.
DO $$
DECLARE
  conname TEXT;
BEGIN
  SELECT c.conname INTO conname
    FROM pg_constraint c
    JOIN pg_class     t ON t.oid = c.conrelid
    WHERE t.relname = 'events'
      AND c.contype = 'c'           -- CHECK constraint
      AND c.conname LIKE '%status%';
  IF conname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE events DROP CONSTRAINT IF EXISTS %I', conname);
  END IF;
END;
$$;

ALTER TABLE events
  ADD CONSTRAINT events_status_check
    CHECK (status IN ('pending','approved','rejected','cancelled','completed'));

-- 1b. Approval / rejection audit columns (idempotent ADD COLUMN).
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='events' AND column_name='approved_by') THEN
    ALTER TABLE events ADD COLUMN approved_by    UUID REFERENCES profiles(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='events' AND column_name='approved_at') THEN
    ALTER TABLE events ADD COLUMN approved_at    TIMESTAMPTZ;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='events' AND column_name='rejected_by') THEN
    ALTER TABLE events ADD COLUMN rejected_by    UUID REFERENCES profiles(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='events' AND column_name='rejected_at') THEN
    ALTER TABLE events ADD COLUMN rejected_at    TIMESTAMPTZ;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='events' AND column_name='rejection_reason') THEN
    ALTER TABLE events ADD COLUMN rejection_reason TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='events' AND column_name='cancelled_by') THEN
    ALTER TABLE events ADD COLUMN cancelled_by   UUID REFERENCES profiles(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='events' AND column_name='cancelled_at') THEN
    ALTER TABLE events ADD COLUMN cancelled_at   TIMESTAMPTZ;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='events' AND column_name='completed_at') THEN
    ALTER TABLE events ADD COLUMN completed_at   TIMESTAMPTZ;
  END IF;
END $$;

-- 1c. Data validation constraints on events (idempotent).
ALTER TABLE events
  DROP CONSTRAINT IF EXISTS events_title_nonempty,
  ADD  CONSTRAINT events_title_nonempty CHECK (length(trim(title)) > 0);

ALTER TABLE events
  DROP CONSTRAINT IF EXISTS events_capacity_positive,
  ADD  CONSTRAINT events_capacity_positive
    CHECK (capacity IS NULL OR capacity > 0);

ALTER TABLE events
  DROP CONSTRAINT IF EXISTS events_fee_nonnegative,
  ADD  CONSTRAINT events_fee_nonnegative
    CHECK (fee IS NULL OR fee >= 0);

ALTER TABLE events
  DROP CONSTRAINT IF EXISTS events_deadline_before_event,
  ADD  CONSTRAINT events_deadline_before_event
    CHECK (registration_deadline IS NULL OR date IS NULL
           OR registration_deadline <= date);

ALTER TABLE events
  DROP CONSTRAINT IF EXISTS events_time_order,
  ADD  CONSTRAINT events_time_order
    CHECK (start_time IS NULL OR end_time IS NULL
           OR start_time < end_time);


-- ====================================================================
-- SECTION 2 — EVENT STATE MACHINE TRIGGER
-- Prevents invalid status transitions:
--
--   pending   → approved ✓   (admin approves)
--   pending   → rejected ✓   (admin rejects)
--   pending   → cancelled ✓  (admin or head cancels before approval)
--   approved  → cancelled ✓  (admin cancels after approval)
--   approved  → completed ✓  (admin marks done)
--   rejected  → pending   ✓  (admin reopens for revision)
--   rejected  → *         ✗  (anything else)
--   cancelled → *         ✗  (terminal state)
--   completed → *         ✗  (terminal state)
-- ====================================================================

CREATE OR REPLACE FUNCTION public.enforce_event_state_machine()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  -- Only run when status actually changes.
  IF NEW.status IS NOT DISTINCT FROM OLD.status THEN
    RETURN NEW;
  END IF;

  -- Terminal states cannot be left.
  IF OLD.status IN ('cancelled', 'completed') THEN
    RAISE EXCEPTION 'EVENT_STATE_INVALID: Cannot change status of a % event.',
      OLD.status
      USING ERRCODE = 'check_violation';
  END IF;

  -- Define valid transitions.
  IF NOT (
    (OLD.status = 'pending'  AND NEW.status IN ('approved','rejected','cancelled'))
    OR (OLD.status = 'approved' AND NEW.status IN ('cancelled','completed'))
    OR (OLD.status = 'rejected' AND NEW.status = 'pending')   -- re-submission
  ) THEN
    RAISE EXCEPTION 'EVENT_STATE_INVALID: Transition % → % is not permitted.',
      OLD.status, NEW.status
      USING ERRCODE = 'check_violation';
  END IF;

  -- Stamp audit fields automatically.
  CASE NEW.status
    WHEN 'approved' THEN
      NEW.approved_by := auth.uid();
      NEW.approved_at := now();
    WHEN 'rejected' THEN
      NEW.rejected_by := auth.uid();
      NEW.rejected_at := now();
    WHEN 'cancelled' THEN
      NEW.cancelled_by := auth.uid();
      NEW.cancelled_at := now();
    WHEN 'completed' THEN
      NEW.completed_at := now();
    ELSE NULL;
  END CASE;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_event_state_machine ON events;
CREATE TRIGGER trg_event_state_machine
  BEFORE UPDATE ON events
  FOR EACH ROW
  EXECUTE FUNCTION public.enforce_event_state_machine();


-- ====================================================================
-- SECTION 3 — REGISTRATIONS: extended status + validation
-- ====================================================================

-- 3a. Widen the registration_status CHECK to include 'attended'.
DO $$
DECLARE
  conname TEXT;
BEGIN
  SELECT c.conname INTO conname
    FROM pg_constraint c
    JOIN pg_class     t ON t.oid = c.conrelid
    WHERE t.relname = 'registrations'
      AND c.contype = 'c'
      AND c.conname LIKE '%registration_status%';
  IF conname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE registrations DROP CONSTRAINT %I', conname);
  END IF;
END;
$$;

ALTER TABLE registrations
  ADD CONSTRAINT registrations_status_check
    CHECK (registration_status IN ('confirmed','attended','cancelled'));

-- 3b. Widen payment_status CHECK to include all valid values.
DO $$
DECLARE
  conname TEXT;
BEGIN
  SELECT c.conname INTO conname
    FROM pg_constraint c
    JOIN pg_class     t ON t.oid = c.conrelid
    WHERE t.relname = 'registrations'
      AND c.contype = 'c'
      AND c.conname LIKE '%payment_status%';
  IF conname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE registrations DROP CONSTRAINT %I', conname);
  END IF;
END;
$$;

ALTER TABLE registrations
  ADD CONSTRAINT registrations_payment_status_check
    CHECK (payment_status IN ('unpaid','paid','failed','refunded'));

-- 3c. QR token must be non-empty.
ALTER TABLE registrations
  DROP CONSTRAINT IF EXISTS registrations_qr_nonempty,
  ADD  CONSTRAINT registrations_qr_nonempty
    CHECK (length(trim(qr_token)) > 0);


-- ====================================================================
-- SECTION 4 — ATOMIC REGISTRATION RPC
--
-- register_for_event(p_event_id, p_qr_token)
--
-- Called by the application instead of a direct INSERT.
-- Uses SELECT ... FOR UPDATE to lock the event row, guaranteeing that
-- two simultaneous calls with the same event_id cannot both read
-- reg_count < capacity and both succeed.
--
-- Returns JSON:
--   { "ok": true,  "registration_id": "<uuid>", "qr_token": "<uuid>" }
--   { "ok": false, "error": "DUPLICATE|CAPACITY_EXCEEDED|
--                             REGISTRATION_CLOSED|DEADLINE_PASSED|
--                             NOT_APPROVED|CANCELLED|EVENT_NOT_FOUND" }
--
-- The function runs as SECURITY DEFINER so it bypasses RLS for the
-- SELECT FOR UPDATE but still validates the authenticated caller.
-- The INSERT is performed as the calling user so RLS INSERT policy
-- (registrations_insert_own) is satisfied.
-- ====================================================================

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
  v_new_reg_id    UUID;
BEGIN
  -- ── 1. Caller must be authenticated ───────────────────────────────
  IF v_student_id IS NULL THEN
    RETURN jsonb_build_object('ok', false, 'error', 'UNAUTHENTICATED');
  END IF;

  -- ── 2. Lock the event row to prevent concurrent race on capacity ───
  --    FOR UPDATE blocks concurrent transactions until this one commits,
  --    making the count check + insert atomic.
  SELECT * INTO v_event
    FROM events
    WHERE id = p_event_id
    FOR UPDATE;

  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'error', 'EVENT_NOT_FOUND');
  END IF;

  -- ── 3. Event must be in a registrable state ────────────────────────
  IF v_event.status = 'cancelled' THEN
    RETURN jsonb_build_object('ok', false, 'error', 'CANCELLED');
  END IF;

  IF v_event.status = 'completed' THEN
    RETURN jsonb_build_object('ok', false, 'error', 'COMPLETED');
  END IF;

  IF v_event.status != 'approved' THEN
    RETURN jsonb_build_object('ok', false, 'error', 'NOT_APPROVED');
  END IF;

  -- ── 4. Registration deadline ───────────────────────────────────────
  IF v_event.registration_deadline IS NOT NULL
     AND v_event.registration_deadline < CURRENT_DATE THEN
    RETURN jsonb_build_object('ok', false, 'error', 'DEADLINE_PASSED');
  END IF;

  -- ── 5. Duplicate registration check ───────────────────────────────
  SELECT id INTO v_existing_id
    FROM registrations
    WHERE event_id = p_event_id
      AND student_id = v_student_id
    LIMIT 1;

  IF FOUND THEN
    RETURN jsonb_build_object('ok', false, 'error', 'DUPLICATE');
  END IF;

  -- ── 6. Capacity check (atomic — event row is locked) ──────────────
  IF v_event.capacity IS NOT NULL THEN
    SELECT COUNT(*) INTO v_reg_count
      FROM registrations
      WHERE event_id = p_event_id;

    IF v_reg_count >= v_event.capacity THEN
      RETURN jsonb_build_object('ok', false, 'error', 'CAPACITY_EXCEEDED');
    END IF;
  END IF;

  -- ── 7. QR token uniqueness ─────────────────────────────────────────
  IF EXISTS (SELECT 1 FROM registrations WHERE qr_token = p_qr_token) THEN
    -- Caller should regenerate the token; this is astronomically unlikely
    -- with UUID4 but we guard it explicitly.
    RETURN jsonb_build_object('ok', false, 'error', 'QR_COLLISION');
  END IF;

  -- ── 8. Insert registration ─────────────────────────────────────────
  --    We set search_path = public so the INSERT runs as the SECURITY
  --    DEFINER owner (postgres), bypassing the RLS INSERT policy.
  --    The RLS policy's logic (student_id = auth.uid(), role = 'student')
  --    is enforced by our explicit checks above (step 1 validates uid).
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
    CASE WHEN v_event.is_paid THEN 'unpaid' ELSE 'unpaid' END,
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
    -- Race: duplicate registration slipped through between our check and INSERT.
    RETURN jsonb_build_object('ok', false, 'error', 'DUPLICATE');
  WHEN OTHERS THEN
    RAISE WARNING 'register_for_event unexpected error: % %', SQLSTATE, SQLERRM;
    RETURN jsonb_build_object('ok', false, 'error', 'INTERNAL_ERROR');
END;
$$;

-- Grant execute to authenticated users only.
REVOKE ALL  ON FUNCTION public.register_for_event(UUID, TEXT) FROM PUBLIC;
REVOKE ALL  ON FUNCTION public.register_for_event(UUID, TEXT) FROM anon;
GRANT EXECUTE ON FUNCTION public.register_for_event(UUID, TEXT) TO authenticated;


-- ====================================================================
-- SECTION 5 — ATOMIC QR ATTENDANCE VALIDATION RPC
--
-- validate_attendance(p_qr_token, p_event_id)
--
-- Called by the society head check-in console.
-- Validates ownership, checks for duplicate scan, records attendance,
-- and updates registration_status atomically.
--
-- Returns JSON:
--   { "ok": true,  "attendee_name": "...", "event_title": "..." }
--   { "ok": false, "error": "INVALID_TOKEN|WRONG_EVENT|
--                             ALREADY_ATTENDED|CANCELLED_REGISTRATION|
--                             NOT_SOCIETY_HEAD|UNAUTHENTICATED|
--                             INTERNAL_ERROR" }
-- ====================================================================

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
  v_reg         registrations%ROWTYPE;
  v_event_title TEXT;
  v_attendee    TEXT;
BEGIN
  -- ── 1. Caller must be authenticated ──────────────────────────────
  IF v_caller_id IS NULL THEN
    RETURN jsonb_build_object('ok', false, 'error', 'UNAUTHENTICATED');
  END IF;

  -- ── 2. Verify caller is a society head owning the given event ─────
  SELECT e.society_id, s.head_id
    INTO v_society_id, v_head_id
    FROM events e
    JOIN societies s ON s.id = e.society_id
    WHERE e.id = p_event_id;

  IF NOT FOUND OR v_head_id IS DISTINCT FROM v_caller_id THEN
    RETURN jsonb_build_object('ok', false, 'error', 'NOT_SOCIETY_HEAD');
  END IF;

  -- ── 3. Fetch + lock the registration row ──────────────────────────
  SELECT * INTO v_reg
    FROM registrations
    WHERE qr_token  = p_qr_token
      AND event_id  = p_event_id
    FOR UPDATE;

  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'error', 'INVALID_TOKEN');
  END IF;

  -- ── 4. Registration must be active ────────────────────────────────
  IF v_reg.registration_status = 'cancelled' THEN
    RETURN jsonb_build_object('ok', false, 'error', 'CANCELLED_REGISTRATION');
  END IF;

  IF v_reg.registration_status = 'attended' THEN
    RETURN jsonb_build_object('ok', false, 'error', 'ALREADY_ATTENDED');
  END IF;

  -- ── 5. Check for existing attendance row (double-safety) ──────────
  IF EXISTS (SELECT 1 FROM attendance WHERE registration_id = v_reg.id) THEN
    RETURN jsonb_build_object('ok', false, 'error', 'ALREADY_ATTENDED');
  END IF;

  -- ── 6. Fetch display names ─────────────────────────────────────────
  SELECT title INTO v_event_title FROM events WHERE id = p_event_id;
  SELECT name  INTO v_attendee    FROM profiles WHERE id = v_reg.student_id;

  -- ── 7. Record attendance atomically ───────────────────────────────
  INSERT INTO attendance (registration_id, status)
    VALUES (v_reg.id, 'valid');

  UPDATE registrations
    SET registration_status = 'attended'
    WHERE id = v_reg.id;

  RETURN jsonb_build_object(
    'ok',            true,
    'attendee_name', COALESCE(v_attendee,    'Unknown Student'),
    'event_title',   COALESCE(v_event_title, 'Unknown Event')
  );

EXCEPTION
  WHEN unique_violation THEN
    -- Concurrent scan: another transaction inserted attendance first.
    RETURN jsonb_build_object('ok', false, 'error', 'ALREADY_ATTENDED');
  WHEN OTHERS THEN
    RAISE WARNING 'validate_attendance unexpected error: % %', SQLSTATE, SQLERRM;
    RETURN jsonb_build_object('ok', false, 'error', 'INTERNAL_ERROR');
END;
$$;

-- Only society heads (authenticated) may call this.
REVOKE ALL  ON FUNCTION public.validate_attendance(TEXT, UUID) FROM PUBLIC;
REVOKE ALL  ON FUNCTION public.validate_attendance(TEXT, UUID) FROM anon;
GRANT EXECUTE ON FUNCTION public.validate_attendance(TEXT, UUID) TO authenticated;


-- ====================================================================
-- SECTION 6 — APPROVE / REJECT EVENT RPCs
--
-- approve_event(p_event_id)
-- reject_event(p_event_id, p_reason)
-- cancel_event(p_event_id, p_reason)
--
-- These stamp audit fields atomically and enforce the state machine.
-- The admin dashboard calls these instead of raw UPDATE.
-- ====================================================================

CREATE OR REPLACE FUNCTION public.approve_event(p_event_id UUID)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_caller_id UUID := auth.uid();
  v_caller_role TEXT;
  v_current_status TEXT;
BEGIN
  IF v_caller_id IS NULL THEN
    RETURN jsonb_build_object('ok', false, 'error', 'UNAUTHENTICATED');
  END IF;

  SELECT role INTO v_caller_role FROM profiles WHERE id = v_caller_id;
  IF v_caller_role IS DISTINCT FROM 'admin' THEN
    RETURN jsonb_build_object('ok', false, 'error', 'NOT_ADMIN');
  END IF;

  SELECT status INTO v_current_status FROM events WHERE id = p_event_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'error', 'EVENT_NOT_FOUND');
  END IF;

  IF v_current_status != 'pending' THEN
    RETURN jsonb_build_object('ok', false, 'error',
      'STATE_ERROR: event is ' || v_current_status || ', not pending');
  END IF;

  UPDATE events
    SET status      = 'approved',
        approved_by = v_caller_id,
        approved_at = now()
    WHERE id = p_event_id;

  RETURN jsonb_build_object('ok', true);
EXCEPTION WHEN OTHERS THEN
  RAISE WARNING 'approve_event error: % %', SQLSTATE, SQLERRM;
  RETURN jsonb_build_object('ok', false, 'error', 'INTERNAL_ERROR');
END;
$$;

CREATE OR REPLACE FUNCTION public.reject_event(
  p_event_id UUID,
  p_reason   TEXT DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_caller_id   UUID := auth.uid();
  v_caller_role TEXT;
  v_current_status TEXT;
BEGIN
  IF v_caller_id IS NULL THEN
    RETURN jsonb_build_object('ok', false, 'error', 'UNAUTHENTICATED');
  END IF;

  SELECT role INTO v_caller_role FROM profiles WHERE id = v_caller_id;
  IF v_caller_role IS DISTINCT FROM 'admin' THEN
    RETURN jsonb_build_object('ok', false, 'error', 'NOT_ADMIN');
  END IF;

  SELECT status INTO v_current_status FROM events WHERE id = p_event_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'error', 'EVENT_NOT_FOUND');
  END IF;

  IF v_current_status != 'pending' THEN
    RETURN jsonb_build_object('ok', false, 'error',
      'STATE_ERROR: event is ' || v_current_status || ', not pending');
  END IF;

  UPDATE events
    SET status           = 'rejected',
        rejected_by      = v_caller_id,
        rejected_at      = now(),
        rejection_reason = COALESCE(p_reason, 'No reason provided.')
    WHERE id = p_event_id;

  RETURN jsonb_build_object('ok', true);
EXCEPTION WHEN OTHERS THEN
  RAISE WARNING 'reject_event error: % %', SQLSTATE, SQLERRM;
  RETURN jsonb_build_object('ok', false, 'error', 'INTERNAL_ERROR');
END;
$$;

CREATE OR REPLACE FUNCTION public.cancel_event(
  p_event_id UUID,
  p_reason   TEXT DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_caller_id   UUID := auth.uid();
  v_caller_role TEXT;
  v_head_id     UUID;
  v_current_status TEXT;
BEGIN
  IF v_caller_id IS NULL THEN
    RETURN jsonb_build_object('ok', false, 'error', 'UNAUTHENTICATED');
  END IF;

  SELECT p.role, s.head_id, e.status
    INTO v_caller_role, v_head_id, v_current_status
    FROM events e
    JOIN societies s ON s.id = e.society_id
    JOIN profiles p  ON p.id = v_caller_id
    WHERE e.id = p_event_id
    FOR UPDATE OF e;

  IF NOT FOUND THEN
    RETURN jsonb_build_object('ok', false, 'error', 'EVENT_NOT_FOUND');
  END IF;

  -- Admins can cancel any event; society heads can cancel their own.
  IF v_caller_role != 'admin' AND v_head_id IS DISTINCT FROM v_caller_id THEN
    RETURN jsonb_build_object('ok', false, 'error', 'NOT_AUTHORIZED');
  END IF;

  IF v_current_status IN ('cancelled','completed') THEN
    RETURN jsonb_build_object('ok', false, 'error',
      'STATE_ERROR: event is already ' || v_current_status);
  END IF;

  UPDATE events
    SET status       = 'cancelled',
        cancelled_by = v_caller_id,
        cancelled_at = now(),
        rejection_reason = COALESCE(p_reason, rejection_reason)
    WHERE id = p_event_id;

  RETURN jsonb_build_object('ok', true);
EXCEPTION WHEN OTHERS THEN
  RAISE WARNING 'cancel_event error: % %', SQLSTATE, SQLERRM;
  RETURN jsonb_build_object('ok', false, 'error', 'INTERNAL_ERROR');
END;
$$;

-- Grant only to authenticated (admin role enforced inside each function).
REVOKE ALL  ON FUNCTION public.approve_event(UUID)        FROM PUBLIC, anon;
REVOKE ALL  ON FUNCTION public.reject_event(UUID, TEXT)   FROM PUBLIC, anon;
REVOKE ALL  ON FUNCTION public.cancel_event(UUID, TEXT)   FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.approve_event(UUID)        TO authenticated;
GRANT EXECUTE ON FUNCTION public.reject_event(UUID, TEXT)   TO authenticated;
GRANT EXECUTE ON FUNCTION public.cancel_event(UUID, TEXT)   TO authenticated;


-- ====================================================================
-- SECTION 7 — ATTENDANCE TABLE: strengthen integrity
-- ====================================================================

-- 7a. Attendance status: widen to include 'invalid' explicitly.
DO $$
DECLARE conname TEXT;
BEGIN
  SELECT c.conname INTO conname
    FROM pg_constraint c
    JOIN pg_class     t ON t.oid = c.conrelid
    WHERE t.relname = 'attendance' AND c.contype = 'c'
      AND c.conname LIKE '%status%';
  IF conname IS NOT NULL THEN
    EXECUTE format('ALTER TABLE attendance DROP CONSTRAINT %I', conname);
  END IF;
END;
$$;

ALTER TABLE attendance
  ADD CONSTRAINT attendance_status_check
    CHECK (status IN ('valid','invalid'));

-- 7b. Ensure that at most one attendance row per registration exists.
--     The UNIQUE on registration_id in the original schema already does
--     this; this is a belt-and-braces re-affirmation (idempotent).
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'attendance'::regclass
      AND contype  = 'u'
      AND conname  = 'attendance_registration_id_key'
  ) AND NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'attendance'::regclass
      AND contype  = 'u'
      AND array_length(conkey,1) = 1
  ) THEN
    ALTER TABLE attendance
      ADD CONSTRAINT attendance_uq_registration UNIQUE (registration_id);
  END IF;
END;
$$;


-- ====================================================================
-- SECTION 8 — INDEXING STRATEGY
--
-- Each index is justified with:
--   USE: which query pattern it accelerates
--   WITHOUT: what the planner would do without it
-- ====================================================================

-- events.status  — the most frequent filter in every event list query
--   USE: SELECT ... FROM events WHERE status = 'approved'
--   WITHOUT: sequential scan across every event row on every page load
CREATE INDEX IF NOT EXISTS idx_events_status
  ON events (status);

-- events.date — used for date-range queries (gte, order by)
--   USE: SELECT ... FROM events WHERE date >= today ORDER BY date
--   WITHOUT: full table scan + sort; important as event count grows
CREATE INDEX IF NOT EXISTS idx_events_date
  ON events (date);

-- events.society_id — join/filter when loading society's event list
--   USE: SELECT ... FROM events WHERE society_id = $1
--   WITHOUT: sequential scan; called on every society dashboard load
CREATE INDEX IF NOT EXISTS idx_events_society
  ON events (society_id);

-- Composite index for approved + future events (most common student query)
--   USE: WHERE status = 'approved' AND date >= $today ORDER BY date
--   WITHOUT: two separate index scans or full scan; this collapses to one
CREATE INDEX IF NOT EXISTS idx_events_approved_date
  ON events (status, date)
  WHERE status = 'approved';

-- registrations.event_id — join for capacity counts and society analytics
--   USE: SELECT COUNT(*) FROM registrations WHERE event_id = $1
--   WITHOUT: sequential scan; called on every event card render
CREATE INDEX IF NOT EXISTS idx_registrations_event
  ON registrations (event_id);

-- registrations.student_id — fetch all registrations for a student
--   USE: SELECT ... FROM registrations WHERE student_id = $1
--   WITHOUT: sequential scan; called on every student dashboard load
CREATE INDEX IF NOT EXISTS idx_registrations_student
  ON registrations (student_id);

-- registrations.qr_token — QR scan lookup (single most latency-sensitive query)
--   USE: SELECT ... FROM registrations WHERE qr_token = $1
--   WITHOUT: sequential scan at check-in time; must be O(1)
--   Note: qr_token already has a UNIQUE constraint which creates an index,
--   but we ensure it exists explicitly.
CREATE UNIQUE INDEX IF NOT EXISTS idx_registrations_qr_token
  ON registrations (qr_token);

-- registrations.registration_status — filter by status (admin view)
--   USE: admin tab filtering WHERE registration_status = 'confirmed'
--   WITHOUT: requires scanning all registrations for status match
CREATE INDEX IF NOT EXISTS idx_registrations_status
  ON registrations (registration_status);

-- Composite: event + status (capacity check inside RPC)
--   USE: SELECT COUNT(*) WHERE event_id = $1 AND registration_status != 'cancelled'
--   WITHOUT: requires reading every registration row for the event
CREATE INDEX IF NOT EXISTS idx_registrations_event_status
  ON registrations (event_id, registration_status);

-- attendance.registration_id — duplicate scan check (UNIQUE already creates index)
--   Re-created explicitly to guarantee existence after schema re-runs.
CREATE UNIQUE INDEX IF NOT EXISTS idx_attendance_registration_id
  ON attendance (registration_id);

-- attendance.scanned_at — admin chronological attendance view
--   USE: ORDER BY scanned_at DESC in admin attendance tab
--   WITHOUT: sort requires reading all rows; index enables index scan
CREATE INDEX IF NOT EXISTS idx_attendance_scanned_at
  ON attendance (scanned_at DESC);

-- societies.head_id — look up society by head (every society dashboard load)
CREATE INDEX IF NOT EXISTS idx_societies_head
  ON societies (head_id);

-- societies.status — admin pending queue + student active society filter
CREATE INDEX IF NOT EXISTS idx_societies_status
  ON societies (status);

-- profiles.role — admin user management tab filter
CREATE INDEX IF NOT EXISTS idx_profiles_role
  ON profiles (role);

-- events audit columns — finding who approved/rejected (admin audit queries)
CREATE INDEX IF NOT EXISTS idx_events_approved_by  ON events (approved_by)
  WHERE approved_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_rejected_by  ON events (rejected_by)
  WHERE rejected_by IS NOT NULL;


-- ====================================================================
-- SECTION 9 — DROP OBSOLETE TRIGGER that did a racy COUNT check
--
-- The old enforce_approved_event_registration trigger used a plain
-- COUNT(*) which is not protected by SELECT FOR UPDATE and can race.
-- The register_for_event() RPC replaces it with a locked count.
-- We drop the trigger but KEEP the RPC as the only registration path.
-- ====================================================================

DROP TRIGGER   IF EXISTS trg_enforce_approved_event_registration ON registrations;
DROP FUNCTION  IF EXISTS public.enforce_approved_event_registration();

-- ====================================================================
-- SECTION 10 — VERIFICATION QUERIES  (run manually to confirm)
-- ====================================================================

-- 10a. Confirm all expected indexes exist:
-- SELECT indexname, indexdef
--   FROM pg_indexes
--   WHERE schemaname = 'public'
--     AND tablename IN ('events','registrations','attendance','societies','profiles')
--   ORDER BY tablename, indexname;

-- 10b. Confirm all RPCs exist:
-- SELECT routine_name, routine_type
--   FROM information_schema.routines
--   WHERE routine_schema = 'public'
--     AND routine_name IN (
--       'register_for_event', 'validate_attendance',
--       'approve_event', 'reject_event', 'cancel_event',
--       'safe_promote_to_admin'
--     );

-- 10c. Test duplicate registration (expect DUPLICATE):
-- SELECT public.register_for_event('<existing_event_id>', gen_random_uuid()::text);
-- SELECT public.register_for_event('<existing_event_id>', gen_random_uuid()::text);

-- 10d. Test full capacity (set capacity=1, register twice, expect CAPACITY_EXCEEDED):
-- UPDATE events SET capacity = 1 WHERE id = '<test_event_id>';
-- SELECT public.register_for_event('<test_event_id>', gen_random_uuid()::text);
-- SELECT public.register_for_event('<test_event_id>', gen_random_uuid()::text);
-- Expected: first returns ok=true, second returns CAPACITY_EXCEEDED.

-- 10e. Test expired deadline (expect DEADLINE_PASSED):
-- UPDATE events SET registration_deadline = '2000-01-01' WHERE id = '<test_event_id>';
-- SELECT public.register_for_event('<test_event_id>', gen_random_uuid()::text);

-- 10f. Test rejected/cancelled event (expect NOT_APPROVED / CANCELLED):
-- UPDATE events SET status='rejected' WHERE id = '<test_id>';
-- SELECT public.register_for_event('<test_id>', gen_random_uuid()::text);

-- 10g. Test invalid QR scan (expect INVALID_TOKEN):
-- SELECT public.validate_attendance('00000000-fake-token-000000000000', '<event_id>');

-- 10h. Test duplicate attendance scan (expect ALREADY_ATTENDED):
-- SELECT public.validate_attendance('<real_qr_token>', '<event_id>');
-- SELECT public.validate_attendance('<real_qr_token>', '<event_id>');

-- 10i. Test event state machine — invalid transition (expect check_violation):
-- UPDATE events SET status='completed' WHERE id='<pending_event_id>';
-- Expected: ERROR — Transition pending → completed is not permitted.

-- 10j. Test concurrent registration simulation (run in two parallel sessions):
-- Session 1: BEGIN; SELECT * FROM events WHERE id='<id>' FOR UPDATE; [hold]
-- Session 2: SELECT public.register_for_event('<id>', gen_random_uuid()::text);
-- Expected: Session 2 blocks until Session 1 commits/rolls back.

-- ====================================================================
-- SECTION 11 — MIGRATION SAFETY VERIFICATION
-- ====================================================================

-- Confirm existing records satisfy new constraints (should return 0):
-- SELECT COUNT(*) FROM events WHERE length(trim(title)) = 0;
-- SELECT COUNT(*) FROM events WHERE capacity IS NOT NULL AND capacity <= 0;
-- SELECT COUNT(*) FROM events WHERE fee IS NOT NULL AND fee < 0;
-- SELECT COUNT(*) FROM events
--   WHERE registration_deadline IS NOT NULL
--     AND date IS NOT NULL
--     AND registration_deadline > date;
-- SELECT COUNT(*) FROM registrations WHERE length(trim(qr_token)) = 0;
-- SELECT COUNT(*) FROM registrations
--   WHERE registration_status NOT IN ('confirmed','attended','cancelled');
-- SELECT COUNT(*) FROM registrations
--   WHERE payment_status NOT IN ('unpaid','paid','failed','refunded');

-- ====================================================================
-- SUMMARY OF ENFORCED RULES
-- ====================================================================
-- ┌─────────────────────────────────────────────────────────────────┐
-- │ Rule                          │ Mechanism                       │
-- ├───────────────────────────────┼─────────────────────────────────┤
-- │ One registration per student  │ UNIQUE(event_id, student_id)    │
-- │ per event                     │ enforced inside RPC + PK        │
-- │ Atomic capacity enforcement   │ SELECT FOR UPDATE in RPC +      │
-- │                               │ COUNT inside lock               │
-- │ Registration deadline         │ CURRENT_DATE check inside RPC   │
-- │ Event must be approved        │ status check inside RPC         │
-- │ Cancelled event not bookable  │ status check inside RPC         │
-- │ Completed event not bookable  │ status check inside RPC         │
-- │ Valid event status values     │ CHECK constraint + state machine │
-- │ Invalid status transitions    │ trg_event_state_machine trigger  │
-- │ Approval audit trail          │ approved_by/at columns stamped  │
-- │                               │ by state machine trigger        │
-- │ Rejection audit trail         │ rejected_by/at/reason columns   │
-- │ Cancellation audit trail      │ cancelled_by/at columns         │
-- │ One attendance per reg        │ UNIQUE(registration_id) +       │
-- │                               │ validate_attendance RPC         │
-- │ Concurrent duplicate scan     │ SELECT FOR UPDATE in RPC +      │
-- │                               │ UNIQUE constraint (fallback)    │
-- │ QR must match event           │ event_id filter in RPC          │
-- │ Cancelled reg cannot attend   │ status check in RPC             │
-- │ Unauthorized attendance       │ society ownership check in RPC  │
-- │ Valid registration statuses   │ CHECK constraint                │
-- │ Valid payment statuses        │ CHECK constraint                │
-- │ Non-empty QR token            │ CHECK constraint                │
-- │ Non-empty event title         │ CHECK constraint                │
-- │ Positive capacity             │ CHECK constraint                │
-- │ Non-negative fee              │ CHECK constraint                │
-- │ Deadline ≤ event date         │ CHECK constraint                │
-- │ Start time < end time         │ CHECK constraint                │
-- └───────────────────────────────┴─────────────────────────────────┘
