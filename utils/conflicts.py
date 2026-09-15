"""
utils/conflicts.py — Deterministic Venue & Schedule Conflict Detection Engine.

Design Principles
-----------------
1. AI MUST NOT control critical business rules:
   Venue conflict detection is 100% DETERMINISTIC. The mathematical overlap
   algorithm is the authoritative source of truth.
2. Gemini AI is used SOLELY to provide natural-language explanation and
   advisory rescheduling suggestions when a conflict is deterministically found.
3. If Gemini is unavailable, rate-limited, or times out, the system continues
   seamlessly using deterministic explanations.
4. Zero PII, secrets, or auth tokens are ever passed to Gemini.

Mathematical Definition of Conflict
-----------------------------------
Two events A and B conflict if and only if:
  1. normalize(A.venue) == normalize(B.venue)
  2. A.date == B.date
  3. Half-open intervals [S_A, E_A) and [S_B, E_B) overlap:
     max(S_A, S_B) < min(E_A, E_B)  <=>  (S_A < E_B) and (S_B < E_A)

Boundary Cases:
  A: 10:00–12:00, B: 11:00–13:00 -> CONFLICT (overlap = 60 mins)
  A: 10:00–12:00, B: 12:00–14:00 -> NO CONFLICT (boundary adjacency)
  A: 10:00–12:00, B: 08:00–10:00 -> NO CONFLICT (boundary adjacency)
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Optional

import google.generativeai as genai

logger = logging.getLogger(__name__)

DEFAULT_EVENT_DURATION_MINUTES = 120  # Fallback duration if end_time is not specified


@dataclass
class ConflictingEvent:
    event_id: str
    title: str
    venue: str
    date: str
    start_time: str
    end_time: str
    status: str
    overlap_minutes: int


@dataclass
class ConflictReport:
    has_conflict: bool
    conflicts: list[ConflictingEvent] = field(default_factory=list)
    summary: str = "No scheduling conflicts detected."
    ai_explanation: Optional[str] = None


def normalize_venue(venue: Optional[str]) -> str:
    """Normalize venue string for robust matching."""
    if not venue:
        return ""
    return re.sub(r"\s+", " ", venue.strip().lower())


def parse_time_to_minutes(t_val: Any) -> Optional[int]:
    """
    Convert a time object or string (HH:MM or HH:MM:SS) to minutes from midnight.
    Returns None if parsing fails.
    """
    if t_val is None:
        return None

    if isinstance(t_val, time):
        return t_val.hour * 60 + t_val.minute

    if isinstance(t_val, str):
        t_str = t_val.strip()
        if not t_str:
            return None
        # Handle formats like "14:30", "14:30:00", "02:30 PM", "2:30 PM"
        try:
            parts = t_str.split(":")
            if len(parts) >= 2:
                hour = int(parts[0])
                min_part = parts[1].split()[0]
                minute = int(min_part)
                if "pm" in t_str.lower() and hour < 12:
                    hour += 12
                elif "am" in t_str.lower() and hour == 12:
                    hour = 0
                return hour * 60 + minute
        except Exception:
            pass

        # Fallback to datetime.strptime
        for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
            try:
                dt = datetime.strptime(t_str, fmt)
                return dt.hour * 60 + dt.minute
            except ValueError:
                continue

    return None


def format_minutes_to_time(minutes: int) -> str:
    """Format minutes from midnight to HH:MM string."""
    h = (minutes // 60) % 24
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def check_time_interval_overlap(
    start_a: int,
    end_a: int,
    start_b: int,
    end_b: int,
) -> tuple[bool, int]:
    """
    Check if half-open intervals [start_a, end_a) and [start_b, end_b) overlap.
    Returns:
        (has_overlap, overlap_duration_in_minutes)
    """
    overlap_start = max(start_a, start_b)
    overlap_end = min(end_a, end_b)

    if overlap_start < overlap_end:
        return True, overlap_end - overlap_start
    return False, 0


def detect_schedule_conflict(
    proposed_venue: str,
    proposed_date: Any,
    proposed_start_time: Any,
    proposed_end_time: Any = None,
    existing_events: Optional[list[dict]] = None,
    exclude_event_id: Optional[str] = None,
    include_statuses: tuple[str, ...] = ("approved",),
) -> ConflictReport:
    """
    Deterministically check if a proposed event conflicts with existing events.

    Parameters
    ----------
    proposed_venue : str
        Target venue or room name.
    proposed_date : date or str
        Event date.
    proposed_start_time : time or str
        Event start time.
    proposed_end_time : time or str, optional
        Event end time (if None, defaults to start + 2 hours).
    existing_events : list of dict, optional
        Events list to compare against.
    exclude_event_id : str, optional
        UUID of the event being updated (to avoid self-conflict).
    include_statuses : tuple of str
        Statuses that reserve the venue (default: ('approved',)).

    Returns
    -------
    ConflictReport
    """
    norm_proposed_venue = normalize_venue(proposed_venue)
    if not norm_proposed_venue:
        return ConflictReport(has_conflict=False, summary="No venue specified.")

    norm_proposed_date = str(proposed_date).strip()
    p_start_min = parse_time_to_minutes(proposed_start_time)
    if p_start_min is None:
        return ConflictReport(has_conflict=False, summary="Invalid or missing start time.")

    p_end_min = parse_time_to_minutes(proposed_end_time)
    if p_end_min is None or p_end_min <= p_start_min:
        p_end_min = p_start_min + DEFAULT_EVENT_DURATION_MINUTES

    if not existing_events:
        return ConflictReport(has_conflict=False, summary="No existing events to check.")

    conflicts: list[ConflictingEvent] = []

    for ev in existing_events:
        ev_id = str(ev.get("id") or "")
        if exclude_event_id and ev_id == str(exclude_event_id):
            continue

        status = str(ev.get("status") or "").lower()
        if status not in include_statuses:
            continue

        ev_venue = normalize_venue(ev.get("venue"))
        if ev_venue != norm_proposed_venue:
            continue

        ev_date = str(ev.get("date") or "").strip()
        if ev_date != norm_proposed_date:
            continue

        ev_start_min = parse_time_to_minutes(ev.get("start_time"))
        if ev_start_min is None:
            continue

        ev_end_min = parse_time_to_minutes(ev.get("end_time"))
        if ev_end_min is None or ev_end_min <= ev_start_min:
            ev_end_min = ev_start_min + DEFAULT_EVENT_DURATION_MINUTES

        has_overlap, overlap_mins = check_time_interval_overlap(
            p_start_min, p_end_min, ev_start_min, ev_end_min
        )

        if has_overlap:
            conflicts.append(
                ConflictingEvent(
                    event_id=ev_id,
                    title=str(ev.get("title") or "Untitled Event"),
                    venue=str(ev.get("venue") or proposed_venue),
                    date=ev_date,
                    start_time=format_minutes_to_time(ev_start_min),
                    end_time=format_minutes_to_time(ev_end_min),
                    status=status,
                    overlap_minutes=overlap_mins,
                )
            )

    if not conflicts:
        return ConflictReport(
            has_conflict=False,
            summary=f"Venue '{proposed_venue}' is available on {norm_proposed_date} from {format_minutes_to_time(p_start_min)} to {format_minutes_to_time(p_end_min)}.",
        )

    lines = [f"⚠️ Schedule Conflict Detected ({len(conflicts)} collision{'s' if len(conflicts)>1 else ''}):"]
    for c in conflicts:
        lines.append(
            f"• '{c.title}' is booked at {c.venue} on {c.date} from {c.start_time} to {c.end_time} "
            f"({c.overlap_minutes} min overlap)."
        )

    return ConflictReport(
        has_conflict=True,
        conflicts=conflicts,
        summary="\n".join(lines),
    )


# In-memory cache for conflict explanations to prevent redundant Gemini API calls
_CONFLICT_AI_CACHE: dict[str, str] = {}


def explain_conflict_with_ai(
    report: Optional[ConflictReport] = None,
    proposed_title: str = "Proposed Event",
    proposed_venue: str = "Venue",
    proposed_date: str = "",
    proposed_start: str = "",
    proposed_end: str = "",
    proposed_event: Optional[dict] = None,
    conflicts: Optional[list[ConflictingEvent]] = None,
    timeout_seconds: float = 6.0,
) -> str:
    """
    Generate an advisory natural-language explanation and actionable suggestions
    using Gemini AI. If Gemini fails or times out, returns a clear deterministic explanation.
    Never exposes API keys or secrets. Supports caching and polymorphic kwargs.
    """
    # Normalize input parameters if proposed_event dict was passed
    if proposed_event is not None and isinstance(proposed_event, dict):
        proposed_title = proposed_event.get("title") or proposed_title
        proposed_venue = proposed_event.get("venue") or proposed_venue
        proposed_date  = str(proposed_event.get("date") or proposed_date)
        proposed_start = str(proposed_event.get("start_time") or proposed_start)
        proposed_end   = str(proposed_event.get("end_time") or proposed_end)

    active_conflicts: list[ConflictingEvent] = []
    if report is not None and report.has_conflict and report.conflicts:
        active_conflicts = report.conflicts
    elif conflicts:
        active_conflicts = conflicts

    if not active_conflicts:
        return "No scheduling conflicts detected."

    first_conflict = active_conflicts[0]
    deterministic_fallback = (
        f"Conflict Notice: {proposed_venue} is already reserved on {proposed_date} during your requested time "
        f"({proposed_start} – {proposed_end}). Conflicting booking: '{first_conflict.title}' "
        f"from {first_conflict.start_time} to {first_conflict.end_time} "
        f"({first_conflict.overlap_minutes} mins overlap). "
        f"Suggestion: Adjust your start time to {first_conflict.end_time} or book an alternate hall."
    )

    # Check in-memory cache to prevent redundant expensive API calls
    conflict_ids = ",".join(str(getattr(c, "event_id", id(c))) for c in active_conflicts)
    cache_key = f"{proposed_title}|{proposed_venue}|{proposed_date}|{proposed_start}|{proposed_end}|{conflict_ids}"
    if cache_key in _CONFLICT_AI_CACHE:
        return _CONFLICT_AI_CACHE[cache_key]

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        _CONFLICT_AI_CACHE[cache_key] = deterministic_fallback
        return deterministic_fallback

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        safe_title = re.sub(r"[<>{}\[\]`]", "", str(proposed_title))[:80]
        safe_venue = re.sub(r"[<>{}\[\]`]", "", str(proposed_venue))[:60]
        safe_date = re.sub(r"[<>{}\[\]`]", "", str(proposed_date))[:20]

        conflict_descriptions = []
        for c in active_conflicts:
            c_title = re.sub(r"[<>{}\[\]`]", "", str(getattr(c, "title", "")))[:80]
            c_venue = str(getattr(c, "venue", ""))
            c_date = str(getattr(c, "date", ""))
            c_start = str(getattr(c, "start_time", ""))
            c_end = str(getattr(c, "end_time", ""))
            c_overlap = getattr(c, "overlap_minutes", 0)
            conflict_descriptions.append(
                f"- Existing Event: '{c_title}' in {c_venue} on {c_date} from {c_start} to {c_end} ({c_overlap} min overlap)"
            )

        prompt = f"""You are an intelligent campus facility coordinator.
A scheduling conflict was deterministically detected for a campus event proposal.

<conflict_data>
Proposed Event: {safe_title}
Venue: {safe_venue}
Date: {safe_date}
Time: {proposed_start} - {proposed_end}

Existing Bookings with Overlap:
{chr(10).join(conflict_descriptions)}
</conflict_data>

Task:
In 2 concise, polite sentences:
1. Explain the exact schedule conflict and the overlap duration.
2. Provide an actionable recommendation (such as suggesting a specific alternate time slot after the existing event ends or selecting another room).
Do not use markdown headers. Keep it professional and direct."""

        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.2, "top_p": 0.8, "max_output_tokens": 256},
            request_options={"timeout": timeout_seconds},
        )
        text = getattr(response, "text", None)
        if text and text.strip():
            result = text.strip()
            _CONFLICT_AI_CACHE[cache_key] = result
            return result
    except Exception as exc:
        logger.warning("Gemini conflict explanation failed (%s); using deterministic fallback.", exc)

    _CONFLICT_AI_CACHE[cache_key] = deterministic_fallback
    return deterministic_fallback

