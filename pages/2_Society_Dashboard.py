"""
pages/2_Society_Dashboard.py — Society Head Operations Portal.

PRD sections covered: 4.2, 7.1, 7.2, 7.3, 9.1, 14

Security notes
--------------
- require_role(["society_head"]) enforces the role at DB level on every load.
- QR scan: query filtered by qr_token AND event_id (scoped to selected event).
  RLS policy registrations_select_society_head enforces ownership via join.
  Python defence-in-depth also checks society_id.
- Event creation: society_id comes from the DB-fetched society record, never
  from user input.
- All user-supplied strings interpolated into render_html() are passed through
  html.escape() to prevent HTML injection (SEC-M5 fix).
- DB exception text is never surfaced verbatim to users (SEC-M4 fix).
- DB triggers now enforce society/event self-approval prevention (BUG-3/4 fix).
"""

import html
import streamlit as st
import pandas as pd
from datetime import date

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

st.set_page_config(
    page_title="Society Operations · CampusPulse",
    page_icon="🏢",
    layout="wide",
)

apply_custom_theme()

# ── Auth guard ──────────────────────────────────────────────────────────────
user_id, head_profile, supabase = require_role(["society_head"])

# ── App bar / logout ────────────────────────────────────────────────────────
if render_app_bar(
    user_email=st.session_state.user.email,
    user_role="society_head",
    user_name=head_profile.get("name"),
):
    handle_logout(supabase)

# ── Fetch society ────────────────────────────────────────────────────────────
try:
    soc_res = (
        supabase.table("societies")
        .select("*")
        .eq("head_id", user_id)
        .execute()
    )
except Exception as exc:
    st.error(f"Could not load society data: {exc}")
    st.stop()

society = soc_res.data[0] if soc_res.data else None

# ────────────────────────────────────────────────────────────────────────────
# ONBOARDING — No society yet
# ────────────────────────────────────────────────────────────────────────────
if not society:
    render_page_header(
        tag="Society Onboarding",
        title="Charter Your Campus Society",
        description=(
            "Establish your official organisation profile to propose events "
            "and track attendance."
        ),
    )

    render_feedback_banner(
        "info",
        "First-Time Setup",
        "Submit your society's charter below. An administrator will review your application, "
        "typically within 1–2 business days. You will be able to propose events once approved.",
        next_step="Complete the form and click 'Submit for Administrative Approval'.",
    )

    with st.container(border=True):
        render_html("""
        <h3 style="font-size:1.15rem;font-weight:700;color:#f1f5f9;
                   margin:0 0 0.75rem 0;">Submit Society Registration</h3>
        """)
        with st.form("create_society_form"):
            soc_name = st.text_input(
                "Official Society Name *",
                placeholder="e.g. Artificial Intelligence Student Chapter",
                max_chars=120,
            )
            soc_dept = st.text_input(
                "Associated Department (optional)",
                placeholder="e.g. Department of Computer Science",
                max_chars=100,
            )
            soc_desc = st.text_area(
                "Mission Statement & Description",
                placeholder=(
                    "Describe your society's purpose, activities, "
                    "and membership criteria…"
                ),
                max_chars=1500,
            )
            render_html("<div style='height:8px;'></div>")
            if st.form_submit_button(
                "Submit for Administrative Approval",
                type="primary",
                use_container_width=True,
            ):
                if not soc_name.strip():
                    st.error("Please provide a society name.")
                else:
                    try:
                        supabase.table("societies").insert({
                            "name":        soc_name.strip(),
                            "description": soc_desc.strip(),
                            "department":  soc_dept.strip(),
                            "head_id":     user_id,
                            "status":      "pending",
                        }).execute()
                        render_feedback_banner(
                            "success",
                            "Charter Submitted Successfully",
                            f"'{soc_name.strip()}' has been submitted for administrative review.",
                            next_step="You will see a status update here once an administrator reviews your application.",
                        )
                        st.rerun()
                    except Exception:
                        st.error("Submission failed. Please try again.")
    st.stop()


# ────────────────────────────────────────────────────────────────────────────
# SOCIETY IDENTITY HEADER CARD
# ────────────────────────────────────────────────────────────────────────────
status = society.get("status", "pending")
badge_variant = (
    "approved" if status == "active"
    else ("pending" if status == "pending" else "rejected")
)
dept_label = f"• {html.escape(society.get('department') or '')}" if society.get("department") else ""
safe_soc_name = html.escape(society.get("name") or "")
safe_soc_desc = html.escape(society.get("description") or "No description provided.")
safe_soc_id   = html.escape(society["id"][:8])

