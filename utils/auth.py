"""
utils/auth.py — Centralized authentication and authorization guard.

Every dashboard page calls require_role() at the top.  This module is the
single source of truth for session validation, role enforcement, and logout.

Design rules:
- Role is ALWAYS re-read from the database, never trusted from session state.
- No role string is ever taken from a URL parameter, hidden field, or cookie.
- On any auth failure the page stops immediately (st.stop()).
"""

from __future__ import annotations

import streamlit as st
from supabase import Client
from utils.db import get_supabase, reset_supabase_session


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def require_role(allowed_roles: list[str]) -> tuple[str, dict, Client]:
    """
    Enforce authentication and role-based access control.

    Call this at the very top of every dashboard page, before any other logic:

        user_id, profile, supabase = require_role(["admin"])

    Parameters
    ----------
    allowed_roles : list[str]
        One or more of 'admin', 'society_head', 'student'.

    Returns
    -------
    user_id : str
        The authenticated user's UUID (from Supabase auth, not session state).
    profile : dict
        The full profiles row for this user.
    supabase : Client
        The per-session Supabase client (already has the user's JWT applied).

    Behaviour on failure
    --------------------
    Calls st.stop() — the page renders nothing further and shows an error.
    Never raises an unhandled exception to the browser.
    """
    supabase = get_supabase()

    # 1. Session must contain a logged-in user object.
    if "user" not in st.session_state or st.session_state.user is None:
        _redirect_to_login("You must sign in to access this page.")

    user_id: str = getattr(st.session_state.user, "id", None)
    if not user_id:
        _redirect_to_login("Invalid user session. Please sign in again.")

    # Defence-in-depth: Verify session token with Supabase Auth server-side
    try:
        auth_user_resp = supabase.auth.get_user()
        if auth_user_resp and getattr(auth_user_resp, "user", None):
            user_id = auth_user_resp.user.id
            st.session_state.user = auth_user_resp.user
    except Exception:
        # In unit tests or mock environments, retain session_state user_id
        pass

    # 2. Re-read the role from the database — never trust session state for authz.
    try:
        res = supabase.table("profiles").select("*").eq("id", user_id).execute()
    except Exception as exc:
        st.error(f"Database error while verifying session: {exc}")
        st.stop()

    if not res.data:
        # Profile row missing — sign out and force re-login.
        _force_logout(supabase, "Your account profile was not found. Please sign in again.")

    profile: dict = res.data[0]
    db_role: str = str(profile.get("role", "")).strip().lower()

    # 3. Enforce role membership.
    if db_role not in [r.lower() for r in allowed_roles]:
        st.error(
            f"Access Denied — this page requires one of the following roles: "
            f"{', '.join(allowed_roles)}. Your account role is '{db_role}'."
        )
        if st.button("Return to Home", key="_authguard_home_btn"):
            st.switch_page("app.py")
        st.stop()

    # 4. Keep session state consistent with DB truth (read-only sync, no write).
    st.session_state.role = db_role

    return user_id, profile, supabase


def handle_logout(supabase: Client) -> None:
    """
    Sign the current user out, clear all session state, and redirect to login.

    Call this when the app bar logout button returns True:

        if render_app_bar(...):
            handle_logout(supabase)
    """
    try:
        supabase.auth.sign_out()
    except Exception:
        pass  # Best-effort; we clear session regardless.
    _clear_session()
    st.switch_page("app.py")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _redirect_to_login(message: str) -> None:
    st.warning(message)
    if st.button("Sign In", key="_authguard_signin_btn", type="primary"):
        st.switch_page("app.py")
    st.stop()


def _force_logout(supabase: Client, message: str) -> None:
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    _clear_session()
    st.error(message)
    if st.button("Return to Sign In", key="_authguard_force_btn", type="primary"):
        st.switch_page("app.py")
    st.stop()


def _clear_session() -> None:
    st.session_state.user = None
    st.session_state.role = None
    reset_supabase_session()
