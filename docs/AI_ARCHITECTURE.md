# Smart Campus AI Layer Architecture

## CampusPulse · Intelligent Campus Society & Event Management System

---

## 1. Executive Summary & Core Architectural Axiom

> **Architectural Axiom:**  
> **"AI must enhance the system, not control critical business rules."**

In the CampusPulse platform, Gemini AI operates as an **advisory and explanatory copilot**, never as an authoritative controller of system state, access control, or scheduling validity:

- **Business Rules are 100% Deterministic:** Database RLS policies, PostgreSQL triggers, atomic RPCs, and mathematical interval algorithms make all binding decisions (event approval status, registration capacity, attendance validation, and venue double-booking prevention).
- **Gemini Enhances Experience:** Gemini provides contextual understanding, personalized linguistic reasoning ("Why this matches you"), and natural-language rescheduling advice.
- **Resilience First:** If Gemini experiences downtime, timeouts, rate limits, or network failures, the platform continues functioning smoothly with zero degraded features via deterministic fallback engines.
- **Zero-Trust Security:** Gemini output is treated as untrusted data; every identifier is validated against authoritative database records before reaching the user interface.

---

## 2. Architecture Overview Diagram

```mermaid
flowchart TD
    subgraph ClientLayer [Client & Dashboard Layer]
        SD[Student Hub Dashboard]
        SocD[Society Head Dashboard]
        AD[University Admin Console]
    end

    subgraph RecPipeline [AI Recommendation Pipeline (utils/ai_recs.py)]
        S1[1. Student Context Aggregator\n• Department & Interests\n• Past Registrations\n• Confirmed Attendance\n• ZERO PII Guarantee]
        S2[2. Candidate Event Filter\n• Query status = 'approved'\n• Exclude already registered\n• Filter upcoming dates]
        S3[3. Deterministic Relevance Scorer\n• Jaccard Token Match (35 pts)\n• Department Affinity (25 pts)\n• Past History Match (15 pts)\n• Attendance Bonus (10 pts)\n• Popularity & Timeliness (15 pts)]
        S4[4. Gemini Ranking & Reasoner\n• Isolated XML Boundaries\n• Token Neutralization\n• JSON Schema Enforcement\n• Multi-Model Timeout Fallback]
        S5[5. Strict Output Validator\n• Verify event_id in approved map\n• Discard fake/rejected/cancelled IDs\n• Deduplicate & Clamp Scores\n• Deterministic Backfill]
    end

    subgraph ConflictEngine [Deterministic Venue Conflict Engine (utils/conflicts.py)]
        CE[Deterministic Overlap Engine\n• Same Venue (normalized)\n• Same Date\n• max(S_A, S_B) < min(E_A, E_B)\n• Half-open interval boundary precision]
        C_AI[Gemini Conflict Explainer\n• Natural language summary\n• Actionable rescheduling advice\n• Deterministic text fallback]
    end

    SD --> S1 --> S2 --> S3
    S3 -->|Top 10 Candidates Pool| S4
    S4 -->|Structured JSON Output| S5
    S4 -.->|Timeout / Quota / Bad JSON| S3
    S5 -->|Validated Rich Cards| SD

    SocD -->|Propose / Edit Event| CE
    AD -->|Review Pending Proposal| CE
    CE -->|Conflict Result| C_AI
    C_AI -->|Conflict Warning Banner| SocD
    C_AI -->|Conflict Status Badge| AD
```

---

## 3. Feature 1: Event Recommendation Pipeline

The recommendation pipeline runs in 6 modular stages:

### Stage 1: Student Context Aggregator (Zero PII)
- Queries student profile (`department`, `interests`), past registered event categories, and physically attended events (`attendance.status = 'valid'`).
- **PII Minimization Guarantee:** Student names, student emails, student UUIDs, phone numbers, and session tokens are **never** passed to the Gemini API or logged. Only academic context (department, sanitized interest tokens, past category preferences) is processed.

### Stage 2: Authoritative Candidate Filtering
- Authoritative query against Supabase `events` table:
  - `status == 'approved'` (strictly excludes `pending`, `rejected`, `cancelled`, `completed`).
  - `date >= today` (upcoming events only).
  - Excludes events the student has already registered for.
- Builds an in-memory authoritative lookup table:
  $$\text{ApprovedCandidates} = \{ \text{id} \mapsto \text{EventData} \}$$

### Stage 3: Deterministic Relevance Scoring
Every candidate is deterministically evaluated using an explainable multi-factor scoring model ($0$ to $100$ points):

$$\text{Score} = \text{InterestMatch} + \text{DeptAffinity} + \text{PastRegMatch} + \text{AttendanceBonus} + \text{PopularityTimeliness}$$

