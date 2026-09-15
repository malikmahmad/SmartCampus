"""
pages/1_Admin_Dashboard.py — University Administration Console.

PRD sections covered: 4.1, 13, 18 (FR-02, FR-05, FR-14)

Security notes
--------------
- require_role(["admin"]) re-reads the role from the database on every load.
- All approve/reject mutations rely on the authenticated user's JWT; RLS
  policies events_update_admin and societies_update_admin enforce the
  admin role at the database layer.
- DB triggers now prevent society/event self-approval even if policies
  were temporarily relaxed.
- All user-supplied strings interpolated into render_html() are escaped
  with html.escape() to prevent HTML injection (SEC-M5 fix).
- DB exception text is never surfaced verbatim to users (SEC-M4 fix).
"""

import html
import logging
import streamlit as st
import pandas as pd

from utils.auth import require_role, handle_logout
from utils.conflicts import detect_schedule_conflict, explain_conflict_with_ai
from utils.ui import (
    apply_custom_theme,
    render_app_bar,
    render_page_header,
    render_kpi_card,
    render_empty_state,
    render_html,
    render_status_badge,
    render_feedback_banner,
)

_logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Administration · CampusPulse",
    page_icon="⚙️",
    layout="wide",
)

apply_custom_theme()

# ── Auth guard ──────────────────────────────────────────────────────────────
admin_id, admin_profile, supabase = require_role(["admin"])

# ── App bar / logout ────────────────────────────────────────────────────────
if render_app_bar(
    user_email=st.session_state.user.email,
    user_role="admin",
    user_name=admin_profile.get("name"),
):
    handle_logout(supabase)

# ── Page header ─────────────────────────────────────────────────────────────
render_page_header(
    tag="Administration Console",
    title="University Oversight & Moderation",
    description=(
        "Monitor platform engagement, review pending society charters, "
        "and authorise event proposals."
    ),
)

# ── Platform-wide KPI metrics ───────────────────────────────────────────────
try:
    stu_res  = supabase.table("profiles").select("id", count="exact").eq("role", "student").execute()
    soc_res  = supabase.table("societies").select("id", count="exact").execute()
    evt_res  = supabase.table("events").select("id", count="exact").execute()
    pend_res = supabase.table("events").select("id", count="exact").eq("status", "pending").execute()
    reg_res  = supabase.table("registrations").select("id", count="exact").execute()
    att_res  = supabase.table("attendance").select("id", count="exact").execute()
except Exception as exc:
    st.error("Failed to load platform metrics. Please refresh.")
    st.stop()

c1, c2, c3, c4, c5, c6 = st.columns(6)
with c1:
    render_kpi_card("Students",       stu_res.count  or 0, "Registered",      "🎓")
with c2:
    render_kpi_card("Societies",      soc_res.count  or 0, "Organizations",   "🏛️")
with c3:
    render_kpi_card("Total Events",   evt_res.count  or 0, "All statuses",    "📅")
with c4:
    render_kpi_card("Pending Events", pend_res.count or 0, "Awaiting review", "⏳")
with c5:
    render_kpi_card("Registrations",  reg_res.count  or 0, "Passes issued",   "🎫")
with c6:
    render_kpi_card("Attendance",     att_res.count  or 0, "Check-ins",       "✅")

# Alert banner if there are pending items awaiting review
pending_count = pend_res.count or 0
if pending_count > 0:
    render_html(f"""
    <div style="margin:1.25rem 0;background:rgba(251,191,36,0.08);
                border-left:4px solid #fbbf24;border-radius:0 12px 12px 0;
                padding:0.75rem 1.15rem;display:flex;align-items:center;gap:0.75rem;">
        <span style="font-size:1.2rem;">⏳</span>
        <span style="font-weight:700;color:#fbbf24;font-size:0.95rem;">
            {pending_count} event proposal{'s' if pending_count != 1 else ''} awaiting your review
            in the Event Authorization Queue.</span>
    </div>
    """)
