import streamlit as st
import requests
from google import genai
from datetime import datetime, timedelta
from dateutil import parser

# --- SECURE API CONFIGURATION ---
try:
    AIRLABS_KEY = st.secrets["AIRLABS_KEY"]
    GOOGLE_MAPS_KEY = st.secrets["GOOGLE_MAPS_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_KEY"]
except Exception:
    st.error("API Keys not found! Check your Streamlit Secrets.")
    st.stop()

# --- AI SETUP ---
# Initialize the new Google GenAI Client
client = genai.Client(api_key=GEMINI_KEY)

# --- UI SETUP ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️")
st.title("✈️ Departly.ai")

# Sidebar for Model Selection
AVAILABLE_MODELS = ['gemini-3-flash-preview', 'gemini-2.5-flash', 'gemini-1.5-flash']
selected_model = st.sidebar.selectbox("Select AI Brain", AVAILABLE_MODELS, index=0)

# ... [Keep your get_flight_data and get_travel_metrics functions] ...

if st.button("Calculate My Safe Departure Time"):
    # ... [Assuming takeoff_dt, boarding_dt, and traffic are already calculated] ...
    
    # --- GEMINI AI ADVISORY ---
    st.markdown("---")
    st.subheader(f"🤖 AI Advisory ({selected_model})")
    
    prompt = f"""
    Context: Flight {flight_input} from {flight['dep_iata']} Airport. 
    Takeoff: {takeoff_dt.strftime('%I:%M %p')}, Boarding: {boarding_dt.strftime('%I:%M %p')}.
    Traffic: {traffic['text']}. Recommended Leave Time: {leave_home_dt.strftime('%I:%M %p')}.
    
    Explain the timeline (1hr security, 15m queue, 30m travel buffers) in a reassuring way.
    """

    try:
        # Using the new SDK syntax for content generation
        response = client.models.generate_content(
            model=selected_model,
            contents=prompt
        )
        
        if response.text:
            st.info(response.text)
            
    except Exception as e:
        st.warning("AI Advisory is currently unavailable. Please follow the calculated times above.")
        st.sidebar.error(f"Model Error: {e}")
