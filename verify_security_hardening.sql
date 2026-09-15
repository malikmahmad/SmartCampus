-- ============================================================================
-- SECURITY HARDENING VERIFICATION SCRIPT
-- ============================================================================
-- Purpose: Verify RPC-based event approval/rejection with audit logging
-- Run this in Supabase SQL Editor AFTER migration
-- ============================================================================

-- ┌────────────────────────────────────────────────────────────────────────┐
-- │ SECTION 1: Verify Schema Changes                                       │
-- └────────────────────────────────────────────────────────────────────────┘

-- Check audit fields exist in events table
SELECT 
  column_name,
  data_type,
  is_nullable
FROM information_schema.columns 
WHERE table_schema = 'public'
  AND table_name = 'events' 
  AND column_name IN (
    'approved_by', 'approved_at', 
    'rejected_by', 'rejected_at', 'rejection_reason',
    'cancelled_by', 'cancelled_at'
  )
ORDER BY column_name;

-- Expected: 7 rows showing all audit columns

-- ┌────────────────────────────────────────────────────────────────────────┐
-- │ SECTION 2: Verify RPC Functions                                        │
-- └────────────────────────────────────────────────────────────────────────┘

-- Check RPC functions exist
SELECT 
  routine_name,
  routine_type,
  data_type as return_type
FROM information_schema.routines
WHERE routine_schema = 'public'
  AND routine_name IN ('approve_event', 'reject_event', 'cancel_event')
ORDER BY routine_name;

-- Expected: 3 rows (approve_event, reject_event, cancel_event)

-- ┌────────────────────────────────────────────────────────────────────────┐
-- │ SECTION 3: Verify Function Permissions                                 │
-- └────────────────────────────────────────────────────────────────────────┘

-- Check grants on RPC functions
SELECT 
  routine_name,
  grantee,
  privilege_type
FROM information_schema.routine_privileges
WHERE routine_schema = 'public'
  AND routine_name IN ('approve_event', 'reject_event', 'cancel_event')
ORDER BY routine_name, grantee;

-- Expected: EXECUTE privilege for 'authenticated' role only

-- ┌────────────────────────────────────────────────────────────────────────┐
-- │ SECTION 4: Verify Indexes                                              │
-- └────────────────────────────────────────────────────────────────────────┘

-- Check audit field indexes exist
SELECT 
  indexname,
  indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename = 'events'
  AND indexname LIKE '%approved%' OR indexname LIKE '%rejected%'
ORDER BY indexname;

-- Expected: idx_events_approved_by, idx_events_rejected_by

-- ┌────────────────────────────────────────────────────────────────────────┐
-- │ SECTION 5: Test RPC Functions (Non-Destructive)                        │
-- └────────────────────────────────────────────────────────────────────────┘

-- Test 1: Call approve_event with non-existent event ID
SELECT public.approve_event('00000000-0000-0000-0000-000000000000'::uuid) as result;
-- Expected: {"ok": false, "error": "EVENT_NOT_FOUND"} or {"ok": false, "error": "UNAUTHENTICATED"}

-- Test 2: Call reject_event with non-existent event ID
SELECT public.reject_event(
  '00000000-0000-0000-0000-000000000000'::uuid,
  'Test rejection reason'
) as result;
-- Expected: {"ok": false, "error": "EVENT_NOT_FOUND"} or {"ok": false, "error": "UNAUTHENTICATED"}

-- ┌────────────────────────────────────────────────────────────────────────┐
-- │ SECTION 6: Audit Trail Sample Queries                                  │
-- └────────────────────────────────────────────────────────────────────────┘

-- Query 1: Count events with audit trail
SELECT 
  COUNT(*) FILTER (WHERE approved_at IS NOT NULL) as approved_count,
  COUNT(*) FILTER (WHERE rejected_at IS NOT NULL) as rejected_count,
  COUNT(*) FILTER (WHERE cancelled_at IS NOT NULL) as cancelled_count
FROM events;

-- Query 2: Recent approvals with admin info
SELECT 
  e.title,
  e.status,
  p.email as approved_by_email,
  e.approved_at
FROM events e
LEFT JOIN profiles p ON p.id = e.approved_by
WHERE e.approved_at IS NOT NULL
ORDER BY e.approved_at DESC
LIMIT 10;

-- Query 3: Recent rejections with reasons
SELECT 
  e.title,
  e.status,
  p.email as rejected_by_email,
  e.rejected_at,
  e.rejection_reason
FROM events e
LEFT JOIN profiles p ON p.id = e.rejected_by
WHERE e.rejected_at IS NOT NULL
ORDER BY e.rejected_at DESC
LIMIT 10;

-- Query 4: Admin activity summary
SELECT 
  p.email,
  p.role,
  COUNT(DISTINCT e1.id) as approvals_count,
  COUNT(DISTINCT e2.id) as rejections_count,
  COUNT(DISTINCT e3.id) as cancellations_count
