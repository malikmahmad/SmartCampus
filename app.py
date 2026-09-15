"""
app.py — CampusPulse landing page and authentication entry point.

Security architecture
---------------------
Role assignment
  - The DB trigger handle_new_user() is the SOLE authority for assigning
    the initial role.  The trigger whitelists only 'student' and
    'society_head' from user-supplied metadata; anything else becomes
    'student'.
  - The Python sign-up handler does NOT write a role into the profiles
    table after sign-up.  It calls upsert with only non-sensitive fields
    (id, email, name) and explicitly omits 'role', so the trigger value
    is preserved.
  - Admin promotion goes through the safe_promote_to_admin() DB function
    which reads the shared secret from pg_settings — never from Python.

Session safety
  - Role is re-read from the database on every dashboard load via
    require_role() in utils/auth.py.
  - st.session_state.user holds the Supabase auth object (JWT-backed).
  - Logout calls supabase.auth.sign_out() to invalidate the server-side
    session, then clears all local session state.

Secret handling
  - No secrets are hardcoded.  Missing SUPABASE_URL or SUPABASE_KEY
    causes a clean st.stop() via utils/db.py.
  - GEMINI_API_KEY absence is handled gracefully in utils/ai_recs.py.
  - The admin promotion secret lives exclusively in pg_settings on the
    DB server; it is never in Python or environment variables.
"""

import html
import streamlit as st
from utils.db import get_supabase, reset_supabase_session
from utils.ui import apply_custom_theme, render_html
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="CampusPulse · Smart Campus OS",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ---------------------------------------------------------------------------
# Session redirect — already logged in
# ---------------------------------------------------------------------------
def _redirect_by_role(supabase, user_id: str) -> None:
    """Read role from DB and switch to the correct dashboard."""
    try:
        res = supabase.table("profiles").select("role").eq("id", user_id).execute()
    except Exception as exc:
        st.error(f"Could not load your profile: {exc}")
        if st.button("Reset Session"):
            st.session_state.user = None
            reset_supabase_session()
            st.rerun()
        st.stop()

    if not res.data:
        # Profile missing — auth state is inconsistent; force logout.
        st.session_state.user = None
        reset_supabase_session()
        st.rerun()
        return

    role = str(res.data[0].get("role", "student")).strip().lower()
    st.session_state.role = role

    if role == "admin":
        st.switch_page("pages/1_Admin_Dashboard.py")
    elif role == "society_head":
        st.switch_page("pages/2_Society_Dashboard.py")
    else:
        st.switch_page("pages/3_Student_Dashboard.py")


# ---------------------------------------------------------------------------
# Sign-in handler
# ---------------------------------------------------------------------------
def _do_login(supabase, email: str, password: str) -> None:
    if not email.strip() or not password.strip():
        st.error("Please enter both email and password.")
        return
    try:
        res = supabase.auth.sign_in_with_password(
            {"email": email.strip(), "password": password.strip()}
        )
        st.session_state.user = res.user
        st.success("Authentication successful! Redirecting…")
        st.rerun()
    except Exception as exc:
        # Avoid leaking internal error details verbatim.
        msg = str(exc)
        if "Invalid login credentials" in msg or "invalid_credentials" in msg:
            st.error("Invalid email or password.")
        else:
            st.error("Sign-in failed. Please try again.")


# ---------------------------------------------------------------------------
# Sign-up handler  (NO admin role from this form — see security note above)
# ---------------------------------------------------------------------------
def _do_signup(supabase, name: str, email: str, password: str, role_label: str) -> None:
    """
    Creates a student or society_head account.
    Admin accounts are provisioned separately via _do_admin_promote().

    Role security
    -------------
    The 'role' value passed to Supabase Auth metadata is consumed by the
    handle_new_user() SECURITY DEFINER trigger, which whitelists only
    'student' and 'society_head'.  Any other value is silently coerced
    to 'student' by the trigger.

    The subsequent upsert DELIBERATELY OMITS the 'role' field so that the
    trigger-assigned value is never overwritten by Python.  This closes
    the SEC-H2 bypass identified in the forensic audit.
    """
    if not name.strip():
        st.error("Please enter your full name.")
        return
    if not email.strip() or "@" not in email:
        st.error("Please provide a valid email address.")
        return
    if len(password) < 6:
        st.error("Password must be at least 6 characters.")
        return

    # Whitelist — only these two values are sent to the trigger.
    # 'admin' is excluded here AND in the trigger; there is no path
    # through this form that produces an admin account.
    allowed_roles = {"Student": "student", "Society Head": "society_head"}
    role = allowed_roles.get(role_label, "student")

    try:
        res = supabase.auth.sign_up(
            {
                "email": email.strip(),
                "password": password.strip(),
                "options": {
                    "data": {
                        "name": name.strip(),
                        # Trigger reads this value and whitelists it.
                        "role": role,
                    }
                },
            }
        )
        user = getattr(res, "user", None)
        if user:
            # Upsert only non-sensitive identity fields.
            # The trigger handle_new_user() has already set the correct
            # role value. We deliberately do not include that column here.
            supabase.table("profiles").upsert(
                {
                    "id":    user.id,
                    "email": email.strip(),
                    "name":  name.strip(),
                },
                on_conflict="id",
            ).execute()
            st.success("Account created! You can now sign in.")
        else:
            # Supabase email confirmation enabled — user object may be None.
            st.success(
                "Account created! Check your email to confirm your address, "
                "then sign in."
            )
    except Exception as exc:
        msg = str(exc)
        if "already registered" in msg.lower() or "already exists" in msg.lower():
            st.error("An account with this email already exists.")
        else:
            st.error("Registration failed. Please try again.")


