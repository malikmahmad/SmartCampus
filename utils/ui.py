import streamlit as st

def render_html(html_str: str):
    """
    Renders HTML via st.markdown with unsafe_allow_html=True.
    Strips all leading whitespace from every line so CommonMark / React-Markdown
    never misinterprets indented tags after blank lines as code blocks (<pre><code>).
    """
    clean = "\n".join(line.strip() for line in html_str.strip().splitlines() if line.strip())
    st.markdown(clean, unsafe_allow_html=True)


def apply_custom_theme():
    """Injects a premium dark glassmorphism design system — aggressive Streamlit overrides."""
    render_html("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap');

    /* ===== GLOBAL RESETS ===== */
    :root {
        --bg-primary: #0b0f19;
        --bg-secondary: #111827;
        --bg-card: rgba(17, 24, 39, 0.7);
        --bg-glass: rgba(255, 255, 255, 0.03);
        --border-subtle: rgba(255, 255, 255, 0.08);
        --border-glow: rgba(129, 140, 248, 0.25);
        --text-primary: #f8fafc;
        --text-secondary: #cbd5e1;
        --text-muted: #94a3b8;
        --text-tertiary: #64748b;
        --accent-indigo: #818cf8;
        --accent-violet: #a78bfa;
        --accent-emerald: #34d399;
        --accent-amber: #fbbf24;
        --accent-rose: #fb7185;
        --accent-cyan: #22d3ee;
        --gradient-brand: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        --gradient-card: linear-gradient(135deg, rgba(17, 24, 39, 0.8) 0%, rgba(15, 23, 42, 0.9) 100%);
        --shadow-glow: 0 0 30px rgba(129, 140, 248, 0.08);
        --shadow-card: 0 4px 24px rgba(0, 0, 0, 0.3);
        --radius-lg: 16px;
        --radius-md: 12px;
        --radius-sm: 8px;
    }

    html, body, .stApp {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    }
    p, label, li, td, th, input, textarea, select, button {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }

    /* CRITICAL: Preserve Material Symbols and icon fonts so ligatures render as icons, not text */
    .material-symbols-rounded,
    .material-symbols-outlined,
    .material-icons,
    [data-testid="stIconMaterial"],
    [data-testid*="Icon"] span,
    span[data-testid*="Icon"],
    span[class*="material-symbols"] {
        font-family: 'Material Symbols Rounded', 'Material Symbols Outlined', 'Material Icons' !important;
        font-weight: normal !important;
        font-style: normal !important;
        line-height: 1 !important;
        letter-spacing: normal !important;
        text-transform: none !important;
        display: inline-block !important;
        white-space: nowrap !important;
        word-wrap: normal !important;
        direction: ltr !important;
        font-size: 20px !important;
        -webkit-font-feature-settings: 'liga' !important;
        -webkit-font-smoothing: antialiased !important;
    }

    .stApp {
        background: var(--bg-primary) !important;
        background-image:
            radial-gradient(at 20% 20%, rgba(102, 126, 234, 0.08) 0, transparent 50%),
            radial-gradient(at 80% 80%, rgba(118, 75, 162, 0.06) 0, transparent 50%),
            radial-gradient(at 50% 0%, rgba(34, 211, 238, 0.04) 0, transparent 40%) !important;
        background-attachment: fixed !important;
    }

    /* Container */
    .block-container {
        max-width: 1280px !important;
        padding: 1.5rem 2rem 4rem 2rem !important;
    }

    /* ===== HIDE STREAMLIT CHROME ===== */
    #MainMenu, footer, header[data-testid="stHeader"] {
        visibility: hidden !important;
        height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    [data-testid="stSidebarNav"], [data-testid="stSidebar"] {
        display: none !important;
    }
    .stDeployButton { display: none !important; }

    /* ===== ANIMATION KEYFRAMES ===== */
    @keyframes fadeInUp {
        from { opacity: 0; transform: translateY(16px); }
        to { opacity: 1; transform: translateY(0); }
    }
    @keyframes shimmer {
        0% { background-position: -200% center; }
        100% { background-position: 200% center; }
    }
    @keyframes pulseGlow {
        0%, 100% { box-shadow: 0 0 8px rgba(129, 140, 248, 0.15); }
        50% { box-shadow: 0 0 20px rgba(129, 140, 248, 0.3); }
    }
    @keyframes gradientShift {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }

    /* ===== GLASS CARD ===== */
    .glass-card {
        background: var(--gradient-card);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-lg);
        padding: 1.5rem;
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        box-shadow: var(--shadow-card);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        animation: fadeInUp 0.5s ease both;
        position: relative;
        overflow: hidden;
    }
    .glass-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.1), transparent);
    }
    .glass-card:hover {
        border-color: var(--border-glow);
        box-shadow: var(--shadow-glow), var(--shadow-card);
        transform: translateY(-2px);
    }

    /* ===== STREAMLIT CONTAINERS (border=True) ===== */
    [data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"] {
        background: var(--gradient-card) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: var(--radius-lg) !important;
        backdrop-filter: blur(16px) !important;
        box-shadow: var(--shadow-card) !important;
        transition: all 0.3s ease !important;
    }
    [data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlockBorderWrapper"]:hover {
        border-color: var(--border-glow) !important;
        box-shadow: var(--shadow-glow) !important;
    }

    /* ===== TOP NAVIGATION BAR ===== */
    .topbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: rgba(17, 24, 39, 0.85);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-lg);
        padding: 0.75rem 1.5rem;
        margin-bottom: 2rem;
        backdrop-filter: blur(24px);
        box-shadow: 0 2px 16px rgba(0,0,0,0.3);
        animation: fadeInUp 0.3s ease both;
    }
    .topbar-brand {
        display: flex;
        align-items: center;
        gap: 0.75rem;
    }
    .topbar-logo {
        width: 40px; height: 40px;
        border-radius: 12px;
        background: var(--gradient-brand);
        color: #fff;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 800;
        font-size: 1.15rem;
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.35);
        animation: pulseGlow 3s ease infinite;
    }
    .topbar-title {
        font-size: 1.2rem;
        font-weight: 700;
        color: var(--text-primary);
        letter-spacing: -0.02em;
    }
    .topbar-sub {
        font-size: 0.7rem;
        font-weight: 500;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .topbar-user {
        display: flex;
        align-items: center;
        gap: 0.75rem;
    }
    .topbar-avatar {
        width: 36px; height: 36px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 0.85rem;
    }
    .topbar-meta {
        text-align: right;
    }
    .topbar-meta-name {
        font-size: 0.875rem;
        font-weight: 600;
        color: var(--text-primary);
    }
    .topbar-meta-role {
        font-size: 0.65rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    /* ===== PAGE HEADER ===== */
    .hero-section {
        margin-bottom: 2rem;
        animation: fadeInUp 0.4s ease both;
    }
    .hero-tag {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: var(--accent-indigo);
        background: rgba(129, 140, 248, 0.1);
        border: 1px solid rgba(129, 140, 248, 0.2);
        padding: 0.3rem 0.75rem;
        border-radius: 999px;
        margin-bottom: 0.75rem;
    }
    .hero-tag::before {
        content: '';
        width: 6px; height: 6px;
        border-radius: 50%;
        background: var(--accent-indigo);
        box-shadow: 0 0 8px var(--accent-indigo);
    }
    .hero-title {
        font-size: 2rem;
        font-weight: 800;
        color: var(--text-primary);
        letter-spacing: -0.04em;
        line-height: 1.15;
        margin: 0 0 0.5rem 0;
    }
    .hero-desc {
        font-size: 1rem;
        color: var(--text-secondary);
        line-height: 1.6;
        max-width: 650px;
        margin: 0;
    }

    /* ===== KPI STAT CARD ===== */
    .kpi {
        background: var(--gradient-card);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-lg);
        padding: 1.25rem 1.5rem;
        backdrop-filter: blur(16px);
        box-shadow: var(--shadow-card);
        height: 100%;
        position: relative;
        overflow: hidden;
        transition: all 0.3s ease;
        animation: fadeInUp 0.5s ease both;
    }
    .kpi::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 2px;
        background: var(--gradient-brand);
        background-size: 200% 100%;
        animation: gradientShift 4s ease infinite;
    }
    .kpi:hover {
        border-color: var(--border-glow);
        transform: translateY(-3px);
        box-shadow: var(--shadow-glow), 0 8px 32px rgba(0,0,0,0.4);
    }
    .kpi-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 0.75rem;
    }
    .kpi-label {
        font-size: 0.75rem;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .kpi-icon {
        width: 36px; height: 36px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.1rem;
        background: rgba(129, 140, 248, 0.1);
        border: 1px solid rgba(129, 140, 248, 0.15);
    }
    .kpi-value {
        font-family: 'JetBrains Mono', 'Inter', monospace;
        font-size: 2.25rem;
        font-weight: 700;
        color: var(--text-primary);
        line-height: 1;
        margin-bottom: 0.25rem;
    }
    .kpi-sub {
        font-size: 0.75rem;
        color: var(--text-muted);
        font-weight: 500;
    }

    /* ===== BADGES ===== */
    .badge {
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
        padding: 0.2rem 0.65rem;
        border-radius: 999px;
        font-size: 0.675rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        white-space: nowrap;
    }
    .badge-approved, .badge-active, .badge-confirmed, .badge-free {
        background: rgba(52, 211, 153, 0.14);
        color: #34d399;
        border: 1px solid rgba(52, 211, 153, 0.3);
    }
    .badge-pending {
        background: rgba(251, 191, 36, 0.14);
        color: #fbbf24;
        border: 1px solid rgba(251, 191, 36, 0.3);
    }
    .badge-rejected {
        background: rgba(251, 113, 133, 0.14);
        color: #fb7185;
        border: 1px solid rgba(251, 113, 133, 0.3);
    }
    .badge-cancelled, .badge-soldout {
        background: rgba(148, 163, 184, 0.14);
        color: #94a3b8;
        border: 1px solid rgba(148, 163, 184, 0.25);
    }
    .badge-completed {
        background: rgba(167, 139, 250, 0.14);
        color: #a78bfa;
        border: 1px solid rgba(167, 139, 250, 0.3);
    }
    .badge-category, .badge-paid {
        background: rgba(129, 140, 248, 0.14);
        color: #818cf8;
        border: 1px solid rgba(129, 140, 248, 0.3);
    }
    .badge-ai {
        background: linear-gradient(135deg, rgba(167, 139, 250, 0.25), rgba(129, 140, 248, 0.25));
        color: #c4b5fd;
        border: 1px solid rgba(167, 139, 250, 0.4);
        font-size: 0.7rem;
        padding: 0.25rem 0.75rem;
    }

    /* ===== TABS — Premium Pill Style ===== */
    .stTabs [data-baseweb="tab-list"] {
        background: rgba(17, 24, 39, 0.6) !important;
        border: 1px solid var(--border-subtle) !important;
        padding: 5px !important;
        border-radius: 14px !important;
        gap: 4px !important;
        width: fit-content !important;
        margin-bottom: 1.5rem !important;
        backdrop-filter: blur(12px) !important;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 10px !important;
        padding: 8px 20px !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
        color: var(--text-muted) !important;
        background: transparent !important;
        border: none !important;
        transition: all 0.25s ease !important;
    }
    .stTabs [data-baseweb="tab"]:hover {
        color: var(--text-secondary) !important;
        background: rgba(255,255,255,0.04) !important;
    }
    .stTabs [aria-selected="true"] {
        background: rgba(129, 140, 248, 0.12) !important;
        color: var(--accent-indigo) !important;
        border: 1px solid rgba(129, 140, 248, 0.2) !important;
        box-shadow: 0 0 12px rgba(129, 140, 248, 0.1) !important;
    }
    .stTabs [data-baseweb="tab-highlight"] {
        display: none !important;
    }
    .stTabs [data-baseweb="tab-border"] {
        display: none !important;
    }

    /* ===== BUTTONS ===== */
    .stButton > button {
        border-radius: 10px !important;
        font-weight: 600 !important;
        font-size: 0.875rem !important;
        padding: 0.6rem 1.25rem !important;
        border: 1px solid var(--border-subtle) !important;
        background: rgba(255,255,255,0.04) !important;
        color: var(--text-primary) !important;
        transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
        backdrop-filter: blur(8px) !important;
    }
    .stButton > button:hover {
        border-color: var(--border-glow) !important;
        background: rgba(129, 140, 248, 0.08) !important;
        box-shadow: 0 0 16px rgba(129, 140, 248, 0.12) !important;
        transform: translateY(-1px) !important;
    }
    .stButton > button[kind="primary"],
    .stButton > button[data-testid="stBaseButton-primary"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        color: #ffffff !important;
        border: none !important;
        box-shadow: 0 4px 16px rgba(102, 126, 234, 0.35) !important;
    }
    .stButton > button[kind="primary"]:hover,
    .stButton > button[data-testid="stBaseButton-primary"]:hover {
        box-shadow: 0 6px 24px rgba(102, 126, 234, 0.5) !important;
        transform: translateY(-2px) !important;
    }

    /* ===== FORM INPUTS (STREAMLIT 1.35+ & BASEWEB) ===== */
    [data-testid="stTextInputRootElement"],
    [data-baseweb="input"] {
        background: rgba(17, 24, 39, 0.7) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: 10px !important;
        backdrop-filter: blur(12px) !important;
        transition: all 0.2s ease !important;
        overflow: hidden !important;
        display: flex !important;
        align-items: center !important;
    }
    [data-testid="stTextInputRootElement"]:focus-within,
    [data-baseweb="input"]:focus-within {
        border-color: var(--accent-indigo) !important;
        box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.18), 0 0 20px rgba(129, 140, 248, 0.1) !important;
    }
    [data-testid="stTextInputField"],
    [data-baseweb="input"] input {
        background: transparent !important;
        border: none !important;
        color: var(--text-primary) !important;
        font-size: 0.9rem !important;
        outline: none !important;
        box-shadow: none !important;
        padding: 0.6rem 0.85rem !important;
    }
    [data-testid="stTextInputField"]::placeholder,
    [data-baseweb="input"] input::placeholder {
        color: var(--text-muted) !important;
    }

    /* ===== BULLETPROOF PASSWORD EYE TOGGLE & INPUT BUTTONS ===== */
    .stTextInput button,
    [data-testid="stTextInputRootElement"] button,
    button[aria-label*="password" i],
    button[aria-label*="Password"],
    button[aria-label*="Show password"],
    button[aria-label*="Hide password"],
    [data-baseweb="input"] button {
        background: transparent !important;
        border: none !important;
        padding: 0 !important;
        margin: 0 8px 0 0 !important;
        width: 32px !important;
        min-width: 32px !important;
        height: 32px !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        box-shadow: none !important;
        transform: none !important;
        cursor: pointer !important;
        position: relative !important;
        opacity: 0.7 !important;
        transition: all 0.2s ease !important;
        background-repeat: no-repeat !important;
        background-position: center !important;
        background-size: 20px 20px !important;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%2394a3b8' stroke-width='2'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' d='M15 12a3 3 0 11-6 0 3 3 0 016 0z'/%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' d='M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z'/%3E%3C/svg%3E") !important;
    }

    /* HIDE ANY AND ALL text/spans inside password buttons — ZERO text leaks */
    .stTextInput button *,
    [data-testid="stTextInputRootElement"] button *,
    button[aria-label*="password" i] *,
    button[aria-label*="Password"] *,
    button[aria-label*="Show password"] *,
    button[aria-label*="Hide password"] *,
    [data-baseweb="input"] button * {
        display: none !important;
        font-size: 0 !important;
        line-height: 0 !important;
        color: transparent !important;
        visibility: hidden !important;
        width: 0 !important;
        height: 0 !important;
        overflow: hidden !important;
    }

    /* When password is revealed / shown */
    .stTextInput button[aria-label*="Hide" i],
    .stTextInput button[aria-label*="hide" i],
    .stTextInput button[aria-pressed="true"],
    [data-testid="stTextInputRootElement"] button[aria-label*="Hide" i],
    [data-testid="stTextInputRootElement"] button[aria-label*="hide" i],
    [data-testid="stTextInputRootElement"] button[aria-pressed="true"],
    button[aria-label*="Hide password" i],
    button[aria-label*="hide password" i],
    [data-baseweb="input"] button[aria-label*="Hide"],
    [data-baseweb="input"] button[aria-label*="hide"],
    [data-baseweb="input"] button[aria-pressed="true"] {
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%23818cf8' stroke-width='2'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' d='M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l18 18'/%3E%3C/svg%3E") !important;
    }

    /* Clear entry button if present */
    .stTextInput button[aria-label*="Clear" i],
    [data-testid="stTextInputRootElement"] button[aria-label*="Clear" i],
    [data-baseweb="input"] button[aria-label*="Clear"],
    [data-baseweb="input"] button[aria-label*="clear"] {
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%2394a3b8' stroke-width='2'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' d='M6 18L18 6M6 6l12 12'/%3E%3C/svg%3E") !important;
    }

    .stTextInput button:hover,
    [data-testid="stTextInputRootElement"] button:hover,
    button[aria-label*="password" i]:hover,
    button[aria-label*="Password"]:hover,
    [data-baseweb="input"] button:hover {
        opacity: 1 !important;
        background-color: rgba(255, 255, 255, 0.08) !important;
        border-radius: 8px !important;
        transform: scale(1.06) !important;
    }

    [data-baseweb="textarea"] {
        background: rgba(17, 24, 39, 0.7) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: 10px !important;
        backdrop-filter: blur(12px) !important;
        transition: all 0.2s ease !important;
    }
    [data-baseweb="textarea"]:focus-within {
        border-color: var(--accent-indigo) !important;
        box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.18), 0 0 20px rgba(129, 140, 248, 0.1) !important;
    }
    [data-baseweb="textarea"] textarea {
        background: transparent !important;
        border: none !important;
        color: var(--text-primary) !important;
        font-size: 0.9rem !important;
        outline: none !important;
        box-shadow: none !important;
    }
    [data-baseweb="textarea"] textarea::placeholder {
        color: var(--text-muted) !important;
    }

    /* Labels */
    .stTextInput label, .stSelectbox label, .stTextArea label,
    .stDateInput label, .stTimeInput label, .stNumberInput label,
    .stCheckbox label, .stRadio label, .stMultiSelect label {
        color: var(--text-secondary) !important;
        font-weight: 600 !important;
        font-size: 0.85rem !important;
        margin-bottom: 0.35rem !important;
    }

    /* Selectbox dropdown */
    div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
        background-color: #111827 !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: 10px !important;
        color: #f1f5f9 !important;
    }
    div[data-testid="stSelectbox"] div[data-baseweb="select"] > div:focus-within {
        border-color: var(--accent-indigo) !important;
        box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.18), 0 0 20px rgba(129, 140, 248, 0.1) !important;
    }
    div[data-testid="stSelectbox"] div[data-baseweb="select"] span {
        color: #f1f5f9 !important;
    }
    
    /* Dropdown Popover List */
    div[data-baseweb="popover"] > div, 
    ul[data-baseweb="menu"] {
        background-color: #111827 !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: 12px !important;
        box-shadow: 0 8px 32px rgba(0,0,0,0.5) !important;
    }
    ul[data-baseweb="menu"] li[role="option"] {
        color: #f1f5f9 !important;
        background-color: transparent !important;
        border-radius: 6px !important;
        margin: 2px 4px !important;
        transition: all 0.15s ease !important;
    }
    ul[data-baseweb="menu"] li[role="option"]:hover, 
    ul[data-baseweb="menu"] li[aria-selected="true"] {
        background-color: rgba(129, 140, 248, 0.12) !important;
        color: var(--accent-indigo) !important;
    }

    /* ===== PROGRESS BAR ===== */
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg, #667eea, #764ba2) !important;
        border-radius: 999px !important;
    }
    .stProgress > div > div > div {
        background: rgba(255,255,255,0.06) !important;
        border-radius: 999px !important;
    }

    /* ===== METRICS ===== */
    [data-testid="stMetric"] {
        background: var(--gradient-card) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: var(--radius-md) !important;
        padding: 1rem !important;
    }
    [data-testid="stMetricLabel"] {
        color: var(--text-muted) !important;
    }
    [data-testid="stMetricValue"] {
        color: var(--text-primary) !important;
        font-family: 'JetBrains Mono', monospace !important;
    }

    /* ===== DIVIDERS ===== */
    hr {
        border-color: var(--border-subtle) !important;
    }

    /* ===== ALERTS ===== */
    .stAlert {
        border-radius: var(--radius-md) !important;
        border: 1px solid var(--border-subtle) !important;
    }

    /* ===== BAR CHART ===== */
    [data-testid="stVegaLiteChart"] {
        background: transparent !important;
    }

    /* ===== EXPANDER ===== */
    [data-testid="stExpander"] {
        border: 1px solid var(--border-subtle) !important;
        border-radius: var(--radius-md) !important;
        background: rgba(17, 24, 39, 0.4) !important;
        margin: 0.5rem 0 !important;
        overflow: hidden !important;
    }
    [data-testid="stExpander"] summary {
        color: var(--text-secondary) !important;
        font-weight: 600 !important;
        font-size: 0.875rem !important;
        padding: 0.75rem 1rem !important;
        transition: all 0.2s ease !important;
        gap: 0.5rem !important;
    }
    [data-testid="stExpander"] summary:hover {
        color: var(--text-primary) !important;
        background: rgba(255, 255, 255, 0.03) !important;
    }
    .streamlit-expanderHeader {
        background: rgba(17, 24, 39, 0.5) !important;
        border-radius: var(--radius-md) !important;
        color: var(--text-secondary) !important;
    }
    /* Bulletproof expander chevron */
    [data-testid="stExpanderToggleIcon"] {
        width: 22px !important;
        min-width: 22px !important;
        height: 22px !important;
        display: inline-flex !important;
        align-items: center !important;
        justify-content: center !important;
        background-repeat: no-repeat !important;
        background-position: center !important;
        background-size: 16px 16px !important;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%2394a3b8' stroke-width='2.5'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' d='M9 5l7 7-7 7'/%3E%3C/svg%3E") !important;
        transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }
    details[open] [data-testid="stExpanderToggleIcon"] {
        transform: rotate(90deg) !important;
    }
    [data-testid="stExpanderToggleIcon"] * {
        display: none !important;
        font-size: 0 !important;
    }

    /* ===== POPOVER ===== */
    [data-testid="stPopover"] > div {
        background: #1e293b !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: var(--radius-lg) !important;
    }

    /* ===== SUBHEADER ===== */
    h2, h3 {
        color: var(--text-primary) !important;
    }
    .stSubheader, [data-testid="stSubheader"] {
        color: var(--text-primary) !important;
    }

    /* ===== CAPTIONS ===== */
    .stCaption, [data-testid="stCaption"] {
        color: var(--text-muted) !important;
    }

    /* ===== TICKET PASS ===== */
    .ticket-pass {
        background: var(--gradient-card);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius-lg);
        overflow: hidden;
        display: flex;
        box-shadow: var(--shadow-card);
        margin-bottom: 1.5rem;
        position: relative;
        transition: all 0.3s ease;
        animation: fadeInUp 0.5s ease both;
    }
    .ticket-pass::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 3px;
        background: var(--gradient-brand);
        background-size: 200% 100%;
        animation: gradientShift 4s ease infinite;
    }
    .ticket-pass:hover {
        border-color: var(--border-glow);
        box-shadow: var(--shadow-glow), 0 8px 32px rgba(0,0,0,0.4);
        transform: translateY(-2px);
    }
    @media (max-width: 768px) {
        .ticket-pass { flex-direction: column; }
    }
    .ticket-main {
        flex: 1;
        padding: 1.5rem;
        border-right: 2px dashed rgba(255,255,255,0.08);
    }
    @media (max-width: 768px) {
        .ticket-main { border-right: none; border-bottom: 2px dashed rgba(255,255,255,0.08); }
    }
    .ticket-qr {
        width: 220px;
        background: rgba(15, 23, 42, 0.5);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 1.5rem;
    }
    @media (max-width: 768px) {
        .ticket-qr { width: 100%; }
    }

    /* ===== AI CONTAINER ===== */
    .ai-container {
        background: linear-gradient(135deg, rgba(167, 139, 250, 0.06) 0%, rgba(129, 140, 248, 0.04) 100%);
        border: 1px solid rgba(167, 139, 250, 0.15);
        border-radius: var(--radius-lg);
        padding: 1.5rem;
        margin-top: 1rem;
        box-shadow: 0 4px 24px rgba(167, 139, 250, 0.08);
        animation: fadeInUp 0.5s ease both;
    }

    /* ===== SCROLLBAR ===== */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.2); }

    /* ===== FORM SUBMIT ===== */
    .stForm [data-testid="stFormSubmitButton"] > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        color: #fff !important;
        border: none !important;
        box-shadow: 0 4px 16px rgba(102, 126, 234, 0.35) !important;
        border-radius: 10px !important;
    }
    .stForm [data-testid="stFormSubmitButton"] > button:hover {
        box-shadow: 0 6px 24px rgba(102, 126, 234, 0.5) !important;
    }

    /* ===== FORM CONTAINER ===== */
    [data-testid="stForm"] {
        border: 1px solid var(--border-subtle) !important;
        border-radius: var(--radius-lg) !important;
        background: var(--gradient-card) !important;
        padding: 1.5rem !important;
    </style>
    <script>
    // BFCache eviction guard: reload page if restored from browser back-forward cache after logout
    window.addEventListener('pageshow', function(event) {
        if (event.persisted) {
            window.location.reload();
        }
    });
    </script>
    """)


def render_app_bar(user_email: str = None, user_role: str = None, user_name: str = None):
    """Renders a glassmorphic top navigation bar."""
    role_cfg = {
        "admin": ("Administrator", "#fb7185", "rgba(251,113,133,0.12)"),
        "society_head": ("Society Head", "#818cf8", "rgba(129,140,248,0.12)"),
        "student": ("Student", "#34d399", "rgba(52,211,153,0.12)")
    }.get(user_role, ("Guest", "#94a3b8", "rgba(148,163,184,0.12)"))

    initials = "U"
    if user_name and user_name.strip():
        parts = user_name.strip().split()
        initials = (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()
    elif user_email:
        initials = user_email[0].upper()

    col_brand, col_user = st.columns([3, 2])
    with col_brand:
        render_html(f"""
        <div class="topbar-brand" style="padding-top: 0.25rem;">
            <div class="topbar-logo">C</div>
            <div>
                <div class="topbar-title">CampusPulse</div>
                <div class="topbar-sub">Smart Campus OS</div>
            </div>
        </div>
        """)

    with col_user:
        if user_email:
            c_info, c_btn = st.columns([3, 1.5])
            with c_info:
                render_html(f"""
                <div class="topbar-user" style="justify-content: flex-end; padding-top: 0.3rem;">
                    <div class="topbar-meta">
                        <div class="topbar-meta-name">{user_name or user_email}</div>
                        <div class="topbar-meta-role" style="color: {role_cfg[1]};">{role_cfg[0]}</div>
                    </div>
                    <div class="topbar-avatar" style="background: {role_cfg[2]}; color: {role_cfg[1]};">{initials}</div>
                </div>
                """)
            with c_btn:
                if st.button("Log Out", key="topbar_logout_btn", use_container_width=True):
                    return True
    return False


def render_page_header(tag: str, title: str, description: str):
    """Renders an animated hero section header."""
    render_html(f"""
    <div class="hero-section">
        <div class="hero-tag">{tag}</div>
        <h1 class="hero-title">{title}</h1>
        <p class="hero-desc">{description}</p>
    </div>
    """)


def render_kpi_card(label: str, value, subtext: str = "", icon_symbol: str = "📊"):
    """Renders a premium glassmorphic KPI card with animated gradient top bar."""
    render_html(f"""
    <div class="kpi">
        <div class="kpi-header">
            <span class="kpi-label">{label}</span>
            <span class="kpi-icon">{icon_symbol}</span>
        </div>
        <div class="kpi-value">{value}</div>
        <div class="kpi-sub">{subtext}</div>
    </div>
    """)


def render_empty_state(title: str, description: str, icon_symbol: str = "✨"):
    """Renders a premium empty state container."""
    render_html(f"""
    <div style="text-align: center; padding: 3.5rem 2rem; background: var(--gradient-card); border: 1px dashed rgba(255,255,255,0.08); border-radius: 16px; margin: 1rem 0; animation: fadeInUp 0.5s ease both;">
        <div style="font-size: 3rem; margin-bottom: 1rem; filter: grayscale(0.2);">{icon_symbol}</div>
        <h3 style="font-size: 1.15rem; font-weight: 700; color: var(--text-primary); margin-bottom: 0.5rem;">{title}</h3>
        <p style="font-size: 0.9rem; color: var(--text-muted); max-width: 400px; margin: 0 auto; line-height: 1.5;">{description}</p>
    </div>
    """)


def render_badge_html(text: str, variant: str = "category") -> str:
    """Returns HTML for a styled micro-badge."""
    return f'<span class="badge badge-{variant}">{text}</span>'


def render_status_badge(status: str) -> str:
    """Returns a styled HTML badge for an event, pass, or charter status."""
    st_clean = (status or "pending").strip().lower()
    mapping = {
        "approved":  ("APPROVED", "approved"),
        "active":    ("ACTIVE", "approved"),
        "confirmed": ("CONFIRMED", "approved"),
        "completed": ("COMPLETED", "completed"),
        "pending":   ("PENDING REVIEW", "pending"),
        "rejected":  ("REJECTED", "rejected"),
        "cancelled": ("CANCELLED", "cancelled"),
        "soldout":   ("SOLD OUT", "soldout"),
        "attended":  ("ATTENDED", "completed"),
    }
    label, variant = mapping.get(st_clean, (st_clean.upper(), "category"))
    return f'<span class="badge badge-{variant}">{label}</span>'


def render_feedback_banner(
    variant: str,
    title: str,
    message: str,
    next_step: str = "",
) -> None:
    """
    Renders an institutional feedback banner answering:
    - What happened?
    - Why?
    - What happens next?
    """
    colors = {
        "success": ("#34d399", "rgba(52, 211, 153, 0.1)", "✅"),
        "warning": ("#fbbf24", "rgba(251, 191, 36, 0.1)", "⚠️"),
        "error":   ("#fb7185", "rgba(251, 113, 133, 0.1)", "⛔"),
        "info":    ("#818cf8", "rgba(129, 140, 248, 0.1)", "ℹ️"),
    }.get(variant, ("#818cf8", "rgba(129, 140, 248, 0.1)", "ℹ️"))

    next_step_html = (
        f'<div style="margin-top:0.5rem;font-size:0.8rem;color:#cbd5e1;'
        f'border-top:1px solid rgba(255,255,255,0.06);padding-top:0.4rem;">'
        f'<strong>Next Steps:</strong> {next_step}</div>'
        if next_step else ""
    )

    render_html(f"""
    <div style="background:{colors[1]};border-left:4px solid {colors[0]};
                border-radius:0 12px 12px 0;padding:0.9rem 1.15rem;margin:0.75rem 0;">
        <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.25rem;">
            <span style="font-size:1.1rem;">{colors[2]}</span>
            <span style="font-weight:700;color:#f8fafc;font-size:0.95rem;">{title}</span>
        </div>
        <div style="font-size:0.85rem;color:#cbd5e1;line-height:1.45;">{message}</div>
        {next_step_html}
    </div>
    """)