FROM profiles p
LEFT JOIN events e1 ON e1.approved_by = p.id
LEFT JOIN events e2 ON e2.rejected_by = p.id
LEFT JOIN events e3 ON e3.cancelled_by = p.id
WHERE p.role = 'admin'
GROUP BY p.id, p.email, p.role
ORDER BY (
  COUNT(DISTINCT e1.id) + 
  COUNT(DISTINCT e2.id) + 
  COUNT(DISTINCT e3.id)
) DESC;

-- ┌────────────────────────────────────────────────────────────────────────┐
-- │ SECTION 7: Security Verification                                        │
-- └────────────────────────────────────────────────────────────────────────┘

-- Check RLS is enabled on events table
SELECT 
  schemaname,
  tablename,
  rowsecurity as rls_enabled
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename = 'events';

-- Expected: rls_enabled = true

-- List all RLS policies on events table
SELECT 
  policyname,
  permissive,
  roles,
  cmd,
  qual,
  with_check
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename = 'events'
ORDER BY policyname;

-- Expected: Multiple policies including events_update_admin

-- ┌────────────────────────────────────────────────────────────────────────┐
-- │ SECTION 8: Data Integrity Checks                                       │
-- └────────────────────────────────────────────────────────────────────────┘

-- Check for orphaned audit references (should be none)
SELECT 
  'Orphaned approved_by' as issue_type,
  COUNT(*) as count
FROM events e
WHERE e.approved_by IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM profiles p WHERE p.id = e.approved_by)
UNION ALL
SELECT 
  'Orphaned rejected_by' as issue_type,
  COUNT(*) as count
FROM events e
WHERE e.rejected_by IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM profiles p WHERE p.id = e.rejected_by);

-- Expected: All counts = 0

-- Check for invalid audit states
SELECT 
  id,
  title,
  status,
  CASE 
    WHEN status = 'approved' AND approved_by IS NULL THEN 'Missing approved_by'
    WHEN status = 'approved' AND approved_at IS NULL THEN 'Missing approved_at'
    WHEN status = 'rejected' AND rejected_by IS NULL THEN 'Missing rejected_by'
    WHEN status = 'rejected' AND rejected_at IS NULL THEN 'Missing rejected_at'
    WHEN status NOT IN ('approved', 'rejected') AND approved_by IS NOT NULL THEN 'Unexpected approved_by'
    WHEN status NOT IN ('approved', 'rejected') AND rejected_by IS NOT NULL THEN 'Unexpected rejected_by'
    ELSE 'OK'
  END as audit_status
FROM events
WHERE CASE 
  WHEN status = 'approved' AND approved_by IS NULL THEN true
  WHEN status = 'approved' AND approved_at IS NULL THEN true
  WHEN status = 'rejected' AND rejected_by IS NULL THEN true
  WHEN status = 'rejected' AND rejected_at IS NULL THEN true
  WHEN status NOT IN ('approved', 'rejected') AND approved_by IS NOT NULL THEN true
  WHEN status NOT IN ('approved', 'rejected') AND rejected_by IS NOT NULL THEN true
  ELSE false
END;

-- Expected: No rows (all audit states are valid)

-- ============================================================================
-- VERIFICATION SUMMARY
-- ============================================================================
-- ✅ All checks passed = Security hardening is complete and correct
-- ❌ Any check failed = Review migration and retry
-- ============================================================================

-- Quick health check (run this last)
SELECT 
  'Schema Audit Fields' as component,
  CASE WHEN COUNT(*) = 7 THEN '✅ PASS' ELSE '❌ FAIL' END as status
FROM information_schema.columns 
WHERE table_name = 'events' 
  AND column_name IN ('approved_by', 'approved_at', 'rejected_by', 'rejected_at', 'rejection_reason', 'cancelled_by', 'cancelled_at')
UNION ALL
SELECT 
  'RPC Functions' as component,
  CASE WHEN COUNT(*) >= 2 THEN '✅ PASS' ELSE '❌ FAIL' END as status
FROM information_schema.routines
WHERE routine_name IN ('approve_event', 'reject_event')
UNION ALL
SELECT 
  'RLS Enabled' as component,
  CASE WHEN rowsecurity THEN '✅ PASS' ELSE '❌ FAIL' END as status
FROM pg_tables
WHERE tablename = 'events'
UNION ALL
SELECT 
  'Audit Indexes' as component,
  CASE WHEN COUNT(*) >= 2 THEN '✅ PASS' ELSE '❌ FAIL' END as status
FROM pg_indexes
WHERE tablename = 'events'
  AND (indexname LIKE '%approved%' OR indexname LIKE '%rejected%');

-- Expected: All rows show ✅ PASS