# ---------------------------------------------------------------------------
# Admin promotion handler
# ---------------------------------------------------------------------------
def _do_admin_promote(supabase, email: str, password: str, secret_key: str) -> None:
    """
    Two-step admin provisioning:
      1. Authenticate to obtain a verified user UUID.
      2. Call the DB RPC which validates the key inside Postgres and
         sets role='admin' only if the key matches pg_settings.

    Security constraints
    --------------------
    - The Python layer never compares the secret key.
    - The RPC is a SECURITY DEFINER function owned by postgres.
    - REVOKE ALL has been issued against PUBLIC, anon, authenticated,
      and service_role in supabase_security_hardening.sql.
    - If PostgREST honours the REVOKE (verified behaviour in Supabase
      ≥2.x), calling this RPC via the anon-key client returns HTTP 403.
      The UI call will therefore raise an exception which we catch below.
    - If the REVOKE is not honoured (older PostgREST), the function still
      validates the key against pg_settings before writing anything.
    - In both cases, a missing or wrong key produces no privilege change.

    NOTE: For a fully zero-trust deployment, replace this RPC call with
    a Supabase Edge Function that uses the service-role key server-side
    and is protected by its own auth header.  The current approach is
    acceptable for a hackathon MVP where the Supabase project is private.
    """
    if "admin_promo_attempts" not in st.session_state:
        st.session_state.admin_promo_attempts = 0

    if st.session_state.admin_promo_attempts >= 3:
        st.error("Too many failed administrator authorization attempts. This access point is locked for this session.")
        return

    if not email.strip() or not password.strip():
        st.error("Email and password are required.")
        return
    if not secret_key.strip():
        st.error("Administrator authorization key is required.")
        return

    # Step 1 — authenticate to get the verified UUID.
    try:
        auth_res = supabase.auth.sign_in_with_password(
            {"email": email.strip(), "password": password.strip()}
        )
        user = auth_res.user
    except Exception:
        st.session_state.admin_promo_attempts += 1
        st.error("Invalid email or password.")
        return

    # Step 2 — call the DB function to validate key and promote.
    try:
        rpc_res = supabase.rpc(
            "safe_promote_to_admin",
            {"target_user_id": user.id, "provided_key": secret_key.strip()},
        ).execute()
        granted: bool = bool(rpc_res.data)
    except Exception as exc:
        err = str(exc)
        st.session_state.admin_promo_attempts += 1
        if "permission denied" in err.lower() or "403" in err or "insufficient_privilege" in err.lower():
            # RPC correctly blocked by REVOKE — expected in production.
            st.error(
                "Administrator promotion is not available through this interface. "
                "Contact your database administrator to provision admin accounts "
                "directly via the Supabase dashboard or a server-side script."
            )
        else:
            st.error(
                "Administrator promotion failed. Ensure 'app.admin_secret_key' "
                "is configured in your Supabase database settings."
            )
        return

    if granted:
        st.session_state.admin_promo_attempts = 0
        st.session_state.user = user
        st.success("Administrator access granted! Redirecting…")
        st.rerun()
    else:
        st.session_state.admin_promo_attempts += 1
        remaining = max(0, 3 - st.session_state.admin_promo_attempts)
        st.error(f"Invalid authorization key. Administrator access denied. ({remaining} attempts remaining)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    apply_custom_theme()
    supabase = get_supabase()

    if "user" not in st.session_state:
        st.session_state.user = None

    if st.session_state.user is not None:
        _redirect_by_role(supabase, st.session_state.user.id)
        return

    # ── Split-screen landing ────────────────────────────────────────────────
    col_hero, col_spacer, col_auth = st.columns([6, 0.5, 5])

    with col_hero:
        render_html("""
        <div style="padding-top: 1rem; animation: fadeInUp 0.6s ease both;">
            <div style="display: inline-flex; align-items: center; gap: 0.5rem;
                        background: rgba(129,140,248,0.1);
                        border: 1px solid rgba(129,140,248,0.2);
                        padding: 0.35rem 0.9rem; border-radius: 999px; margin-bottom: 1.75rem;">
                <span style="display:inline-block;width:7px;height:7px;border-radius:50%;
                             background:#818cf8;box-shadow:0 0 8px #818cf8;"></span>
                <span style="font-size:0.725rem;font-weight:700;color:#818cf8;
                             text-transform:uppercase;letter-spacing:0.08em;">Campus Event OS</span>
            </div>
            <h1 style="font-size:2.85rem;font-weight:800;color:#f1f5f9;
                       line-height:1.15;letter-spacing:-0.04em;margin:0 0 1.25rem 0;">
                The central<br>
                <span style="background:linear-gradient(135deg,#667eea,#764ba2,#22d3ee);
                             -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                             background-clip:text;">operating system</span><br>
                for university life.
            </h1>
            <p style="font-size:1.05rem;color:#94a3b8;line-height:1.7;
                      margin-bottom:2rem;max-width:520px;">
                Discover verified campus societies, book real-time event passes with secure
                QR tokens, and get personalised AI recommendations.
            </p>
            <div style="display:flex;flex-direction:column;gap:0.85rem;margin-bottom:2rem;">
                <div class="glass-card" style="padding:1rem 1.25rem;margin-bottom:0;">
                    <div style="display:flex;align-items:center;gap:0.85rem;">
                        <div style="width:42px;height:42px;border-radius:12px;
                                    background:rgba(129,140,248,0.12);
                                    border:1px solid rgba(129,140,248,0.2);
                                    color:#818cf8;display:flex;align-items:center;
                                    justify-content:center;font-size:1.15rem;flex-shrink:0;">🏛️</div>
                        <div>
                            <div style="font-size:0.9rem;font-weight:700;color:#f1f5f9;
                                        margin-bottom:0.15rem;">Verified Society Governance</div>
                            <div style="font-size:0.8rem;color:#64748b;line-height:1.4;">
                                Official approval pipelines and admin moderation for campus organizations.</div>
                        </div>
                    </div>
                </div>
                <div class="glass-card" style="padding:1rem 1.25rem;margin-bottom:0;">
                    <div style="display:flex;align-items:center;gap:0.85rem;">
                        <div style="width:42px;height:42px;border-radius:12px;
                                    background:rgba(52,211,153,0.12);
                                    border:1px solid rgba(52,211,153,0.2);
                                    color:#34d399;display:flex;align-items:center;
                                    justify-content:center;font-size:1.15rem;flex-shrink:0;">🎫</div>
                        <div>
                            <div style="font-size:0.9rem;font-weight:700;color:#f1f5f9;
                                        margin-bottom:0.15rem;">Digital QR Event Passes</div>
                            <div style="font-size:0.8rem;color:#64748b;line-height:1.4;">
                                Instant QR ticket generation with capacity enforcement and
                                duplicate-proof check-ins.</div>
                        </div>
                    </div>
                </div>
                <div class="glass-card" style="padding:1rem 1.25rem;margin-bottom:0;">
                    <div style="display:flex;align-items:center;gap:0.85rem;">
                        <div style="width:42px;height:42px;border-radius:12px;
                                    background:rgba(167,139,250,0.12);
                                    border:1px solid rgba(167,139,250,0.2);
                                    color:#a78bfa;display:flex;align-items:center;
                                    justify-content:center;font-size:1.15rem;flex-shrink:0;">✨</div>
                        <div>
                            <div style="font-size:0.9rem;font-weight:700;color:#f1f5f9;
                                        margin-bottom:0.15rem;">Gemini AI Campus Intelligence</div>
                            <div style="font-size:0.8rem;color:#64748b;line-height:1.4;">
                                Contextual event recommendations matching your major and activity history.</div>
                        </div>
                    </div>
                </div>
            </div>
            <div style="display:flex;align-items:center;gap:1.5rem;
                        font-size:0.775rem;font-weight:600;color:#475569;">
                <span style="display:flex;align-items:center;gap:0.35rem;">
                    <span style="color:#34d399;">●</span> Role-Based Access</span>
                <span style="display:flex;align-items:center;gap:0.35rem;">
                    <span style="color:#818cf8;">●</span> Supabase Powered</span>
                <span style="display:flex;align-items:center;gap:0.35rem;">
                    <span style="color:#a78bfa;">●</span> University Verified</span>
            </div>
        </div>
        """)

    with col_auth:
        render_html("<div style='height:1rem;'></div>")

        with st.container(border=True):
            render_html("""
            <div style="margin-bottom:1.25rem;">
                <div style="display:inline-flex;align-items:center;justify-content:center;
                            width:48px;height:48px;border-radius:14px;
                            background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);
                            color:white;font-weight:800;font-size:1.3rem;
                            margin-bottom:0.85rem;
                            box-shadow:0 4px 16px rgba(102,126,234,0.35);
                            animation:pulseGlow 3s ease infinite;">C</div>
                <h2 style="font-size:1.5rem;font-weight:800;color:#f1f5f9;
                           margin:0;letter-spacing:-0.03em;">Welcome to CampusPulse</h2>
                <p style="font-size:0.875rem;color:#64748b;margin-top:0.3rem;">
                    Sign in to your university portal or create an account.</p>
            </div>
            """)

            # Three tabs: Sign In | Create Account | Admin Access
            tab_login, tab_signup, tab_admin = st.tabs(
                ["Sign In", "Create Account", "Admin Access"]
            )

            # ── Sign In ────────────────────────────────────────────────────
            with tab_login:
                email_in = st.text_input(
                    "University Email *",
                    placeholder="student@campus.edu",
                    key="login_email",
                    help="Enter your institutional email address.",
                    max_chars=120,
                )
                pass_in = st.text_input(
                    "Password *",
                    type="password",
                    placeholder="••••••••",
                    key="login_password",
                    max_chars=128,
                )
                render_html("<div style='height:8px;'></div>")
                if st.button(
                    "Sign In to Portal",
                    type="primary",
                    use_container_width=True,
                    key="btn_login",
                ):
                    _do_login(supabase, email_in, pass_in)

            # ── Create Account ─────────────────────────────────────────────
            with tab_signup:
                name_su = st.text_input(
                    "Full Name *",
                    placeholder="e.g. Alex Morgan",
                    key="signup_name",
                    max_chars=100,
                )
                email_su = st.text_input(
                    "University Email *",
                    placeholder="name@campus.edu",
                    key="signup_email",
                    max_chars=120,
                )
                pass_su = st.text_input(
                    "Create Password *",
                    type="password",
                    placeholder="Minimum 6 characters",
                    key="signup_password",
                    help="Password must contain at least 6 characters.",
                    max_chars=128,
                )
                role_su = st.selectbox(
                    "Account Type *",
                    ["Student", "Society Head"],
                    key="signup_role",
                )
                if role_su == "Student":
                    st.caption("🎓 **Student Hub**: Browse events, claim digital QR entry passes, and receive personalized AI recommendations.")
                else:
                    st.caption("🏢 **Society Operations**: Propose campus events, manage registrations, track capacity, and scan attendee passes.")

                render_html("<div style='height:8px;'></div>")
                if st.button(
                    "Create Account",
                    type="primary",
                    use_container_width=True,
                    key="btn_signup",
                ):
                    _do_signup(supabase, name_su, email_su, pass_su, role_su)

            # ── Admin Access ───────────────────────────────────────────────
            with tab_admin:
                render_html("""
                <div style="background:rgba(251,113,133,0.06);
                            border:1px solid rgba(251,113,133,0.2);
                            border-radius:10px;padding:0.75rem 1rem;
                            margin-bottom:0.85rem;">
                    <p style="font-size:0.8rem;color:#fb7185;margin:0;line-height:1.5;">
                        <strong>Restricted access.</strong> Administrator accounts require a
                        valid authorization key configured by your institution's database
                        administrator. The key is validated server-side — it is never
                        processed in the application code.
                    </p>
                </div>
                """)
                email_adm = st.text_input(
                    "Admin Email",
                    placeholder="admin@campus.edu",
                    key="admin_email",
                    max_chars=120,
                )
                pass_adm = st.text_input(
                    "Password",
                    type="password",
                    placeholder="••••••••",
                    key="admin_password",
                    max_chars=128,
                )
                key_adm = st.text_input(
                    "Authorization Key",
                    type="password",
                    placeholder="Provided by your database administrator",
                    key="admin_secret",
                    max_chars=256,
                )
                render_html("<div style='height:8px;'></div>")
                if st.button(
                    "Request Administrator Access",
                    type="primary",
                    use_container_width=True,
                    key="btn_admin",
                ):
                    _do_admin_promote(supabase, email_adm, pass_adm, key_adm)


if __name__ == "__main__":
    main()