else:
    render_html("<div style='height:1.5rem;'></div>")

# ── Navigation tabs (PRD 13) ────────────────────────────────────────────────
(
    tab_overview,
    tab_soc_queue,
    tab_evt_queue,
    tab_students,
    tab_registrations,
    tab_attendance,
) = st.tabs([
    "📊  Platform Analytics",
    "🏛️  Society Charters",
    "📋  Event Queue",
    "🎓  Students",
    "🎫  Registrations",
    "✅  Attendance",
])

# ────────────────────────────────────────────────────────────────────────────
# TAB 1 — Platform Analytics
# ────────────────────────────────────────────────────────────────────────────
with tab_overview:
    col_chart, col_sys = st.columns([3, 1.5])

    with col_chart:
        with st.container(border=True):
            render_html("""
            <h3 style="font-size:1.1rem;font-weight:700;color:#f1f5f9;margin:0 0 0.25rem 0;">
                Event Category Distribution</h3>
            <p style="font-size:0.825rem;color:#64748b;margin:0 0 0.75rem 0;">
                Campus programming breakdown across areas.</p>
            """)
            try:
                all_events_data = supabase.table("events").select("category, status").execute()
            except Exception:
                all_events_data = type("_", (), {"data": []})()

            if all_events_data.data:
                df = pd.DataFrame(all_events_data.data)
                counts = df["category"].value_counts()
                st.bar_chart(counts, color="#818cf8")

                # Status breakdown
                st.divider()
                render_html("""
                <p style="font-size:0.8rem;font-weight:700;color:#64748b;
                           text-transform:uppercase;letter-spacing:0.04em;
                           margin:0 0 0.5rem 0;">Status Breakdown</p>
                """)
                status_counts = df["status"].value_counts()
                scol1, scol2, scol3, scol4 = st.columns(4)
                cols = [scol1, scol2, scol3, scol4]
                status_list = ["approved", "pending", "rejected", "cancelled"]
                status_labels = ["Approved", "Pending", "Rejected", "Cancelled"]
                for i, (s, label) in enumerate(zip(status_list, status_labels)):
                    cols[i].metric(label, status_counts.get(s, 0))
            else:
                render_empty_state(
                    "No Events Logged",
                    "Analytics will display once societies begin proposing events.",
                    "📊",
                )

    with col_sys:
        with st.container(border=True):
            render_html("""
            <h3 style="font-size:1.1rem;font-weight:700;color:#f1f5f9;margin:0 0 0.5rem 0;">
                System Status</h3>
            <div style="display:flex;flex-direction:column;gap:1rem;
                        font-size:0.875rem;padding-top:0.5rem;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="color:#94a3b8;">Database</span>
                    <span class="badge badge-approved">ONLINE</span>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="color:#94a3b8;">Auth Engine</span>
                    <span class="badge badge-approved">ACTIVE</span>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="color:#94a3b8;">AI Matcher</span>
                    <span class="badge badge-ai">GEMINI 1.5</span>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="color:#94a3b8;">QR Engine</span>
                    <span class="badge badge-approved">SECURE</span>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:center;">
                    <span style="color:#94a3b8;">RLS</span>
                    <span class="badge badge-approved">ENFORCED</span>
                </div>
            </div>
            """)
            st.divider()
            st.caption(f"Logged in as {html.escape(admin_profile.get('email', ''))}")

