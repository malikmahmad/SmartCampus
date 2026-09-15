"""
utils/registration.py — Student event registration logic.

Architecture
------------
Registration is performed exclusively through the register_for_event()
PostgreSQL RPC, never via a direct INSERT.

Why the RPC instead of a direct INSERT
---------------------------------------
A direct INSERT from the application layer suffers from a TOCTOU race:
  1. App reads current registration count → 49 / 50
  2. Concurrent request also reads 49 / 50
  3. Both pass the capacity check
  4. Both INSERT → count becomes 51 (over capacity)

The register_for_event() RPC uses SELECT … FOR UPDATE to lock the event
row.  All concurrent calls for the same event are serialised at the DB
level.  Exactly one succeeds when the last seat is taken; all others
receive CAPACITY_EXCEEDED from within the same transaction.

Error codes returned by the RPC
---------------------------------
  DUPLICATE          — student already registered for this event
  CAPACITY_EXCEEDED  — event is fully booked
  DEADLINE_PASSED    — registration deadline has passed
  NOT_APPROVED       — event is not yet approved
  CANCELLED          — event has been cancelled
  COMPLETED          — event has already taken place
  EVENT_NOT_FOUND    — p_event_id does not exist
  QR_COLLISION       — UUID4 collision (astronomically rare; caller should retry)
  UNAUTHENTICATED    — auth.uid() is NULL (session expired)
  INTERNAL_ERROR     — unexpected DB error (logged server-side)

Security notes
--------------
- student_id is resolved inside the RPC from auth.uid(); the application
  never passes a student_id parameter.
- DB exception text is never surfaced verbatim to users.
- Python pre-flight checks are kept for fast UX feedback only; the RPC
  is the authoritative enforcement layer.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date

import streamlit as st
from supabase import Client

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RPC error code → user-facing message
# ---------------------------------------------------------------------------
_RPC_MESSAGES: dict[str, str] = {
    "DUPLICATE":           "You are already registered for this event.",
    "CAPACITY_EXCEEDED":   "This event has reached full capacity.",
    "DEADLINE_PASSED":     "Registration is closed — the deadline has passed.",
    "NOT_APPROVED":        "This event is not yet open for registration.",
    "CANCELLED":           "This event has been cancelled.",
    "COMPLETED":           "This event has already taken place.",
    "EVENT_NOT_FOUND":     "Event not found. Please refresh and try again.",
    "QR_COLLISION":        "A temporary error occurred. Please try again.",
    "UNAUTHENTICATED":     "Your session has expired. Please sign in again.",
    "INTERNAL_ERROR":      "Registration failed due to a server error. Please try again.",
    "UNPAID_REGISTRATION": "This is a paid event. Please complete payment simulation before entry.",
    "EVENT_EXPIRED":       "Registration or check-in is not permitted for completed or past events.",
}

# These are also raised by old triggers still in flight during migration;
# keep them for belt-and-braces.
_LEGACY_MESSAGES: dict[str, str] = {
    "REGISTRATION_CLOSED": "Registration is not currently open for this event.",
    "CAPACITY_EXCEEDED":   "This event has reached full capacity.",
    "DUPLICATE_SCAN":      "You are already registered for this event.",
}


def _map_rpc_error(raw_error: str) -> str:
    """Return a safe, user-facing message for an RPC error code."""
    code = raw_error.strip()
    # Strip any suffix like "STATE_ERROR: event is rejected, not pending"
    base_code = code.split(":")[0].strip()
    if base_code in _RPC_MESSAGES:
        return _RPC_MESSAGES[base_code]
    for legacy_key, msg in _LEGACY_MESSAGES.items():
        if legacy_key in code:
            return msg
    logger.error("Unknown RPC error code (not surfaced to user): %r", raw_error)
    return "Registration failed. Please try again."


def _map_exception_error(exc: Exception) -> str:
    """
    Fallback for unexpected exceptions (network errors, malformed responses).
    Never exposes SQL internals.
    """
    msg = str(exc).lower()
    raw = str(exc)
    if "uq_registration_student_event" in raw or ("unique" in msg and "registration" in msg):
        return _RPC_MESSAGES["DUPLICATE"]
    if "CAPACITY_EXCEEDED" in raw:
        return _RPC_MESSAGES["CAPACITY_EXCEEDED"]
    if "REGISTRATION_CLOSED" in raw or "deadline" in msg:
        return _RPC_MESSAGES["DEADLINE_PASSED"]
    if "permission denied" in msg or "insufficient_privilege" in msg:
        return "You do not have permission to register for this event."
    logger.error("Registration exception (not surfaced to user): %s", exc)
    return "Registration failed. Please try again."


# Alias required by security tests
_safe_registration_error = _map_exception_error


# ---------------------------------------------------------------------------
# Public registration function
# ---------------------------------------------------------------------------

def register_student(
    supabase: Client,
    student_id: str,
    event: dict,
    already_registered: list[str],
) -> None:
    """
    Register the authenticated student for an event.

    Calls the register_for_event() PostgreSQL RPC which enforces:
      • Atomic capacity enforcement (SELECT FOR UPDATE)
      • Registration deadline
      • Event must be approved (not pending/rejected/cancelled/completed)
      • Duplicate prevention (UNIQUE constraint, checked inside lock)
      • QR token uniqueness

    Parameters
    ----------
    supabase          : Authenticated Supabase client (carries student JWT).
    student_id        : Verified UUID from st.session_state.user.id.
                        NEVER from user input — the RPC uses auth.uid().
    event             : Full event dict from the DB query (for UX pre-checks).
    already_registered: List of event UUIDs already registered (UX only).
    """
    event_id = event["id"]
    today    = date.today()

    # ── Pre-flight checks (UX speed — not the security boundary) ────────────

    # 1. Fast duplicate check using local state.
    if event_id in already_registered:
        st.warning(_RPC_MESSAGES["DUPLICATE"])
        return

    # 2. Client-side deadline check for immediate feedback.
    deadline_str = event.get("registration_deadline")
    if deadline_str:
        try:
            if date.fromisoformat(str(deadline_str)) < today:
                st.error(_RPC_MESSAGES["DEADLINE_PASSED"])
                return
        except (ValueError, TypeError):
            pass  # RPC enforces; don't block on a parse error.

    # 3. Client-side capacity check for immediate feedback (exclude cancelled).
    capacity = event.get("capacity")
    if capacity:
        try:
            count_res = (
                supabase.table("registrations")
                .select("id", count="exact")
                .eq("event_id", event_id)
                .neq("registration_status", "cancelled")
                .execute()
            )
            if (count_res.count or 0) >= capacity:
                st.error(_RPC_MESSAGES["CAPACITY_EXCEEDED"])
                return
        except Exception:
            pass  # RPC is authoritative; proceed and let it decide.

    # ── Call the atomic RPC ───────────────────────────────────────────────────
    qr_token = str(uuid.uuid4())

    try:
        rpc_res = supabase.rpc(
            "register_for_event",
            {
                "p_event_id": event_id,
                "p_qr_token": qr_token,
            },
        ).execute()
    except Exception as exc:
        st.error(_map_exception_error(exc))
        return

    # ── Interpret RPC response ────────────────────────────────────────────────
    result = rpc_res.data
    if not isinstance(result, dict):
        logger.error("register_for_event returned unexpected type: %r", result)
        st.error("Registration failed. Please try again.")
        return

    if result.get("ok"):
        st.success("🎉 Registration Confirmed! Your pass is ready in 'My Digital Passes'.")
        st.rerun()
    else:
        error_code = result.get("error", "INTERNAL_ERROR")
        if error_code == "QR_COLLISION":
            # Retry once with a fresh UUID (astronomically rare).
            return register_student(supabase, student_id, event, already_registered)
        st.error(_map_rpc_error(error_code))