1. **Interest Token Overlap ($0 - 35$ pts):** Normalized token overlap between student interests and event title, description, and tags.
2. **Department Affinity ($0 - 25$ pts):** Category or hosting society matches student's academic department ($+25$), or campus-wide category ($+15$).
3. **Past Registration History ($0 - 15$ pts):** Student previously registered for events in this category.
4. **Attendance Engagement Bonus ($0 - 10$ pts):** Bonus if the student physically attended events in this category (proven real-world engagement).
5. **Popularity & Timeliness ($0 - 15$ pts):** Up to $+10$ based on registration count, and $+5$ if occurring within the next 14 days.

Top $N$ candidates (default 8–10) are selected for Gemini analysis, drastically cutting latency and token consumption.

### Stage 4: Gemini AI Ranking Assistance & Structured Reasoner
- The pruned candidate list is formatted into a prompt wrapped in isolated XML boundary tags:
  ```xml
  <student_context>
  Department: Computer Science
  Interests: AI, Machine Learning, Robotics
  </student_context>

  <candidate_events>
  [
    {"event_id": "...", "title": "...", "category": "...", "description": "..."}
  ]
  </candidate_events>
  ```
- **Strict Output Schema:** The model is instructed to output **only** valid JSON:
  ```json
  [
    {
      "event_id": "<exact_uuid>",
      "score": 94,
      "reason": "Directly matches your interest in Robotics and aligns with your Computer Science department."
    }
  ]
  ```
- Multi-model sequence: `gemini-1.5-flash` $\rightarrow$ `gemini-1.5-pro` $\rightarrow$ `gemini-2.0-flash`.

### Stage 5: Strict Output Validation & Backfill
To enforce the principle **"Do not blindly trust arbitrary Gemini output"**:
1. **Identifier Verification:** For every item in the JSON output, `rec["event_id"]` is verified against $\text{ApprovedCandidates}$. If an ID does not exist in the dictionary, it is **instantly discarded**. Gemini cannot hallucinate events, resurrect rejected events, or expose unapproved events.
2. **Deduplication:** Repeated event IDs are filtered out.
3. **Score Clamping:** Match score is clamped to $[20, 99]$.
4. **Resilience Backfill:** If Gemini fails, times out, or returns fewer recommendations than requested, the pipeline seamlessly backfills from the top deterministic scored candidates.

### Stage 6: UI Presentation
- In `3_Student_Dashboard.py`, recommendations are displayed as glassmorphic cards with:
  - Match percentage badge (`96% MATCH`).
  - Source badge (`✨ Gemini AI Match` vs `⚡ Deterministic Profile Match`).
  - Personalized explanation box ("Why This Matches You").
  - Instant 1-click registration popover wired to atomic RPC `register_student`.

---

## 4. Feature 2: Deterministic Venue & Schedule Conflict Engine

### Mathematical Conflict Formulation
Two events $A$ and $B$ conflict if and only if:
1. $\text{normalize}(A.\text{venue}) == \text{normalize}(B.\text{venue})$
2. $A.\text{date} == B.\text{date}$
3. Half-open time intervals $[S_A, E_A)$ and $[S_B, E_B)$ overlap:
   $$\max(S_A, S_B) < \min(E_A, E_B) \iff (S_A < E_B) \land (S_B < E_A)$$

### Overlap Duration
$$\text{OverlapMinutes} = \max(0, \min(E_A, E_B) - \max(S_A, S_B))$$

### Boundary Condition Precision
| Scenario | Event A | Event B | Overlap Check | Result |
| :--- | :--- | :--- | :--- | :--- |
| **Standard Overlap** | 10:00 – 12:00 | 11:00 – 13:00 | $\max(10, 11) < \min(12, 13) \implies 11 < 12$ | **CONFLICT (60 min)** |
| **Adjacent Boundary (Start)** | 10:00 – 12:00 | 12:00 – 14:00 | $\max(10, 12) < \min(12, 14) \implies 12 < 12$ (False) | **NO CONFLICT** |
| **Adjacent Boundary (End)** | 10:00 – 12:00 | 08:00 – 10:00 | $\max(8, 10) < \min(10, 12) \implies 10 < 10$ (False) | **NO CONFLICT** |
| **Different Venue** | Hall A (10–12) | Hall B (10–12) | Venues distinct | **NO CONFLICT** |
| **Different Date** | Oct 15 (10–12) | Oct 16 (10–12) | Dates distinct | **NO CONFLICT** |

### Status Awareness
- Only active bookings (`approved`) reserve venue capacity.
- `rejected` and `cancelled` events never cause conflicts.
- Self-event exclusion (`exclude_event_id`) prevents false-positive conflicts when editing an existing event.