# ────────────────────────────────────────────────────────────────────────────
# TAB 2 — Society Charter Queue
# ────────────────────────────────────────────────────────────────────────────
with tab_soc_queue:
    render_html("""
    <h3 style="font-size:1.15rem;font-weight:700;color:#f1f5f9;margin:0 0 0.25rem 0;">
        Society Charter Applications</h3>
    <p style="font-size:0.825rem;color:#64748b;margin:0 0 1rem 0;">
        Review proposed student organisations seeking official recognition.</p>
    """)

    try:
        pending_soc = (
            supabase.table("societies")
            .select("*, profiles(name, email)")
            .eq("status", "pending")
            .order("created_at")
            .execute()
        )
    except Exception:
        render_feedback_banner("error", "Load Error", "Could not load pending societies. Please refresh.")
        pending_soc = type("_", (), {"data": []})()

    if pending_soc.data:
        render_html(f"""
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1rem;">
            <span class="badge badge-pending">{len(pending_soc.data)} PENDING</span>
            <span style="font-size:0.825rem;color:#64748b;">
                Review each application carefully before approving or rejecting.</span>
        </div>
        """)

        for soc in pending_soc.data:
            head = soc.get("profiles") or {}
            safe_soc_name   = html.escape(soc.get("name") or "")
            safe_soc_dept   = html.escape(soc.get("department") or "General")
            safe_soc_desc   = html.escape(soc.get("description") or "No description provided.")
            safe_head_name  = html.escape(head.get("name") or "Society Head")
            safe_head_email = html.escape(head.get("email") or "—")
            created_at = (soc.get("created_at") or "")[:10]

            with st.container(border=True):
                colA, colB = st.columns([3.5, 1.4])
                with colA:
                    render_html(f"""
                    <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem;flex-wrap:wrap;">
                        <span class="badge badge-pending">PENDING CHARTER</span>
                        <span style="font-size:0.8rem;color:#64748b;font-weight:600;">
                            Dept: {safe_soc_dept}</span>
                        <span style="font-size:0.75rem;color:#475569;">
                            Applied: {html.escape(created_at)}</span>
                    </div>
                    <h3 style="font-size:1.25rem;font-weight:800;color:#f1f5f9;
                               margin:0 0 0.3rem 0;">{safe_soc_name}</h3>
                    <p style="font-size:0.85rem;color:#818cf8;font-weight:600;
                              margin:0 0 0.5rem 0;">
                        Requested by {safe_head_name}
                        <span style="color:#475569;font-weight:500;">
                            &nbsp;({safe_head_email})</span></p>
                    <p style="font-size:0.875rem;color:#94a3b8;margin:0;line-height:1.5;">
                        {safe_soc_desc}</p>
                    """)

                with colB:
                    render_html("<div style='height:1rem;'></div>")

                    # ── Approve button ────────────────────────────────────
                    if st.button(
                        "✅ Approve Charter",
                        key=f"app_soc_{soc['id']}",
                        type="primary",
                        use_container_width=True,
                    ):
                        try:
                            supabase.table("societies").update(
                                {"status": "active"}
                            ).eq("id", soc["id"]).execute()
                            render_feedback_banner(
                                "success",
                                "Charter Approved",
                                f"'{safe_soc_name}' is now an active society. "
                                "The society head can begin proposing events.",
                            )
                            st.rerun()
                        except Exception as exc:
                            _logger.error("Society approve failed: %s", exc)
                            st.error("Could not approve charter. Please try again.")

                    # ── Reject with mandatory reason ──────────────────────
                    with st.popover("❌ Reject Charter", use_container_width=True):
                        render_html("""
                        <div style="margin-bottom:0.5rem;">
                            <span style="font-size:0.85rem;font-weight:700;color:#fb7185;">
                                Reject Society Charter</span><br>
                            <span style="font-size:0.8rem;color:#94a3b8;">
                                Providing a reason helps the society head understand
                                what to address before reapplying.</span>
                        </div>
                        """)
                        soc_reject_reason = st.text_area(
                            "Rejection Reason *",
                            key=f"soc_reason_{soc['id']}",
                            placeholder="e.g. Insufficient mission statement, duplicate society already exists, missing department approval…",
                            height=100,
                        )
                        if st.button(
                            "Confirm Rejection",
                            key=f"confirm_rej_soc_{soc['id']}",
                            type="primary",
                        ):
                            if not soc_reject_reason.strip():
                                st.warning("Please provide a rejection reason before confirming.")
                            else:
                                try:
                                    supabase.table("societies").update({
                                        "status":           "rejected",
                                        "rejection_reason": soc_reject_reason.strip(),
                                    }).eq("id", soc["id"]).execute()
                                    render_feedback_banner(
                                        "warning",
                                        "Charter Rejected",
                                        f"'{safe_soc_name}' charter has been rejected. "
                                        "The society head will see your reason.",
                                    )
                                    st.rerun()
                                except Exception as exc:
                                    _logger.error("Society reject failed: %s", exc)
                                    st.error("Could not reject charter. Please try again.")
    else:
        render_empty_state(
            "Queue Clear",
            "All society charters have been reviewed. No pending applications.",
            "🏛️",
        )