render_html(f"""
<div class="glass-card" style="margin-bottom:1.75rem;position:relative;">
    <div style="position:absolute;top:0;left:0;right:0;height:3px;
                background:linear-gradient(90deg,#667eea,#764ba2,#22d3ee);
                background-size:200% 100%;animation:gradientShift 4s ease infinite;
                border-radius:16px 16px 0 0;"></div>
    <div style="display:flex;justify-content:space-between;align-items:flex-start;
                flex-wrap:wrap;gap:1rem;padding-top:0.5rem;">
        <div>
            <div style="display:flex;align-items:center;gap:0.6rem;margin-bottom:0.5rem;">
                <span class="badge badge-{badge_variant}">{html.escape(status.upper())} CHARTER</span>
                <span style="font-size:0.8rem;color:#64748b;font-weight:600;">{dept_label}</span>
            </div>
            <h1 style="font-size:1.85rem;font-weight:800;color:#f1f5f9;
                       margin:0;letter-spacing:-0.03em;">{safe_soc_name}</h1>
            <p style="font-size:0.9rem;color:#94a3b8;margin-top:0.4rem;
                      max-width:700px;line-height:1.5;">
                {safe_soc_desc}</p>
        </div>
        <div style="text-align:right;">
            <div style="font-size:0.7rem;color:#475569;font-weight:700;
                        text-transform:uppercase;letter-spacing:0.06em;">Org ID</div>
            <code style="font-size:0.75rem;color:#818cf8;
                         font-family:'JetBrains Mono',monospace;">
                {safe_soc_id}…</code>
        </div>
    </div>
</div>
""")

# ── Status gates ─────────────────────────────────────────────────────────────
if status == "pending":
    render_feedback_banner(
        "warning",
        "Charter Under Review",
        "Your society charter application is currently being reviewed by the university administration.",
        next_step="Event creation and management will unlock once your charter is approved. "
                  "This typically takes 1–2 business days.",
    )
    st.stop()

if status == "rejected":
    rejection_reason = society.get("rejection_reason") or ""
    reason_html = (
        f"<br><strong>Reason:</strong> {html.escape(rejection_reason)}"
        if rejection_reason
        else ""
    )
    render_feedback_banner(
        "error",
        "Charter Application Declined",
        f"Your society charter was not approved by the university administration.{reason_html}",
        next_step="Please contact the Student Affairs Office to discuss next steps or resubmit with revisions.",
    )
    st.stop()

# ────────────────────────────────────────────────────────────────────────────
# ACTIVE SOCIETY — fetch analytics
# ────────────────────────────────────────────────────────────────────────────
try:
    events_res = (
        supabase.table("events")
        .select("*")
        .eq("society_id", society["id"])
        .order("created_at", desc=True)
        .execute()
    )
except Exception as exc:
    st.error(f"Could not load events: {exc}")
    events_res = type("_", (), {"data": []})()

all_events = events_res.data or []
event_ids  = [e["id"] for e in all_events]

regs_by_event:    dict = {}
attended_by_event: dict = {}
total_soc_regs = 0
total_soc_att  = 0
attended_reg_ids: set = set()

if event_ids:
    try:
        all_regs_res = (
            supabase.table("registrations")
            .select("id, event_id")
            .in_("event_id", event_ids)
            .execute()
        )
        all_regs      = all_regs_res.data or []
        total_soc_regs = len(all_regs)
        all_reg_ids    = [r["id"] for r in all_regs]

        if all_reg_ids:
            att_res = (
                supabase.table("attendance")
                .select("registration_id")
                .in_("registration_id", all_reg_ids)
                .execute()
            )
            attended_reg_ids = {a["registration_id"] for a in (att_res.data or [])}
            total_soc_att    = len(attended_reg_ids)

        for r in all_regs:
            eid = r["event_id"]
            regs_by_event[eid] = regs_by_event.get(eid, 0) + 1
            if r["id"] in attended_reg_ids:
                attended_by_event[eid] = attended_by_event.get(eid, 0) + 1
    except Exception as exc:
        st.warning(f"Could not load analytics: {exc}")

turnout = (
    f"{int((total_soc_att / total_soc_regs) * 100)}%"
    if total_soc_regs > 0 else "N/A"
)

