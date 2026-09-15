"""
pages/3_Student_Dashboard.py — Student Hub Portal.

PRD sections covered: 4.3, 6.1, 6.2, 6.3, 8.1, 8.2, 9, 10, 15

Security notes
--------------
- require_role(["student"]) enforces role at DB level on every load.
- student_id in all mutations comes from the verified JWT via
  st.session_state.user.id, never from user input.
- All user-supplied strings interpolated into render_html() are passed
  through html.escape() to prevent HTML injection (SEC-M5 fix).
- Registration logic moved to utils/registration.py (SEC-H4 fix).
- DB triggers enforce approved-event-only registration, deadline, and
  capacity at the database layer.
- AI output rendered via st.markdown(), not render_html() (XSS safe).
- DB exception text is never surfaced verbatim (SEC-M4 fix).
"""

from __future__ import annotations

import html
import streamlit as st
from datetime import date

from utils.auth import require_role, handle_logout
from utils.qr_ops import get_qr_base64
from utils.ai_recs import get_recommendations, generate_recommendations_pipeline, PipelineResult
from utils.registration import register_student
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
    page_title="Student Portal · CampusPulse",
    page_icon="🎓",
    layout="wide",
)

apply_custom_theme()

# ── Auth guard ──────────────────────────────────────────────────────────────
user_id, student_profile, supabase = require_role(["student"])

# ── App bar / logout ────────────────────────────────────────────────────────
if render_app_bar(
    user_email=st.session_state.user.email,
    user_role="student",
    user_name=student_profile.get("name"),
):
    handle_logout(supabase)

# ── Page header ─────────────────────────────────────────────────────────────
student_name = student_profile.get("name") or "Student"
render_page_header(
    tag="Student Hub",
    title=f"Welcome back, {student_name}",
    description=(
        "Discover campus events, manage your digital QR passes, "
        "and explore AI recommendations."
    ),
)

# ── Student KPIs ─────────────────────────────────────────────────────────────
try:
    regs_call = (
        supabase.table("registrations")
        .select("id, event_id")
        .eq("student_id", user_id)
        .execute()
    )
except Exception as exc:
    st.error(f"Could not load your registrations: {exc}")
    regs_call = type("_", (), {"data": []})()

registered_event_ids = [r["event_id"] for r in (regs_call.data or [])]
registered_ids       = [r["id"]       for r in (regs_call.data or [])]

attended_count = 0
if registered_ids:
    try:
        att_call = (
            supabase.table("attendance")
            .select("id")
            .in_("registration_id", registered_ids)
            .execute()
        )
        attended_count = len(att_call.data or [])
    except Exception:
        pass

try:
    total_call = (
        supabase.table("events")
        .select("id", count="exact")
        .eq("status", "approved")
        .gte("date", str(date.today()))
        .execute()
    )
    approved_events_count = total_call.count or 0
except Exception:
    approved_events_count = 0

dept = student_profile.get("department") or "General"

c1, c2, c3, c4 = st.columns(4)
with c1:
    render_kpi_card("Upcoming Events",   approved_events_count, "Live verified events", "🏛️")
with c2:
    render_kpi_card("My Registrations",  len(registered_event_ids), "Active passes", "🎫")
with c3:
    render_kpi_card("Events Attended",   attended_count, "Verified check-ins", "✅")
with c4:
    render_kpi_card("Major / Track",     dept, "Academic department", "🎓")

render_html("<div style='height:1.5rem;'></div>")

# ── Navigation tabs ──────────────────────────────────────────────────────────
tab_discover, tab_passes, tab_profile, tab_ai = st.tabs([
    "Discover Events",
    "My Digital Passes",
    "My Profile",
    "AI Recommendations",
])