# ────────────────────────────────────────────────────────────────────────────
# TAB 3 — Event Authorization Queue
# ────────────────────────────────────────────────────────────────────────────
with tab_evt_queue:
    render_html("""
    <h3 style="font-size:1.15rem;font-weight:700;color:#f1f5f9;margin:0 0 0.25rem 0;">
        Event Authorization Queue</h3>
    <p style="font-size:0.825rem;color:#64748b;margin:0 0 1rem 0;">
        Review proposed events before publishing to the campus directory.</p>
    """)

    try:
        pending_evt = (
            supabase.table("events")
            .select("*, societies(name, department)")
            .eq("status", "pending")
            .order("created_at")
            .execute()
        )
    except Exception:
        render_feedback_banner("error", "Load Error", "Could not load pending events. Please refresh.")
        pending_evt = type("_", (), {"data": []})()

    # Pre-fetch approved events for deterministic schedule conflict detection
    try:
        approved_res = (
            supabase.table("events")
            .select("id, title, venue, date, start_time, end_time, status")
            .eq("status", "approved")
            .execute()
        )
        approved_evs = approved_res.data or []
    except Exception:
        approved_evs = []

    if pending_evt.data:
        render_html(f"""
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:1rem;">
            <span class="badge badge-pending">{len(pending_evt.data)} PENDING</span>
            <span style="font-size:0.825rem;color:#64748b;">
                Conflict analysis is performed automatically for each proposal.</span>
        </div>
        """)

        for event in pending_evt.data:
            soc_data = event.get("societies") or {}
            fee_tag = (
                f"${event.get('fee', 0):.2f}"
                if event.get("is_paid")
                else "FREE"
            )
            deadline = html.escape(str(event.get("registration_deadline") or "Not set"))
            safe_evt_title = html.escape(event.get("title") or "")
            safe_evt_cat   = html.escape(event.get("category") or "General")
            safe_evt_soc   = html.escape(soc_data.get("name") or "Unknown Society")
            safe_evt_date  = html.escape(str(event.get("date") or ""))
            safe_evt_time  = html.escape(str(event.get("start_time") or ""))
            safe_evt_end   = html.escape(str(event.get("end_time") or "—"))
            safe_evt_venue = html.escape(event.get("venue") or "")
            safe_evt_cap   = html.escape(str(event.get("capacity") or "Unlimited"))
            safe_evt_desc  = html.escape(event.get("description") or "No description provided.")
            created_at     = (event.get("created_at") or "")[:10]

            # Deterministic conflict check against existing approved events
            conflict_rep = detect_schedule_conflict(
                proposed_venue=event.get("venue") or "",
                proposed_date=event.get("date"),
                proposed_start_time=event.get("start_time"),
                proposed_end_time=event.get("end_time"),
                existing_events=approved_evs,
                exclude_event_id=event.get("id"),
            )
            conflict_badge = (
                '<span class="badge badge-rejected" style="font-weight:700;">⚠️ VENUE CONFLICT</span>'
                if conflict_rep.has_conflict
                else '<span class="badge badge-approved" style="font-weight:700;">✅ VENUE CLEAR</span>'
            )

            with st.container(border=True):
                colA, colB = st.columns([3.5, 1.4])
                with colA:
                    render_html(f"""
                    <div style="display:flex;align-items:center;gap:0.5rem;
                                margin-bottom:0.5rem;flex-wrap:wrap;">
                        <span class="badge badge-pending">PENDING VERIFICATION</span>
                        {conflict_badge}
                        <span class="badge badge-category">{safe_evt_cat}</span>
                        <span style="font-size:0.75rem;color:#475569;">
                            Submitted: {html.escape(created_at)}</span>
                    </div>
                    <h3 style="font-size:1.25rem;font-weight:800;color:#f1f5f9;
                               margin:0 0 0.3rem 0;">{safe_evt_title}</h3>
                    <p style="font-size:0.85rem;color:#818cf8;font-weight:600;
                              margin:0 0 0.6rem 0;">
                        Hosted by {safe_evt_soc}</p>
                    <div style="display:flex;flex-wrap:wrap;gap:1.25rem;
                                color:#64748b;font-size:0.825rem;margin-bottom:0.75rem;">
                        <span>📅 {safe_evt_date}</span>
                        <span>🕐 {safe_evt_time} → {safe_evt_end}</span>
                        <span>📍 {safe_evt_venue}</span>
                        <span>👥 Capacity: {safe_evt_cap}</span>
                        <span>🏷️ Ticket: {html.escape(fee_tag)}</span>
                        <span>🗓️ Reg. deadline: {deadline}</span>
                    </div>
                    <p style="font-size:0.875rem;color:#94a3b8;margin:0 0 0.5rem 0;line-height:1.5;">
                        {safe_evt_desc}</p>
                    """)

                    if conflict_rep.has_conflict:
                        with st.expander("⚠️ View Schedule Conflict Breakdown & AI Advisory", expanded=True):
                            st.warning(conflict_rep.summary)
                            ai_advice = explain_conflict_with_ai(
                                conflict_rep,
                                proposed_title=event.get("title") or "",
                                proposed_venue=event.get("venue") or "",
                                proposed_date=str(event.get("date") or ""),
                                proposed_start=str(event.get("start_time") or ""),
                                proposed_end=str(event.get("end_time") or ""),
                            )
                            st.info(f"🤖 **Facility AI Advice:** {ai_advice}")

                with colB:
                    render_html("<div style='height:1rem;'></div>")

                    # ── Authorize button ──────────────────────────────────
                    if st.button(
                        "✅ Authorize Event",
                        key=f"app_evt_{event['id']}",
                        type="primary",
                        use_container_width=True,
                    ):
                        try:
                            # Call RPC function for audit trail
                            result = supabase.rpc(
                                "approve_event",
                                {"p_event_id": event["id"]}
                            ).execute()

                            if result.data and result.data.get("ok"):
                                render_feedback_banner(
                                    "success",
                                    "Event Authorized",
                                    f"'{safe_evt_title}' is now live on the campus directory. "
                                    "Students can discover and register.",
                                )
                                st.rerun()
                            else:
                                error_msg = (
                                    result.data.get("error", "Unknown error")
                                    if result.data else "Unknown error"
                                )
                                st.error(f"Could not authorize event: {error_msg}")
                        except Exception as exc:
                            _logger.error("Event approve failed: %s", exc)
                            st.error("Could not authorize event. Please try again.")

                    # ── Reject with mandatory reason ──────────────────────
                    with st.popover("❌ Reject Event", use_container_width=True):
                        render_html("""
                        <div style="margin-bottom:0.5rem;">
                            <span style="font-size:0.85rem;font-weight:700;color:#fb7185;">
                                Reject Event Proposal</span><br>
                            <span style="font-size:0.8rem;color:#94a3b8;">
                                Your reason will be visible to the society head
                                so they can revise and resubmit.</span>
                        </div>
                        """)
                        reason = st.text_area(
                            "Rejection Reason *",
                            key=f"reason_{event['id']}",
                            placeholder="e.g. Conflicts with academic calendar, insufficient details, duplicate event, missing safety plan…",
                            height=100,
                        )
                        if st.button(
                            "Confirm Rejection",
                            key=f"confirm_rej_{event['id']}",
                            type="primary",
                        ):
                            if not reason.strip():
                                st.warning("Please provide a rejection reason before confirming.")
                            else:
                                try:
                                    result = supabase.rpc(
                                        "reject_event",
                                        {
                                            "p_event_id": event["id"],
                                            "p_reason":   reason.strip(),
                                        }
                                    ).execute()

                                    if result.data and result.data.get("ok"):
                                        render_feedback_banner(
                                            "warning",
                                            "Event Rejected",
                                            f"'{safe_evt_title}' has been rejected. "
                                            "The society head will see your reason.",
                                        )
                                        st.rerun()
                                    else:
                                        error_msg = (
                                            result.data.get("error", "Unknown error")
                                            if result.data else "Unknown error"
                                        )
                                        st.error(f"Could not reject event: {error_msg}")
                                except Exception as exc:
                                    _logger.error("Event reject failed: %s", exc)
                                    st.error("Could not reject event. Please try again.")
    else:
        render_empty_state(
            "Queue Clear",
            "All event proposals have been reviewed. New submissions will appear here automatically.",
            "✔️",
        )