# ── KPI row ──────────────────────────────────────────────────────────────────
k1, k2, k3, k4 = st.columns(4)
with k1:
    render_kpi_card("Total Events",   len(all_events),   "Hosted & proposed", "📅")
with k2:
    render_kpi_card("Registrations",  total_soc_regs,    "Confirmed tickets", "👥")
with k3:
    render_kpi_card("Attendees",      total_soc_att,     "Scanned at door",   "✅")
with k4:
    render_kpi_card("Turnout Rate",   turnout,           "Attendance rate",   "📈")

render_html("<div style='height:1.25rem;'></div>")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_portfolio, tab_create, tab_edit, tab_scan = st.tabs([
    "📋  Event Portfolio",
    "➕  Propose New Event",
    "✏️  Edit Pending Event",
    "📷  Venue Check-In",
])

# ────────────────────────────────────────────────────────────────────────────
# TAB 1 — Event Portfolio
# ────────────────────────────────────────────────────────────────────────────
with tab_portfolio:
    render_html("""
    <h3 style="font-size:1.15rem;font-weight:700;color:#f1f5f9;margin:0 0 0.25rem 0;">
        Managed Campus Events</h3>
    <p style="font-size:0.825rem;color:#64748b;margin:0 0 1rem 0;">
        All events your society has proposed or hosted.</p>
    """)

    if all_events:
        # Summary filter bar
        status_counts = {}
        for ev in all_events:
            s = ev.get("status", "pending")
            status_counts[s] = status_counts.get(s, 0) + 1

        filter_options = ["All"] + [
            f"{s.capitalize()} ({c})" for s, c in status_counts.items()
        ]
        portfolio_filter = st.selectbox(
            "Filter by status",
            filter_options,
            key="portfolio_status_filter",
            label_visibility="collapsed",
        )
        selected_status = (
            None if portfolio_filter == "All"
            else portfolio_filter.split(" (")[0].lower()
        )

        visible_events = (
            all_events if selected_status is None
            else [e for e in all_events if e.get("status", "pending") == selected_status]
        )

        if not visible_events:
            render_empty_state(
                "No Events with This Status",
                "Try changing the filter above.",
                "🔍",
            )
        else:
            for event in visible_events:
                total_regs = regs_by_event.get(event["id"], 0)
                attended   = attended_by_event.get(event["id"], 0)
                capacity   = event.get("capacity")
                ev_status  = event.get("status", "pending")
                badge_cls  = (
                    "approved" if ev_status == "approved"
                    else ("pending" if ev_status == "pending" else "rejected")
                )
                ev_turnout = (
                    f"{int((attended / total_regs) * 100)}%" if total_regs > 0 else "0%"
                )
                deadline = html.escape(str(event.get("registration_deadline") or "Not set"))
                safe_ev_title  = html.escape(event.get("title") or "")
                safe_ev_cat    = html.escape(event.get("category") or "General")
                safe_ev_date   = html.escape(str(event.get("date") or ""))
                safe_ev_time   = html.escape(str(event.get("start_time") or ""))
                safe_ev_venue  = html.escape(event.get("venue") or "")
                safe_ev_desc   = html.escape(event.get("description") or "No description.")
                rejection_note = event.get("rejection_reason") or ""

                with st.container(border=True):
                    col_t, col_s = st.columns([3, 2])
                    with col_t:
                        render_html(f"""
                        <div style="display:flex;align-items:center;gap:0.5rem;
                                    margin-bottom:0.4rem;flex-wrap:wrap;">
                            <span class="badge badge-{badge_cls}">{html.escape(ev_status.upper())}</span>
                            <span class="badge badge-category">{safe_ev_cat}</span>
                            <span style="font-size:0.8rem;color:#64748b;font-weight:500;">
                                📅 {safe_ev_date} at {safe_ev_time}</span>
                        </div>
                        <h3 style="font-size:1.2rem;font-weight:700;color:#f1f5f9;
                                   margin:0 0 0.3rem 0;">{safe_ev_title}</h3>
                        <p style="font-size:0.825rem;color:#64748b;margin:0 0 0.25rem 0;">
                            📍 {safe_ev_venue} &nbsp;|&nbsp;
                            🗓️ Reg. deadline: {deadline}</p>
                        <p style="font-size:0.875rem;color:#94a3b8;margin:0;line-height:1.45;">
                            {safe_ev_desc}</p>
                        """)

                        # Show rejection reason inline if rejected
                        if ev_status == "rejected" and rejection_note:
                            render_html(f"""
                            <div style="margin-top:0.75rem;background:rgba(251,113,133,0.08);
                                        border-left:3px solid #fb7185;border-radius:0 8px 8px 0;
                                        padding:0.6rem 0.85rem;">
                                <div style="font-size:0.75rem;font-weight:700;color:#fb7185;
                                            text-transform:uppercase;letter-spacing:0.04em;
                                            margin-bottom:0.2rem;">Admin Rejection Reason</div>
                                <div style="font-size:0.85rem;color:#cbd5e1;line-height:1.4;">
                                    {html.escape(rejection_note)}</div>
                            </div>
                            """)
                        elif ev_status == "rejected":
                            render_html("""
                            <div style="margin-top:0.75rem;background:rgba(251,113,133,0.06);
                                        border-left:3px solid #fb7185;border-radius:0 8px 8px 0;
                                        padding:0.5rem 0.85rem;">
                                <div style="font-size:0.8rem;color:#fb7185;">
                                    Event rejected — no reason provided. Contact Student Affairs for details.</div>
                            </div>
                            """)

                    with col_s:
                        render_html("<div style='height:0.5rem;'></div>")
                        s1, s2, s3 = st.columns(3)
                        s1.metric("Registered", total_regs)
                        s2.metric("Attended",   attended)
                        s3.metric("Turnout",    ev_turnout)
                        if capacity and capacity > 0:
                            fill = min(1.0, total_regs / capacity)
                            st.caption(f"Capacity: {int(fill * 100)}%  ({total_regs}/{capacity})")
                            st.progress(fill)
    else:
        render_empty_state(
            "No Events Created Yet",
            "Use 'Propose New Event' to submit your first event for administrative review.",
            "🗓️",
        )