### Gemini Rescheduling Explainer
When the deterministic engine flags a conflict, Gemini provides a 2-sentence explanation with polite rescheduling options (e.g. suggesting moving to the end of the existing booking or booking an alternate auditorium). If offline, a deterministic explanation is displayed.

---

## 5. Security & Prompt Injection Defense

1. **PII Redaction:** Student names, emails, avatars, student IDs, and passwords are never incorporated into prompts.
2. **Untrusted Content Sanitization:**
   - User inputs (`interests`, `department`) and society content (`description`, `title`) are sanitized via `_sanitize_for_prompt` to strip delimiters (`< > { } [ ] \ ` `).
   - High-risk injection phrases (`ignore previous instructions`, `system prompt`, `<|im_start|>`) are neutralized.
3. **Structured Isolation:** All external inputs are embedded inside explicit XML boundaries with system warnings commanding the model to treat enclosed text as passive data.
4. **Secrets Isolation:** No API keys, JWT tokens, service role keys, or credentials exist in prompts or logs.

---

## 6. Cost & Performance Optimizations

1. **Pre-Filtering:** Evaluates only upcoming, approved events and removes already-registered events prior to scoring.
2. **Candidate Pruning:** Only the top 8–10 candidate events are passed to Gemini instead of the full database, decreasing token usage by >80%.
3. **Multi-Tier Caching:**
   - In-memory cache keyed by SHA-256 hash of `user_id + interests + candidate_event_ids`.
   - 10-minute TTL prevents repeated Gemini invocations during page reloads or tab navigation.
4. **Deterministic Fallback:** Instant zero-latency response when the model is unavailable or rate-limited.

---

## 7. Testing & Verification Matrix

The test suite in `tests/test_ai_layer.py` and `tests/test_security.py` covers 50 automated tests:

| Test Case | Module | Description | Status |
| :--- | :--- | :--- | :--- |
| `test_gemini_unavailable_fallback` | `test_ai_layer.py` | Graceful deterministic recommendations when Gemini fails | ✅ PASS |
| `test_malformed_gemini_output_handling` | `test_ai_layer.py` | Resilient recovery on invalid JSON / empty responses | ✅ PASS |
| `test_invalid_event_ids_discarded` | `test_ai_layer.py` | Hallucinated UUIDs discarded; valid IDs preserved | ✅ PASS |
| `test_rejected_or_cancelled_events` | `test_ai_layer.py` | Rejected / cancelled events blocked from recommendations | ✅ PASS |
| `test_duplicate_recommendations` | `test_ai_layer.py` | Duplicate event IDs in model response deduplicated | ✅ PASS |
| `test_empty_candidates_handling` | `test_ai_layer.py` | Clean message when no approved events exist | ✅ PASS |
| `test_prompt_injection_neutralized` | `test_ai_layer.py` | Neutralization of injection payloads and brackets | ✅ PASS |
| `test_zero_pii_and_secrets` | `test_ai_layer.py` | Verification that prompts contain zero PII or credentials | ✅ PASS |
| `test_explain_conflict_ai_offline` | `test_ai_layer.py` | Conflict explanation falls back cleanly when offline | ✅ PASS |
| `test_venue_conflict_overlapping` | `test_ai_layer.py` | Overlap (10:00-12:00 vs 11:00-13:00) detected as conflict | ✅ PASS |
| `test_no_conflict_different_venue` | `test_ai_layer.py` | Different venue yields no conflict | ✅ PASS |
| `test_no_conflict_different_date` | `test_ai_layer.py` | Different date yields no conflict | ✅ PASS |
| `test_boundary_time_no_conflict_start` | `test_ai_layer.py` | Adjacent intervals [10:00, 12:00) & [12:00, 14:00) = NO conflict | ✅ PASS |
| `test_boundary_time_no_conflict_end` | `test_ai_layer.py` | Adjacent intervals [08:00, 10:00) & [10:00, 12:00) = NO conflict | ✅ PASS |
| `test_rejected_cancelled_no_conflict` | `test_ai_layer.py` | Rejected/cancelled events do not cause conflicts | ✅ PASS |
| `test_self_event_exclusion` | `test_ai_layer.py` | Editing event ignores self-conflict | ✅ PASS |
| `TestRegistrationErrorMapping` (5 tests) | `test_security.py` | Safe DB error mapping without leaking internals | ✅ PASS |
| `TestPromptInjectionSanitisation` (6 tests)| `test_security.py` | Input sanitization against formatting injection | ✅ PASS |
| `TestDatabaseAttackScenarios` & Rules | `test_security.py` | Full security authorization and schema invariants | ✅ PASS |