# ────────────────────────────────────────────────────────────────────────────
# TAB 4 — Students  (PRD 13: Admin can view students)
# ────────────────────────────────────────────────────────────────────────────
with tab_students:
    render_html("""
    <h3 style="font-size:1.15rem;font-weight:700;color:#f1f5f9;margin:0 0 0.25rem 0;">
        Registered Students</h3>
    <p style="font-size:0.825rem;color:#64748b;margin:0 0 1rem 0;">
        All student accounts on the platform.</p>
    """)

    search_stu = st.text_input(
        "Search by name or email",
        placeholder="🔍  Filter students by name or email…",
        key="admin_stu_search",
        label_visibility="collapsed",
    )

    try:
        students_res = (
            supabase.table("profiles")
            .select("id, name, email, department, interests, created_at")
            .eq("role", "student")
            .order("created_at", desc=True)
            .execute()
        )
    except Exception:
        render_feedback_banner("error", "Load Error", "Could not load students. Please refresh.")
        students_res = type("_", (), {"data": []})()

    rows = students_res.data or []
    if search_stu.strip():
        q = search_stu.lower()
        rows = [
            r for r in rows
            if q in (r.get("name") or "").lower()
            or q in (r.get("email") or "").lower()
        ]

    if rows:
        df = pd.DataFrame(rows)[
            ["name", "email", "department", "interests", "created_at"]
        ]
        df.columns = ["Name", "Email", "Department", "Interests", "Joined"]
        df["Joined"] = pd.to_datetime(df["Joined"]).dt.strftime("%Y-%m-%d")
        df = df.fillna("—")
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"{len(rows)} student(s) found.")
    else:
        render_empty_state(
            "No Students Found",
            "No student accounts match your search." if search_stu else "No students have registered yet.",
            "🎓",
        )