# ────────────────────────────────────────────────────────────────────────────
# TAB 2 — Propose New Event  (PRD 7.2)
# ────────────────────────────────────────────────────────────────────────────
with tab_create:
    render_html("""
    <h3 style="font-size:1.15rem;font-weight:700;color:#f1f5f9;margin:0 0 0.25rem 0;">
        Submit New Event Proposal</h3>
    <p style="font-size:0.825rem;color:#64748b;margin:0 0 1rem 0;">
        Events are forwarded to administration for verification before going public.</p>
    """)

    with st.container(border=True):
        with st.form("create_event_form"):
            st.markdown("#### 1. Basic Information")
            c_title, c_cat = st.columns([2.5, 1.5])
            with c_title:
                title = st.text_input(
                    "Event Title *",
                    placeholder="e.g. Annual Hackathon & Developer Summit",
                    max_chars=120,
                )
            with c_cat:
                try:
                    cats_res = supabase.table("event_categories").select("name").execute()
                    db_cats  = [c["name"] for c in (cats_res.data or [])]
                except Exception:
                    db_cats = []
                DEFAULT_CATS = [
                    "General", "Technology", "Science", "Arts", "Sports",
                    "Business", "Academic", "Cultural", "Career",
                    "Social", "Competition", "Workshop",
                ]
                cat_list = list(dict.fromkeys(db_cats + DEFAULT_CATS))
                category = st.selectbox("Category *", cat_list)

            desc = st.text_area(
                "Event Description *",
                placeholder="Provide agenda, speakers, prerequisites…",
                max_chars=2000,
            )

            st.divider()
            st.markdown("#### 2. Schedule & Venue")
            col1, col2 = st.columns(2)
            with col1:
                ev_date     = st.date_input("Event Date *")
                time_start  = st.time_input("Start Time *")
            with col2:
                venue       = st.text_input(
                    "Venue / Hall *", placeholder="e.g. Auditorium Hall B",
                    max_chars=120,
                )
                time_end    = st.time_input("End Time (optional)")

            st.divider()
            st.markdown("#### 3. Registration")
            col3, col4 = st.columns(2)
            with col3:
                capacity = st.number_input(
                    "Attendee Capacity (0 = unlimited)",
                    min_value=0, value=100, step=10,
                )
                # PRD 7.2 required field
                reg_deadline = st.date_input(
                    "Registration Deadline *",
                    value=ev_date,
                    help="Students cannot register after this date.",
                )
            with col4:
                is_paid = st.checkbox("Paid entry event?")
                fee = (
                    st.number_input(
                        "Ticket Fee (PKR / USD)",
                        min_value=0.0, value=0.0, step=1.0,
                    )
                    if is_paid else 0.0
                )

            render_html("<div style='height:12px;'></div>")
            if st.form_submit_button(
                "Submit Event for Review", type="primary", use_container_width=True
            ):
                errors = []
                if not title.strip():
                    errors.append("Event title is required.")
                if not desc.strip():
                    errors.append("Description is required.")
                if not venue.strip():
                    errors.append("Venue is required.")
                if reg_deadline and ev_date and reg_deadline > ev_date:
                    errors.append(
                        "Registration deadline cannot be after the event date."
                    )
                if time_end and time_start and time_end <= time_start:
                    errors.append(
                        "End time must be after the start time."
                    )

                if errors:
                    for e in errors:
                        st.error(e)
                else:
                    # Deterministic venue conflict check against existing approved events
                    existing_approved = [ev for ev in all_events if ev.get("status") == "approved"]
                    conflict_rep = detect_schedule_conflict(
                        proposed_venue=venue.strip(),
                        proposed_date=ev_date,
                        proposed_start_time=time_start,
                        proposed_end_time=time_end,
                        existing_events=existing_approved,
                    )
                    if conflict_rep.has_conflict:
                        ai_explanation = explain_conflict_with_ai(
                            conflict_rep,
                            proposed_title=title.strip(),
                            proposed_venue=venue.strip(),
                            proposed_date=str(ev_date),
                            proposed_start=str(time_start),
                            proposed_end=str(time_end) if time_end else "",
                        )
                        render_feedback_banner(
                            "error",
                            "Schedule Conflict Detected",
                            f"{conflict_rep.summary}",
                            next_step=f"AI Facility Advisor: {ai_explanation}",
                        )
                    else:
                        try:
                            supabase.table("events").insert({
                                "society_id":            society["id"],
                                "title":                 title.strip(),
                                "description":           desc.strip(),
                                "category":              category,
                                "date":                  str(ev_date),
                                "start_time":            str(time_start),
                                "end_time":              str(time_end) if time_end else None,
                                "venue":                 venue.strip(),
                                "capacity":              capacity if capacity > 0 else None,
                                "is_paid":               is_paid,
                                "fee":                   float(fee) if is_paid else 0.0,
                                "registration_deadline": str(reg_deadline),
                                "status":                "pending",
                            }).execute()
                            render_feedback_banner(
                                "success",
                                "Event Proposal Submitted",
                                f"'{title.strip()}' has been forwarded for administrative review.",
                                next_step="You can monitor the status in the Event Portfolio tab. "
                                          "You may edit it while it remains in 'Pending' status.",
                            )
                            st.rerun()
                        except Exception:
                            st.error("Submission failed. Please try again.")