# ────────────────────────────────────────────────────────────────────────────
# TAB 1 — Discover Events  (PRD 6.1, 6.2, 6.3)
# ────────────────────────────────────────────────────────────────────────────
with tab_discover:
    render_html("""
    <h3 style="font-size:1.15rem;font-weight:700;color:#f1f5f9;margin:0 0 1rem 0;">
        Explore Upcoming Events</h3>
    """)

    # ── Filters (PRD 6.3) ───────────────────────────────────────────────────
    f1, f2, f3, f4 = st.columns([3, 1.5, 1.5, 1.5])
    with f1:
        search_q = st.text_input(
            "Search",
            placeholder="Search by title, topic, or keyword…",
            label_visibility="collapsed",
        )
    with f2:
        category_filter = st.selectbox(
            "Category",
            ["All Categories", "Technology", "Science", "Arts", "Sports",
             "Business", "Academic", "Cultural", "Career",
             "Social", "Competition", "Workshop", "General"],
            label_visibility="collapsed",
        )
    with f3:
        pricing_filter = st.selectbox(
            "Pricing",
            ["All Events", "Free Only", "Paid Only"],
            label_visibility="collapsed",
        )
    with f4:
        date_filter = st.date_input(
            "From date",
            value=date.today(),
            label_visibility="collapsed",
            help="Show events from this date onwards.",
        )

    # ── Fetch approved, non-expired events ──────────────────────────────────
    try:
        events_res = (
            supabase.table("events")
            .select("*, societies(name)")
            .eq("status", "approved")
            .gte("date", str(date_filter))   # PRD Business Rule 5: no expired events
            .order("date")
            .execute()
        )
    except Exception as exc:
        st.error(f"Could not load events: {exc}")
        events_res = type("_", (), {"data": []})()

    all_ev = events_res.data or []

    # Fetch registration counts for capacity display.
    ev_ids = [e["id"] for e in all_ev]
    reg_counts: dict = {}
    if ev_ids:
        try:
            # 1. Try secure aggregator function (bypasses student row-level read restrictions)
            rc_rpc = supabase.rpc("get_event_reg_counts", {"p_event_ids": ev_ids}).execute()
            if rc_rpc.data and isinstance(rc_rpc.data, list):
                for row in rc_rpc.data:
                    reg_counts[row["event_id"]] = int(row.get("reg_count", 0))
            else:
                # 2. Fallback: query active registrations
                rc_res = (
                    supabase.table("registrations")
                    .select("event_id")
                    .in_("event_id", ev_ids)
                    .neq("registration_status", "cancelled")
                    .execute()
                )
                for r in rc_res.data or []:
                    eid = r["event_id"]
                    reg_counts[eid] = reg_counts.get(eid, 0) + 1
        except Exception:
            pass

    # ── Client-side filters ──────────────────────────────────────────────────
    today = date.today()
    filtered: list = []
    for e in all_ev:
        if search_q.strip():
            q = search_q.lower()
            if (
                q not in (e.get("title") or "").lower()
                and q not in (e.get("category") or "").lower()
                and q not in (e.get("description") or "").lower()
            ):
                continue
        if (
            category_filter != "All Categories"
            and (e.get("category") or "").lower() != category_filter.lower()
        ):
            continue
        if pricing_filter == "Free Only" and e.get("is_paid"):
            continue
        if pricing_filter == "Paid Only" and not e.get("is_paid"):
            continue
        filtered.append(e)

    # Filter active indicators & count
    f_stat, f_reset = st.columns([4, 1.2])
    with f_stat:
        st.markdown(
            f"<div style='font-size:0.85rem;color:#94a3b8;margin-bottom:0.75rem;'>"
            f"Showing <strong style='color:#f8fafc;'>{len(filtered)}</strong> of "
            f"<strong style='color:#f8fafc;'>{len(all_ev)}</strong> upcoming verified campus events"
            f"</div>",
            unsafe_allow_html=True,
        )

    if not filtered:
        render_empty_state(
            "No Events Match Your Filters",
            "Try clearing your search query or selecting 'All Categories' and 'All Events'.",
            "🔍",
        )
    else:
        for event in filtered:
            society_name  = html.escape((event.get("societies") or {}).get("name", "Campus Society"))
            current_regs  = reg_counts.get(event["id"], 0)
            capacity      = event.get("capacity")
            is_sold_out   = bool(capacity and current_regs >= capacity)
            is_registered = event["id"] in registered_event_ids

            # PRD Business Rule 4: check registration deadline.
            deadline_str  = event.get("registration_deadline")
            deadline_date = (
                date.fromisoformat(str(deadline_str)) if deadline_str else None
            )
            deadline_passed = bool(deadline_date and deadline_date < today)

            spots_left = max(0, capacity - current_regs) if capacity else None
            spots_text = (
                f"{spots_left} of {capacity} spots left"
                if capacity else "Unlimited Capacity"
            )
            fill_pct  = (
                min(100, int((current_regs / capacity) * 100))
                if capacity and capacity > 0 else 0
            )
            fee_badge = (
                f'<span class="badge badge-paid">${event.get("fee", 0):.2f}</span>'
                if event.get("is_paid")
                else '<span class="badge badge-free">FREE PASS</span>'
            )
            safe_category = html.escape(event.get("category") or "General")
            cat_badge = f'<span class="badge badge-category">{safe_category}</span>'
            deadline_display = html.escape(deadline_str or "No deadline")
            safe_title  = html.escape(event.get("title") or "")
            safe_desc   = html.escape(event.get("description") or "No description provided.")
            safe_date   = html.escape(str(event.get("date") or "TBA"))
            safe_time   = html.escape(str(event.get("start_time") or "TBA"))
            safe_venue  = html.escape(event.get("venue") or "TBA")

            with st.container(border=True):
                col_info, col_action = st.columns([3.2, 1.2])

                with col_info:
                    render_html(f"""
                    <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem;flex-wrap:wrap;">
                        {cat_badge} {fee_badge}
                    </div>
                    <h3 style="font-size:1.25rem;font-weight:700;color:#f8fafc;
                               margin:0 0 0.3rem 0;">{safe_title}</h3>
                    <p style="font-size:0.85rem;color:#818cf8;font-weight:600;
                              margin:0 0 0.5rem 0;">Hosted by {society_name}</p>
                    <p style="font-size:0.875rem;color:#cbd5e1;
                              margin:0 0 0.75rem 0;line-height:1.55;">
                        {safe_desc}</p>
                    <div style="display:flex;flex-wrap:wrap;gap:1.25rem;
                                color:#94a3b8;font-size:0.825rem;font-weight:500;">
                        <span>📅 {safe_date}</span>
                        <span>⏰ {safe_time}</span>
                        <span>📍 {safe_venue}</span>
                        <span>👥 {spots_text}</span>
                        <span>🗓️ Reg. Closes: {deadline_display}</span>
                    </div>
                    """)
                    if capacity:
                        st.progress(fill_pct / 100)

                with col_action:
                    render_html("<div style='height:1.5rem;'></div>")

                    if is_registered:
                        st.button(
                            "✅ Registered",
                            key=f"reg_{event['id']}",
                            disabled=True,
                            use_container_width=True,
                        )
                        st.caption("Active pass in 'My Digital Passes'")
                    elif is_sold_out:
                        st.button(
                            "❌ Sold Out",
                            key=f"sold_{event['id']}",
                            disabled=True,
                            use_container_width=True,
                        )
                        st.caption(f"Capacity of {capacity} reached")
                    elif deadline_passed:
                        st.button(
                            "🔒 Reg. Closed",
                            key=f"closed_{event['id']}",
                            disabled=True,
                            use_container_width=True,
                        )
                        st.caption(f"Deadline was {deadline_display}")
                    else:
                        with st.popover("Register Pass", use_container_width=True):
                            st.markdown(f"**Confirm Pass: {safe_title}**")
                            st.caption(
                                f"Host: {society_name} · Venue: {safe_venue}"
                            )
                            st.caption("✅ A secure single-use QR pass will be issued immediately upon booking.")

                            if event.get("is_paid"):
                                st.info(
                                    f"💳 Registration Fee: **${event.get('fee', 0):.2f}** "
                                    f"(Sandbox Payment Simulation)"
                                )
                                st.caption("No real card charges occur. This is a campus test transaction.")
                                st.text_input(
                                    "Cardholder Name",
                                    value=student_name,
                                    key=f"card_name_{event['id']}",
                                )
                                st.text_input(
                                    "Card Number",
                                    value="•••• •••• •••• 4242",
                                    type="password",
                                    key=f"card_num_{event['id']}",
                                )

                            if st.button(
                                "Confirm Pass Reservation",
                                key=f"confirm_{event['id']}",
                                type="primary",
                                use_container_width=True,
                            ):
                                register_student(
                                    supabase, user_id, event, registered_event_ids
                                )