# ────────────────────────────────────────────────────────────────────────────
# TAB 5 — Registrations  (PRD 13: Admin can view registrations)
# ────────────────────────────────────────────────────────────────────────────
with tab_registrations:
    render_html("""
    <h3 style="font-size:1.15rem;font-weight:700;color:#f1f5f9;margin:0 0 0.25rem 0;">
        All Event Registrations</h3>
    <p style="font-size:0.825rem;color:#64748b;margin:0 0 1rem 0;">
        Platform-wide registration records.</p>
    """)

    reg_filter_col1, reg_filter_col2 = st.columns([3, 1.5])
    with reg_filter_col1:
        search_reg = st.text_input(
            "Search registrations",
            placeholder="🔍  Search by student name or event title…",
            key="admin_reg_search",
            label_visibility="collapsed",
        )
    with reg_filter_col2:
        status_filter = st.selectbox(
            "Status filter",
            ["All Statuses", "confirmed", "attended", "cancelled"],
            key="admin_reg_status",
            label_visibility="collapsed",
        )

    try:
        regs_res = (
            supabase.table("registrations")
            .select(
                "id, registered_at, payment_status, registration_status, "
                "events(title, date), profiles(name, email)"
            )
            .order("registered_at", desc=True)
            .execute()
        )
    except Exception:
        render_feedback_banner("error", "Load Error", "Could not load registrations. Please refresh.")
        regs_res = type("_", (), {"data": []})()

    reg_rows = []
    for r in regs_res.data or []:
        evt  = r.get("events")  or {}
        prof = r.get("profiles") or {}
        reg_rows.append({
            "Student":    prof.get("name", "—"),
            "Email":      prof.get("email", "—"),
            "Event":      evt.get("title", "—"),
            "Event Date": evt.get("date", "—"),
            "Status":     r.get("registration_status", "—"),
            "Payment":    r.get("payment_status", "—"),
            "Registered": r.get("registered_at", "")[:10] if r.get("registered_at") else "—",
        })

    if search_reg.strip():
        q = search_reg.lower()
        reg_rows = [
            row for row in reg_rows
            if q in row["Student"].lower() or q in row["Event"].lower()
        ]
    if status_filter != "All Statuses":
        reg_rows = [row for row in reg_rows if row["Status"] == status_filter]

    if reg_rows:
        df_reg = pd.DataFrame(reg_rows)
        st.dataframe(df_reg, use_container_width=True, hide_index=True)
        st.caption(f"{len(reg_rows)} registration(s) found.")
    else:
        render_empty_state(
            "No Registrations Found",
            "No records match your current filters.",
            "🎫",
        )