# ────────────────────────────────────────────────────────────────────────────
# TAB 3 — Edit Pending Event  (PRD 4.2: edit events before approval)
# ────────────────────────────────────────────────────────────────────────────
with tab_edit:
    render_html("""
    <h3 style="font-size:1.15rem;font-weight:700;color:#f1f5f9;margin:0 0 0.25rem 0;">
        Edit a Pending Event</h3>
    <p style="font-size:0.825rem;color:#64748b;margin:0 0 1rem 0;">
        You can only edit events that are still awaiting admin approval.</p>
    """)

    pending_events = [e for e in all_events if e.get("status") == "pending"]

    if not pending_events:
        render_empty_state(
            "No Editable Events",
            "Only events with 'Pending' status can be edited. "
            "Approved and rejected events cannot be modified.",
            "✏️",
        )
    else:
        event_options = {e["title"]: e for e in pending_events}
        selected_title = st.selectbox(
            "Select event to edit",
            list(event_options.keys()),
            key="edit_event_select",
        )
        sel = event_options[selected_title]

        with st.form("edit_event_form"):
            render_html(f"""
            <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem;">
                <span class="badge badge-pending">PENDING REVIEW</span>
                <span style="font-size:0.875rem;color:#94a3b8;font-weight:600;">
                    Editing: {html.escape(sel['title'])}</span>
            </div>
            """)
            st.divider()

            col_a, col_b = st.columns([2.5, 1.5])
            with col_a:
                ed_title = st.text_input("Event Title *", value=sel.get("title", ""), max_chars=120)
            with col_b:
                try:
                    cats_res2 = supabase.table("event_categories").select("name").execute()
                    db_cats2  = [c["name"] for c in (cats_res2.data or [])]
                except Exception:
                    db_cats2 = []
                DEFAULT_CATS2 = [
                    "General", "Technology", "Science", "Arts", "Sports",
                    "Business", "Academic", "Cultural", "Career",
                    "Social", "Competition", "Workshop",
                ]
                cat_list2 = list(dict.fromkeys(db_cats2 + DEFAULT_CATS2))
                cur_cat_idx = cat_list2.index(sel.get("category", "General")) if sel.get("category") in cat_list2 else 0
                ed_cat = st.selectbox("Category *", cat_list2, index=cur_cat_idx)

            ed_desc  = st.text_area("Description *", value=sel.get("description", ""), max_chars=2000)
            ed_venue = st.text_input("Venue *", value=sel.get("venue", ""), max_chars=120)

            col_c, col_d = st.columns(2)
            with col_c:
                ed_date = st.date_input(
                    "Event Date *",
                    value=date.fromisoformat(sel["date"]) if sel.get("date") else date.today(),
                )
                ed_deadline = st.date_input(
                    "Registration Deadline *",
                    value=date.fromisoformat(sel["registration_deadline"])
                    if sel.get("registration_deadline") else date.today(),
                )
            with col_d:
                # Parse existing times from DB
                import datetime as _dt
                _start_val = None
                _end_val   = None
                if sel.get("start_time"):
                    try:
                        t = sel["start_time"]
                        if isinstance(t, str):
                            _start_val = _dt.time.fromisoformat(t[:8])
                        else:
                            _start_val = t
                    except Exception:
                        _start_val = None
                if sel.get("end_time"):
                    try:
                        t = sel["end_time"]
                        if isinstance(t, str):
                            _end_val = _dt.time.fromisoformat(t[:8])
                        else:
                            _end_val = t
                    except Exception:
                        _end_val = None

                ed_start = st.time_input(
                    "Start Time *",
                    value=_start_val or _dt.time(9, 0),
                )
                ed_end = st.time_input(
                    "End Time (optional)",
                    value=_end_val or _dt.time(11, 0),
                )
                ed_cap = st.number_input(
                    "Capacity (0 = unlimited)",
                    min_value=0,
                    value=int(sel["capacity"]) if sel.get("capacity") else 0,
                    step=10,
                )
                ed_is_paid = st.checkbox("Paid event?", value=bool(sel.get("is_paid")))
                ed_fee = (
                    st.number_input(
                        "Fee",
                        min_value=0.0,
                        value=float(sel.get("fee") or 0.0),
                        step=1.0,
                    )
                    if ed_is_paid else 0.0
                )

            if st.form_submit_button("Save Changes", type="primary", use_container_width=True):
                edit_errors = []
                if not ed_title.strip():
                    edit_errors.append("Title is required.")
                if not ed_venue.strip():
                    edit_errors.append("Venue is required.")
                if ed_deadline and ed_date and ed_deadline > ed_date:
                    edit_errors.append("Deadline cannot be after the event date.")
                if ed_end and ed_start and ed_end <= ed_start:
                    edit_errors.append("End time must be after the start time.")

                if edit_errors:
                    for err in edit_errors:
                        st.error(err)
                else:
                    existing_approved = [ev for ev in all_events if ev.get("status") == "approved"]
                    conflict_rep = detect_schedule_conflict(
                        proposed_venue=ed_venue.strip(),
                        proposed_date=ed_date,
                        proposed_start_time=ed_start,
                        proposed_end_time=ed_end,
                        existing_events=existing_approved,
                        exclude_event_id=sel.get("id"),
                    )
                    if conflict_rep.has_conflict:
                        ai_explanation = explain_conflict_with_ai(
                            conflict_rep,
                            proposed_title=ed_title.strip(),
                            proposed_venue=ed_venue.strip(),
                            proposed_date=str(ed_date),
                            proposed_start=str(ed_start),
                            proposed_end=str(ed_end),
                        )
                        render_feedback_banner(
                            "error",
                            "Schedule Conflict Detected",
                            f"{conflict_rep.summary}",
                            next_step=f"AI Facility Advisor: {ai_explanation}",
                        )
                    else:
                        try:
                            supabase.table("events").update({
                                "title":                 ed_title.strip(),
                                "description":           ed_desc.strip(),
                                "category":              ed_cat,
                                "venue":                 ed_venue.strip(),
                                "date":                  str(ed_date),
                                "start_time":            str(ed_start),
                                "end_time":              str(ed_end),
                                "capacity":              int(ed_cap) if ed_cap > 0 else None,
                                "registration_deadline": str(ed_deadline),
                                "is_paid":               ed_is_paid,
                                "fee":                   float(ed_fee) if ed_is_paid else 0.0,
                            }).eq("id", sel["id"]).eq("status", "pending").execute()
                            render_feedback_banner(
                                "success",
                                "Event Updated",
                                f"'{ed_title.strip()}' has been saved. It remains in 'Pending' status.",
                                next_step="The updated details will be reviewed by an administrator.",
                            )
                            st.rerun()
                        except Exception:
                            st.error("Update failed. Please try again.")