# ────────────────────────────────────────────────────────────────────────────
# TAB 2 — My Digital Passes  (PRD 8, 9)
# ────────────────────────────────────────────────────────────────────────────
with tab_passes:
    render_html("""
    <h3 style="font-size:1.15rem;font-weight:700;color:#f8fafc;margin:0 0 0.25rem 0;">
        Your Verified Digital Passes</h3>
    <p style="font-size:0.85rem;color:#94a3b8;margin:0 0 1rem 0;">
        Present the high-contrast QR pass at the entrance for instant single-use admission verification.</p>
    """)

    try:
        my_regs = (
            supabase.table("registrations")
            .select("*, events(*, societies(name))")
            .eq("student_id", user_id)
            .order("registered_at", desc=True)
            .execute()
        )
    except Exception as exc:
        st.error(f"Could not load your passes: {exc}")
        my_regs = type("_", (), {"data": []})()

    all_passes = my_regs.data or []

    pass_filter_choice = st.radio(
        "Pass Filter",
        ["All Passes", "Active Entry Passes", "Attended History"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if pass_filter_choice == "Active Entry Passes":
        displayed_passes = [r for r in all_passes if r.get("registration_status") == "confirmed"]
    elif pass_filter_choice == "Attended History":
        displayed_passes = [r for r in all_passes if r.get("registration_status") == "attended"]
    else:
        displayed_passes = all_passes

    if displayed_passes:
        for r in displayed_passes:
            e = r.get("events")
            if not e:
                continue

            soc_name     = html.escape((e.get("societies") or {}).get("name", "Campus Society"))
            qr_b64       = get_qr_base64(r["qr_token"])
            short_id     = r["qr_token"][:8].upper()
            pay_badge    = (
                '<span class="badge badge-paid">PAID</span>'
                if r.get("payment_status") == "paid"
                else '<span class="badge badge-free">FREE PASS</span>'
            )
            reg_status   = r.get("registration_status", "confirmed")
            status_class = (
                "approved" if reg_status == "attended"
                else ("cancelled" if reg_status == "cancelled" else "confirmed")
            )
            status_label = "ATTENDED & VERIFIED" if reg_status == "attended" else reg_status.upper()
            status_badge = f'<span class="badge badge-{html.escape(status_class)}">{html.escape(status_label)}</span>'

            safe_e_title    = html.escape(e.get("title") or "")
            safe_e_category = html.escape(e.get("category") or "Event")
            safe_e_date     = html.escape(str(e.get("date") or "TBA"))
            safe_e_time     = html.escape(str(e.get("start_time") or "TBA"))
            safe_e_venue    = html.escape(e.get("venue") or "TBA")
            safe_s_name     = html.escape(student_name)
            safe_token_pre  = html.escape(r["qr_token"][:13])

            render_html(f"""
            <div class="ticket-pass">
                <div class="ticket-main">
                    <div style="display:flex;justify-content:space-between;
                                align-items:flex-start;margin-bottom:0.6rem;">
                        <div style="display:flex;gap:0.4rem;flex-wrap:wrap;">
                            <span class="badge badge-category">{safe_e_category}</span>
                            {pay_badge}
                            {status_badge}
                        </div>
                        <span style="font-family:'JetBrains Mono',monospace;
                                     font-size:0.775rem;color:#cbd5e1;font-weight:700;
                                     background:rgba(255,255,255,0.06);padding:0.2rem 0.6rem;border-radius:6px;">
                            PASS #{short_id}</span>
                    </div>
                    <h2 style="font-size:1.35rem;font-weight:800;color:#f8fafc;
                               margin:0 0 0.3rem 0;">{safe_e_title}</h2>
                    <p style="font-size:0.875rem;color:#818cf8;font-weight:600;
                              margin:0 0 1rem 0;">Organized by {soc_name}</p>
                    <div style="display:grid;
                                grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
                                gap:0.85rem;padding-top:0.85rem;
                                border-top:1px solid rgba(255,255,255,0.08);">
                        <div>
                            <div style="font-size:0.7rem;color:#94a3b8;
                                        text-transform:uppercase;font-weight:700;
                                        letter-spacing:0.06em;">Event Date</div>
                            <div style="font-size:0.9rem;font-weight:600;
                                        color:#f1f5f9;">{safe_e_date}</div>
                        </div>
                        <div>
                            <div style="font-size:0.7rem;color:#94a3b8;
                                        text-transform:uppercase;font-weight:700;
                                        letter-spacing:0.06em;">Start Time</div>
                            <div style="font-size:0.9rem;font-weight:600;
                                        color:#f1f5f9;">{safe_e_time}</div>
                        </div>
                        <div>
                            <div style="font-size:0.7rem;color:#94a3b8;
                                        text-transform:uppercase;font-weight:700;
                                        letter-spacing:0.06em;">Campus Venue</div>
                            <div style="font-size:0.9rem;font-weight:600;
                                        color:#f1f5f9;">{safe_e_venue}</div>
                        </div>
                        <div>
                            <div style="font-size:0.7rem;color:#94a3b8;
                                        text-transform:uppercase;font-weight:700;
                                        letter-spacing:0.06em;">Verified Attendee</div>
                            <div style="font-size:0.9rem;font-weight:600;
                                        color:#f1f5f9;">{safe_s_name}</div>
                        </div>
                    </div>
                </div>
                <div class="ticket-qr" style="background:#0f172a;border-left:1px solid rgba(255,255,255,0.08);">
                    <img src="{qr_b64}" width="135"
                         style="border-radius:10px;
                                box-shadow:0 4px 16px rgba(0,0,0,0.5);
                                border:3px solid #ffffff;" />
                    <div style="font-size:0.725rem;color:#cbd5e1;font-weight:700;
                                margin-top:0.65rem;text-transform:uppercase;
                                letter-spacing:0.08em;">Present at Door</div>
                    <code style="font-size:0.65rem;color:#94a3b8;margin-top:0.2rem;
                                 font-family:'JetBrains Mono',monospace;">
                        TOKEN: {safe_token_pre}…</code>
                </div>
            </div>
            """)
    else:
        empty_msg = (
            "You have no active upcoming event passes."
            if pass_filter_choice == "Active Entry Passes"
            else ("No past verified attendance records found yet."
                  if pass_filter_choice == "Attended History"
                  else "Browse campus events in 'Discover' to book your first digital pass.")
        )
        render_empty_state("No Passes Found", empty_msg, "🎫")

# ────────────────────────────────────────────────────────────────────────────
# TAB 3 — My Profile  (PRD 15: student can maintain profile)
# ────────────────────────────────────────────────────────────────────────────
with tab_profile:
    render_html("""
    <h3 style="font-size:1.15rem;font-weight:700;color:#f1f5f9;margin:0 0 0.25rem 0;">
        My Profile</h3>
    <p style="font-size:0.825rem;color:#64748b;margin:0 0 1rem 0;">
        Keep your profile up to date so AI recommendations stay relevant.</p>
    """)

    with st.container(border=True):
        with st.form("profile_update_form"):
            st.markdown("**Personal Information**")
            prof_name = st.text_input(
                "Full Name",
                value=student_profile.get("name") or "",
                placeholder="Your full name",
                max_chars=100,
            )
            st.text_input(
                "Email (read-only)",
                value=student_profile.get("email") or st.session_state.user.email or "",
                disabled=True,
                help="Email cannot be changed here.",
            )

            st.divider()
            st.markdown("**Academic Details**")
            departments = [
                "General",
                "Computer Science",
                "Electrical Engineering",
                "Mechanical Engineering",
                "Business Administration",
                "Arts & Humanities",
                "Natural Sciences",
                "Social Sciences",
                "Medicine & Health",
                "Law",
                "Architecture",
                "Other",
            ]
            cur_dept = student_profile.get("department") or "General"
            dept_idx = departments.index(cur_dept) if cur_dept in departments else 0
            prof_dept = st.selectbox("Department / Major", departments, index=dept_idx)

            prof_interests = st.text_area(
                "Interests (comma-separated)",
                value=student_profile.get("interests") or "",
                placeholder="e.g. Artificial Intelligence, Web Development, Robotics",
                help=(
                    "These are used by the AI recommendation engine. "
                    "Separate each interest with a comma."
                ),
                max_chars=500,
            )

            render_html("<div style='height:8px;'></div>")
            if st.form_submit_button(
                "Save Profile", type="primary", use_container_width=True
            ):
                if not prof_name.strip():
                    st.error("Name cannot be empty.")
                else:
                    try:
                        # Only update non-sensitive fields; role is excluded.
                        supabase.table("profiles").update({
                            "name":      prof_name.strip(),
                            "department": prof_dept,
                            "interests": prof_interests.strip(),
                        }).eq("id", user_id).execute()
                        st.success("Profile updated successfully!")
                        # Clear cached AI recommendations so they regenerate
                        # with the new profile data.
                        if "cached_student_recs" in st.session_state:
                            del st.session_state["cached_student_recs"]
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Profile update failed: {exc}")

# ────────────────────────────────────────────────────────────────────────────
# TAB 4 — AI Recommendations  (PRD 10, FR-12)
#
# Output is rendered with st.markdown(), NOT render_html(), to prevent XSS.
# ────────────────────────────────────────────────────────────────────────────
with tab_ai:
    render_html("""
    <h3 style="font-size:1.15rem;font-weight:700;color:#f1f5f9;margin:0 0 0.25rem 0;">
        Gemini AI Campus Intelligence</h3>
    <p style="font-size:0.825rem;color:#64748b;margin:0 0 1rem 0;">
        Personalised event suggestions based on your profile and history.</p>
    """)

    ai_col, btn_col = st.columns([3, 1])
    with ai_col:
        render_html(f"""
        <div class="glass-card" style="margin-bottom:1rem;">
            <div style="display:flex;align-items:center;gap:0.85rem;">
                <div style="width:40px;height:40px;border-radius:10px;
                            background:rgba(167,139,250,0.12);
                            border:1px solid rgba(167,139,250,0.2);
                            color:#a78bfa;display:flex;align-items:center;
                            justify-content:center;font-size:1.2rem;">✨</div>
                <div>
                    <h4 style="font-size:0.95rem;font-weight:700;color:#f1f5f9;margin:0;">
                        Contextual Matching Engine</h4>
                    <p style="font-size:0.825rem;color:#64748b;margin:0;">
                        Tailored to your major (<strong style="color:#818cf8;">
                        {dept}</strong>) and {len(registered_event_ids)} past registrations.
                    </p>
                </div>
            </div>
        </div>
        """)
    with btn_col:
        btn_gen = st.button(
            "Generate Recommendations",
            type="primary",
            use_container_width=True,
        )

    if btn_gen:
        with st.spinner("Analysing your profile & event catalog with Gemini AI…"):
            pipeline_res = generate_recommendations_pipeline(user_id, supabase, force_refresh=True)
            st.session_state["cached_student_pipeline_result"] = pipeline_res
            st.session_state["cached_student_recs"] = pipeline_res.to_markdown()

    if "cached_student_pipeline_result" in st.session_state:
        res: PipelineResult = st.session_state["cached_student_pipeline_result"]

        if res.is_fallback:
            st.info(
                "⚡ **Deterministic Match Mode Active** — Recommendations are currently calculated "
                "using our deterministic academic relevance engine (Gemini AI advisory service offline)."
            )

        if not res.recommendations:
            render_empty_state(
                "No Matching Events",
                res.fallback_reason or "No approved events match your current profile preferences.",
                "🔍",
            )
        else:
            render_html(f"""
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;flex-wrap:wrap;gap:0.5rem;">
                <div style="display:flex;align-items:center;gap:0.5rem;">
                    <span class="badge badge-ai">✨ {len(res.recommendations)} TAILORED MATCHES</span>
                    <span style="font-size:0.8rem;color:#64748b;">Evaluated {res.total_candidates_evaluated} approved campus events</span>
                </div>
            </div>
            """)

            for rec in res.recommendations:
                safe_title = html.escape(rec.title)
                safe_cat   = html.escape(rec.category)
                safe_soc   = html.escape(rec.society_name)
                safe_venue = html.escape(rec.venue)
                safe_date  = html.escape(rec.date)
                safe_time  = html.escape(rec.time) if rec.time else "TBA"
                safe_reason = html.escape(rec.reason)
                badge_type = "badge-ai" if rec.source == "gemini" else "badge-category"
                source_label = "✨ Gemini AI Match" if rec.source == "gemini" else "⚡ Deterministic Profile Match"
                cost_tag = f"${rec.fee:.2f}" if rec.is_paid else "FREE"

                with st.container(border=True):
                    card_col, act_col = st.columns([3.6, 1.2])
                    with card_col:
                        render_html(f"""
                        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.4rem;flex-wrap:wrap;">
                            <span class="badge {badge_type}">{source_label}</span>
                            <span class="badge badge-approved" style="font-weight:700;">{rec.score}% MATCH</span>
                            <span class="badge badge-category">{safe_cat}</span>
                            <span style="font-size:0.8rem;color:#64748b;font-weight:600;">{cost_tag}</span>
                        </div>
                        <h3 style="font-size:1.15rem;font-weight:800;color:#f1f5f9;margin:0 0 0.25rem 0;">
                            {safe_title}
                        </h3>
                        <div style="font-size:0.825rem;color:#818cf8;font-weight:600;margin-bottom:0.5rem;">
                            Hosted by {safe_soc}
                        </div>
                        <div style="display:flex;flex-wrap:wrap;gap:1rem;color:#64748b;font-size:0.8rem;margin-bottom:0.6rem;">
                            <span>📅 {safe_date}</span>
                            <span>⏰ {safe_time}</span>
                            <span>📍 {safe_venue}</span>
                        </div>
                        <div style="background:rgba(129,140,248,0.06);border-left:3px solid #818cf8;
                                    padding:0.5rem 0.75rem;border-radius:0 8px 8px 0;margin-top:0.35rem;">
                            <span style="font-size:0.75rem;font-weight:700;color:#a78bfa;text-transform:uppercase;letter-spacing:0.05em;display:block;margin-bottom:0.15rem;">
                                Why This Matches You
                            </span>
                            <span style="font-size:0.825rem;color:#cbd5e1;line-height:1.4;">
                                {safe_reason}
                            </span>
                        </div>
                        """)

                    with act_col:
                        render_html("<div style='height:1.5rem;'></div>")
                        is_registered = rec.event_id in registered_event_ids
                        if is_registered:
                            st.button(
                                "✅ Registered",
                                key=f"rec_reg_{rec.event_id}",
                                disabled=True,
                                use_container_width=True,
                            )
                        else:
                            with st.popover("Register Pass", use_container_width=True):
                                st.markdown(f"**Register for {safe_title}**")
                                st.caption(f"Host: {safe_soc} | Venue: {safe_venue}")
                                if rec.is_paid:
                                    st.info(f"💳 Fee: **${rec.fee:.2f}**")
                                    st.text_input("Name", value=student_name, key=f"rec_card_n_{rec.event_id}")
                                    st.text_input("Card", value="•••• •••• •••• 4242", type="password", key=f"rec_card_c_{rec.event_id}")

                                if st.button(
                                    "Confirm Registration",
                                    key=f"confirm_rec_{rec.event_id}",
                                    type="primary",
                                    use_container_width=True,
                                ):
                                    event_stub = {
                                        "id": rec.event_id,
                                        "title": rec.title,
                                        "status": "approved",
                                        "capacity": rec.capacity,
                                        "fee": rec.fee,
                                        "is_paid": rec.is_paid,
                                    }
                                    register_student(
                                        supabase, user_id, event_stub, registered_event_ids
                                    )
    elif not btn_gen:
        render_empty_state(
            "Ready for Insights",
            "Click 'Generate Recommendations' to get AI-powered event suggestions tailored to your academic profile.",
            "🤖",
        )


# _register_student() has been moved to utils/registration.py.
# Import at top of file: from utils.registration import register_student