# ────────────────────────────────────────────────────────────────────────────
# TAB 6 — Attendance  (PRD 13: Admin can view attendance)
# ────────────────────────────────────────────────────────────────────────────
with tab_attendance:
    render_html("""
    <h3 style="font-size:1.15rem;font-weight:700;color:#f1f5f9;margin:0 0 0.25rem 0;">
        Attendance Records</h3>
    <p style="font-size:0.825rem;color:#64748b;margin:0 0 1rem 0;">
        All QR check-in events across the platform.</p>
    """)

    att_filter_col1, att_filter_col2 = st.columns([3, 1])
    with att_filter_col1:
        att_search = st.text_input(
            "Search attendance",
            placeholder="🔍  Search by student name or event…",
            key="admin_att_search",
            label_visibility="collapsed",
        )
    with att_filter_col2:
        if st.button("🔄 Refresh", key="att_refresh", use_container_width=True):
            st.rerun()

    try:
        att_full = (
            supabase.table("attendance")
            .select(
                "id, scanned_at, status, "
                "registrations(registered_at, "
                "  events(title, date, venue), "
                "  profiles(name, email))"
            )
            .order("scanned_at", desc=True)
            .execute()
        )
    except Exception:
        render_feedback_banner("error", "Load Error", "Could not load attendance records. Please refresh.")
        att_full = type("_", (), {"data": []})()

    att_rows = []
    for a in att_full.data or []:
        reg  = a.get("registrations") or {}
        evt  = reg.get("events")      or {}
        prof = reg.get("profiles")    or {}
        att_rows.append({
            "Student":     prof.get("name",  "—"),
            "Email":       prof.get("email", "—"),
            "Event":       evt.get("title",  "—"),
            "Event Date":  evt.get("date",   "—"),
            "Venue":       evt.get("venue",  "—"),
            "Scan Status": a.get("status", "—"),
            "Scanned At":  (a.get("scanned_at") or "")[:19].replace("T", " "),
        })

    if att_search.strip():
        q = att_search.lower()
        att_rows = [
            row for row in att_rows
            if q in row["Student"].lower() or q in row["Event"].lower()
        ]

    if att_rows:
        df_att = pd.DataFrame(att_rows)
        st.dataframe(df_att, use_container_width=True, hide_index=True)
        st.caption(f"{len(att_rows)} attendance record(s).")
    else:
        render_empty_state(
            "No Attendance Records",
            "Check-in records will appear here once students scan their QR passes.",
            "✅",
        )
