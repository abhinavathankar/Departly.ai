import streamlit as st
import requests
from google import genai
from google.genai import types
from datetime import datetime, timedelta
from dateutil import parser

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

def get_flight_data(flight_iata):
    """Fetches flight schedule and airport details from AirLabs"""
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={flight_iata}&api_key={AIRLABS_KEY}"
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
    flight_input = st.text_input("IndiGo Flight", value="6E2134")
with col2:
    home_input = st.text_input("Pickup Point", placeholder="e.g., Mahaveer Tuscan, Hoodi")

if st.button("Calculate My Safe Departure", use_container_width=True):
    if not home_input or not flight_input:
        st.warning("Please fill in both fields.")
    else:
        with st.spinner(f"Consulting {selected_model}..."):
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
                    leave_dt = boarding_dt - timedelta(seconds=total_needed_seconds)
                    
                    # --- DISPLAY ---
                    st.balloons()
                    st.success(f"### 🚪 Leave Home by: **{leave_dt.strftime('%I:%M %p')}**")
                    
                    # Fetching richer details for the prompt
                    origin_city = flight.get('dep_city', flight['dep_iata'])
                    dest_city = flight.get('arr_city', flight['arr_iata'])
                    terminal = flight.get('dep_terminal', 'Main')

                    st.write(f"Route: **{origin_city}** to **{dest_city}** | Terminal: **{terminal}**")

                    m1, m2, m3 = st.columns(3)
                    m1.metric("Takeoff", takeoff_dt.strftime("%I:%M %p"))
                    m2.metric("Boarding", boarding_dt.strftime("%I:%M %p"))
                    m3.metric("Live Traffic", traffic['text'])

                    # --- ENRICHED GEMINI 3 PROMPT ---
                    st.divider()
                    st.subheader(f"🤖 Luxury Travel Advisory")
                    
                    prompt = f"""
                    You are an elite luxury travel assistant for Departly.ai. 
                    Your tone is professional, reassuring, and detailed.

                    **TRIP DETAILS:**
                    - Flight: {flight_input} (IndiGo)
                    - Route: {origin_city} to {dest_city}
                    - Terminal: {terminal}
                    - Takeoff: {takeoff_dt.strftime('%I:%M %p')}
                    - Boarding: {boarding_dt.strftime('%I:%M %p')}

                    **GROUND LOGISTICS:**
                    - Traffic: {traffic['text']}
                    - Recommended Departure: {leave_dt.strftime('%I:%M %p')}

                    **TASK:**
                    Explain why this timing is the 'Golden Window' for a stress-free trip. 
                    Mention the 1-hour security, 15m queue buffer, and 30m travel buffer.
                    Structure with **Bold Headers**.
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
                st.error("Flight not found. Verify the number.")

st.markdown("---")
st.caption("2025 Departly.ai | Powered by Gemini 3 & Google Maps.")
