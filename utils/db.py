import os
from supabase import create_client, Client
from dotenv import load_dotenv
import streamlit as st

# Load environment variables (useful for local development)
load_dotenv()

def get_supabase() -> Client:
    """
    Initialize and return a per-session Supabase client to prevent
    session/auth bleed across concurrent users in Streamlit.
    """
    url: str = os.environ.get("SUPABASE_URL")
    key: str = os.environ.get("SUPABASE_KEY")
    
    if not url or not key:
        try:
            st.error("Supabase credentials not found in environment variables. Please check your .env file.")
            st.stop()
        except Exception:
            raise ValueError("Supabase credentials not found in environment variables.")

    # In a Streamlit session, maintain client per session
    try:
        if "supabase_client" not in st.session_state or st.session_state.supabase_client is None:
            st.session_state.supabase_client = create_client(url, key)
        return st.session_state.supabase_client
    except Exception:
        # Fallback if run outside of Streamlit context (e.g. scripts/tests)
        return create_client(url, key)

def reset_supabase_session():
    """Clear the session client on logout."""
    try:
        if "supabase_client" in st.session_state:
            st.session_state.supabase_client = None
    except Exception:
        pass
