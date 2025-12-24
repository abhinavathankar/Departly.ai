import streamlit as st
import requests
from google import genai
from google.genai import types
from datetime import datetime, timedelta
from dateutil import parser
import re

# --- SECURE API CONFIGURATION ---
try:
    AIRLABS_KEY = st.secrets["AIRLABS_KEY"]
    GOOGLE_MAPS_KEY = st.secrets["GOOGLE_MAPS_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_KEY"]
except Exception:
    st.error("Missing API Keys! Add AIRLABS_KEY, GOOGLE_MAPS_KEY, and GEMINI_KEY to Streamlit Secrets.")
    st.stop()

# --- 2025 SDK INITIALIZATION ---
client = genai.Client(api_key=GEMINI_KEY)

# --- FUNCTIONS ---

def get_flight_data(flight_input):
    """Handles spaces and fetches flight details from AirLabs"""
    # Remove all spaces from the input (e.g., 'AI 2222' -> 'AI2222')
    clean_iata = flight_input.replace(" ", "").upper()
    
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={AIRLABS_KEY}"
    try:
        response = requests.get(url).json()
        if "response" in response and response["response"]:
            return response["response"][0]
    except Exception as e:
        st.sidebar.error(f"AirLabs Error: {e}")
    return None

def get_travel_metrics(origin, airport_code):
    """Fetches real-time traffic data from Google Maps"""
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": origin,
        "destinations": f"{airport_code} Airport",
        "mode": "driving",
        "departure_time": "now",
        "key": GOOGLE_MAPS_KEY
    }
    try:
        data = requests.get(url, params=params).json()
        if data['status'] == 'OK':
            element = data['rows'][0]['elements'][0]
            if element['status'] == 'OK':
                return {
                    "seconds": element['duration_in_traffic']['value'],
                    "text": element['duration_in_traffic']['text'],
                    "distance": element['distance']['text']
                }
    except Exception as e:
        st.sidebar.error(f"Google Maps Error: {e}")
    return None

# --- STREAMLIT UI ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️", layout="centered")

st.markdown("""
    <style>
    .stMetric { background-color: #f8f9fa; padding: 15px; border-radius: 12px; border: 1px solid #e9ecef; }
    </style>
    """, unsafe_allow_html=True)

st.title("✈️ Departly.ai")
st.write("Precision travel planning with Gemini 3 Intelligence.")

# Model Selector
AVAILABLE_MODELS = ['gemini-3-flash-preview', 'gemini-2.5-flash', 'gemini-1.5-flash']
selected_model = st.sidebar.selectbox("AI Model", AVAILABLE_MODELS, index=0)

col1, col2 = st.columns(2)
with col1:
    # 1. UPDATED UI LABEL
    flight_input = st.text_input("Flight Number", help="e.g. AI 2222, 6E 2134, EK 502")
with col2:
    home_input = st.text_input("Pickup Point", placeholder="e.g., Mahaveer Tuscan, Hoodi")

if st.button("Calculate My Safe Departure", use_container_width=True):
    if not home_input or not flight_input:
        st.warning("Please fill in both fields.")
    else:
        with st.spinner(f"Consulting {selected_model}..."):
            # 3. INTERNALLY HANDLES SPACES
            flight = get_flight_data(flight_input)
            
            if flight:
                takeoff_dt = parser.parse(flight['dep_time'])
                boarding_dt = takeoff_dt - timedelta(minutes=45)
                traffic = get_travel_metrics(home_input, flight['dep_iata'])
                
                if traffic:
                    safety_buffer_mins = 105 
                    total_needed_seconds = traffic['seconds'] + (safety_buffer_mins * 60)
                    leave_dt = boarding_dt - timedelta(seconds=total_needed_seconds)
                    
                    st.balloons()
                    st.success(f"### 🚪 Leave Home by: **{leave_dt.strftime('%I:%M %p')}**")
                    
                    origin_city = flight.get('dep_city', flight['dep_iata'])
                    dest_city = flight.get('arr_city', flight['arr_iata'])
                    terminal = flight.get('dep_terminal', 'Main')

                    st.write(f"Route: **{origin_city}** to **{dest_city}** | Terminal: **{terminal}**")

                    m1, m2, m3 = st.columns(3)
                    m1.metric("Takeoff", takeoff_dt.strftime("%I:%M %p"))
                    m2.metric("Boarding", boarding_dt.strftime("%I:%M %p"))
                    m3.metric("Live Traffic", traffic['text'])

                    # --- 2. UPDATED SHORT PROMPT (3 PARAS, 3 LINES EACH) ---
                    st.divider()
                    st.subheader(f"🤖 Luxury Travel Advisory")
                    
                    prompt = f"""
                    You are an elite luxury travel assistant. 
                    Trip: {flight_input.upper()} from {flight['dep_iata']}. Takeoff: {takeoff_dt.strftime('%I:%M %p')}. Leave home: {leave_dt.strftime('%I:%M %p')}.

                    STRICT FORMATTING RULE: 
                    Write exactly 3 paragraphs. Each paragraph must be exactly 3 lines long.
                    Paragraph 1: Welcome the user and explain the 'Golden Window' for departure.
                    Paragraph 2: Detail the 1hr security, 15m queue, and 30m travel buffers.
                    Paragraph 3: Reassure them of a stress-free journey and close professionally.
                    """
                    
                    try:
                        response = client.models.generate_content(
                            model=selected_model,
                            contents=prompt,
                            config=types.GenerateContentConfig(temperature=0.7)
                        )
                        st.info(response.text)
                    except Exception as e:
                        st.warning("AI Advisory unavailable. Please follow the times above.")
                else:
                    st.error("Google Maps could not calculate the route.")
            else:
                st.error("Flight not found. Ensure the Carrier Code and Number are correct.")

st.markdown("---")
st.caption("2025 Departly.ai | Powered by Gemini 3 & Google Maps.")
