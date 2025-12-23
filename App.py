import streamlit as st
import requests
from google import genai
from google.genai import types
from datetime import datetime, timedelta
from dateutil import parser

# --- SECURE API CONFIGURATION ---
try:
    # Pulling keys from Streamlit Cloud Secrets (Settings -> Secrets)
    AIRLABS_KEY = st.secrets["AIRLABS_KEY"]
    GOOGLE_MAPS_KEY = st.secrets["GOOGLE_MAPS_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_KEY"]
except Exception:
    st.error("Missing API Keys! Add AIRLABS_KEY, GOOGLE_MAPS_KEY, and GEMINI_KEY to Streamlit Secrets.")
    st.stop()

# --- 2025 SDK INITIALIZATION ---
client = genai.Client(api_key=GEMINI_KEY)

# --- FUNCTIONS ---

def get_flight_data(flight_iata):
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={flight_iata}&api_key={AIRLABS_KEY}"
    try:
        response = requests.get(url).json()
        if "response" in response and response["response"]:
            return response["response"][0]
    except Exception as e:
        st.sidebar.error(f"AirLabs Error: {e}")
    return None

def get_travel_metrics(origin, airport_code):
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

# Model Selector in Sidebar
AVAILABLE_MODELS = ['gemini-3-flash-preview', 'gemini-2.5-flash', 'gemini-1.5-flash']
selected_model = st.sidebar.selectbox("AI Model", AVAILABLE_MODELS, index=0)

# User Inputs
col1, col2 = st.columns(2)
with col1:
    flight_input = st.text_input("IndiGo Flight", value="6E2134")
with col2:
    home_input = st.text_input("Pickup Point", placeholder="e.g., Mahaveer Tuscan, Hoodi")

if st.button("Calculate My Safe Departure", use_container_width=True):
    if not home_input or not flight_input:
        st.warning("Please fill in both fields.")
    else:
        with st.spinner(f"Processing with {selected_model}..."):
            flight = get_flight_data(flight_input)
            
            if flight:
                # 1. Timeline Logic
                takeoff_dt = parser.parse(flight['dep_time'])
                boarding_dt = takeoff_dt - timedelta(minutes=45)
                
                # 2. Traffic Logic
                traffic = get_travel_metrics(home_input, flight['dep_iata'])
                
                if traffic:
                    # 3. Buffer Logic: 60m Sec + 15m Queue + 30m Road = 105 mins
                    safety_buffer_mins = 105 
                    total_needed_seconds = traffic['seconds'] + (safety_buffer_mins * 60)
                    leave_dt = boarding_dt - timedelta(seconds=total_transit_seconds if 'total_transit_seconds' in locals() else total_needed_seconds)
                    
                    # --- DISPLAY ---
                    st.balloons()
                    st.success(f"### 🚪 Leave Home by: **{leave_dt.strftime('%I:%M %p')}**")
                    
                    st.write(f"Destination: **{flight['dep_iata']} Airport** | Distance: **{traffic['distance']}**")

                    m1, m2, m3 = st.columns(3)
                    m1.metric("Takeoff", takeoff_dt.strftime("%I:%M %p"))
                    m2.metric("Boarding", boarding_dt.strftime("%I:%M %p"))
                    m3.metric("Live Traffic", traffic['text'])

                    # --- GEMINI 3 AI ADVISORY ---
                    st.divider()
                    st.subheader(f"🤖 AI Advisory ({selected_model})")
                    
                    prompt = f"""
                    You are a luxury travel assistant. 
                    Flight: {flight_input} from {flight['dep_iata']}.
                    Departure: {takeoff_dt.strftime('%I:%M %p')}.
                    Traffic: {traffic['text']}.
                    Must Leave Home By: {leave_dt.strftime('%I:%M %p')}.
                    
                    Explain why this timing is safe. Mention the specific buffers: 1hr security, 15m queue, and 30m travel. 
                    Structure the response with bold headers.
                    """
                    
                    try:
                        response = client.models.generate_content(
                            model=selected_model,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                temperature=0.7,
                                max_output_tokens=500
                            )
                        )
                        st.info(response.text)
                    except Exception as e:
                        st.warning("AI Advisory could not be generated, but your schedule is ready above.")
                        st.sidebar.error(f"AI Error: {e}")
                else:
                    st.error("Address not found by Google Maps.")
            else:
                st.error("Flight not found in AirLabs database.")

st.markdown("---")
st.caption("2025 Departly.ai | Powered by Google Gemini 3 & Google Maps.")