# ────────────────────────────────────────────────────────────────────────────
# TAB 4 — QR Venue Check-In  (PRD 9.1)
#
# Uses the validate_attendance() RPC which:
#   1. Verifies caller owns the event (society_id check inside DB)
#   2. Locks the registration row (SELECT FOR UPDATE) — race-safe
#   3. Checks registration_status is not already 'attended' or 'cancelled'
#   4. Inserts attendance row (UNIQUE enforces single-use)
#   5. Updates registration_status to 'attended'
#   All steps are atomic within one transaction.
# ────────────────────────────────────────────────────────────────────────────
with tab_scan:
    render_html("""
    <h3 style="font-size:1.15rem;font-weight:700;color:#f1f5f9;margin:0 0 0.25rem 0;">
        Venue Check-In Console</h3>
    <p style="font-size:0.825rem;color:#64748b;margin:0 0 1rem 0;">
        Verify student passes at the door by entering the QR token code.</p>
    """)

    approved_events = [e for e in all_events if e.get("status") == "approved"]
    if not approved_events:
        render_empty_state(
            "No Approved Events",
            "You need at least one approved event before you can scan passes.",
            "🎫",
        )
        st.stop()

    event_map = {f"{e['title']} — {e.get('date','TBA')}": e for e in approved_events}
    scan_event_label = st.selectbox(
        "Select event to scan for",
        list(event_map.keys()),
        key="scan_event_selector",
    )
    scan_event = event_map[scan_event_label]

    col_box, col_guide = st.columns([2.5, 1.5])

    with col_box:
        with st.container(border=True):
            render_html("""
            <h4 style="font-size:1rem;font-weight:700;color:#f1f5f9;
                       margin:0 0 0.75rem 0;">Scan or Enter Pass Token</h4>
            """)
            token_input = st.text_input(
                "QR Pass Token",
                placeholder="Paste or scan token (UUID)…",
                key="qr_token_input",
            )
            render_html("<div style='height:8px;'></div>")
            if st.button(
                "Validate & Mark Attendance",
                type="primary",
                use_container_width=True,
                key="btn_validate_qr",
            ):
                import logging as _logging
                _logger = _logging.getLogger(__name__)

                token = token_input.strip()
                if not token:
                    st.error("Please enter a QR token.")
                else:
                    # ── Call the atomic validate_attendance() RPC ────────────
                    # The RPC handles all validation + attendance recording in
                    # one serialised transaction. No multi-step race is possible.
                    try:
                        rpc_res = supabase.rpc(
                            "validate_attendance",
                            {
                                "p_qr_token":  token,
                                "p_event_id":  scan_event["id"],
                            },
                        ).execute()
                        result = rpc_res.data
                    except Exception as exc:
                        _logger.error("validate_attendance RPC call failed: %s", exc)
                        st.error("Check-in failed due to a server error. Please try again.")
                        result = None

                    if isinstance(result, dict):
                        if result.get("ok"):
                            attendee = html.escape(result.get("attendee_name", "Student"))
                            ev_title = html.escape(result.get("event_title", scan_event.get("title", "")))
                            render_feedback_banner(
                                "success",
                                "Attendance Recorded",
                                f"{attendee} has been admitted to {ev_title}.",
                                next_step="The attendee roster below will update automatically.",
                            )
                        else:
                            error_code = result.get("error", "INTERNAL_ERROR")
                            _SCAN_MESSAGES = {
                                "INVALID_TOKEN":         ("error", "Invalid Token", "No matching pass was found for this event. Verify the token is correct."),
                                "WRONG_EVENT":           ("error", "Wrong Event", "This pass belongs to a different event. Ensure you have selected the correct event above."),
                                "ALREADY_ATTENDED":      ("warning", "Already Checked In", "This student's pass has already been used for today's event."),
                                "CANCELLED_REGISTRATION":("warning", "Registration Cancelled", "This student's registration has been cancelled and cannot be admitted."),
                                "NOT_SOCIETY_HEAD":      ("error", "Access Denied", "You do not own this event. You can only scan passes for your society's events."),
                                "UNAUTHENTICATED":       ("error", "Session Expired", "Your session has expired. Please sign out and sign in again."),
                                "INTERNAL_ERROR":        ("error", "Server Error", "Check-in failed due to a server error. Please try again in a moment."),
                            }
                            variant, title_msg, body_msg = _SCAN_MESSAGES.get(
                                error_code, ("error", error_code, "An unexpected error occurred.")
                            )
                            render_feedback_banner(variant, title_msg, body_msg)

    with col_guide:
        with st.container(border=True):
            render_html("""
            <h4 style="font-size:1rem;font-weight:700;color:#f1f5f9;
                       margin:0 0 0.75rem 0;">Check-In Guidelines</h4>
            """)
            st.markdown(
                "- **Event-Scoped**: Select the correct event above before scanning.\n"
                "- **Single Admission**: Each token is valid for one entry only.\n"
                "- **Atomic Validation**: Concurrent scans are serialised at the DB level.\n"
                "- **Society Scoped**: Passes for other societies are rejected server-side.\n"
                "- **Real-Time Sync**: Turnout stats update across the portal."
            )

    # ── Live Attendee Roster ─────────────────────────────────────────────────
    render_html("<div style='height:1.5rem;'></div>")
    render_html("""
    <h4 style="font-size:1rem;font-weight:700;color:#f1f5f9;margin:0 0 0.5rem 0;">
        Live Attendee Roster</h4>
    <p style="font-size:0.8rem;color:#64748b;margin:0 0 0.75rem 0;">
        Students who have checked in for the selected event.</p>
    """)

    col_refresh, col_count = st.columns([1, 5])
    with col_refresh:
        if st.button("🔄 Refresh", key="roster_refresh", use_container_width=True):
            st.rerun()

    try:
        roster_res = (
            supabase.table("registrations")
            .select(
                "id, registered_at, registration_status, "
                "profiles(name, email, department), "
                "attendance(scanned_at)"
            )
            .eq("event_id", scan_event["id"])
            .order("registered_at")
            .execute()
        )
        roster_rows = roster_res.data or []
    except Exception:
        roster_rows = []

    attended_rows = []
    pending_rows  = []
    for r in roster_rows:
        prof = r.get("profiles") or {}
        att  = r.get("attendance") or []
        scanned_at = att[0]["scanned_at"] if att else None
        row = {
            "Name":        prof.get("name", "—"),
            "Email":       prof.get("email", "—"),
            "Department":  prof.get("department", "—"),
            "Status":      r.get("registration_status", "—"),
            "Scanned At":  scanned_at[:19].replace("T", " ") if scanned_at else "—",
        }
        if scanned_at:
            attended_rows.append(row)
        else:
            pending_rows.append(row)

    scanned_count = len(attended_rows)
    total_regs_for_event = len(roster_rows)

    with col_count:
        render_html(f"""
        <div style="display:flex;align-items:center;gap:1rem;padding-top:0.4rem;">
            <span class="badge badge-approved">✅ {scanned_count} Checked In</span>
            <span class="badge badge-pending">⏳ {total_regs_for_event - scanned_count} Registered / Not Yet Arrived</span>
        </div>
        """)

    if attended_rows:
        st.dataframe(
            pd.DataFrame(attended_rows),
            use_container_width=True,
            hide_index=True,
        )
    elif roster_rows:
        render_empty_state(
            "No Check-Ins Yet",
            "No students have scanned their passes yet. The roster will populate as attendees arrive.",
            "📷",
        )
    else:
        render_empty_state(
            "No Registrations",
            "No students have registered for this event yet.",
            "🎫",
        )

    # Collapsible pending roster
    if pending_rows:
        with st.expander(f"⏳ View {len(pending_rows)} Registered Students Not Yet Checked In"):
            st.dataframe(
                pd.DataFrame(pending_rows)[["Name", "Email", "Department"]],
                use_container_width=True,
                hide_index=True,
            )
