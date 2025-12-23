import streamlit as st
import requests
import google.generativeai as genai
from datetime import datetime, timedelta
from dateutil import parser

# --- API CONFIGURATION ---
# Replace these with your actual keys
AIRLABS_KEY = "YOUR_AIRLABS_API_KEY"
GOOGLE_MAPS_KEY = "YOUR_GOOGLE_MAPS_KEY"
GEMINI_KEY = "YOUR_GEMINI_API_KEY"

# --- AI SETUP ---
genai.configure(api_key=GEMINI_KEY)
ai_model = genai.GenerativeModel('gemini-1.5-flash')

# --- FUNCTIONS ---

def get_flight_data(flight_iata):
    """Fetches flight schedule from AirLabs"""
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={flight_iata}&api_key={AIRLABS_KEY}"
    try:
        response = requests.get(url).json()
        if "response" in response and response["response"]:
            return response["response"][0]
    except Exception as e:
        st.error(f"AirLabs Error: {e}")
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
        st.error(f"Google Maps Error: {e}")
    return None

# --- STREAMLIT UI ---
st.set_page_config(page_title="Buffer.ai", page_icon="✈️", layout="centered")

st.title("✈️ Buffer.ai")
st.subheader("Smart Departure Assistant")
st.markdown("---")

# User Inputs
col_input1, col_input2 = st.columns(2)
with col_input1:
    flight_input = st.text_input("IndiGo Flight Number", value="6E2134", help="Format: 6E123")
with col_input2:
    home_input = st.text_input("Your Current Location", placeholder="e.g., Mahaveer Tuscan, Hoodi")

if st.button("Calculate My Safe Departure Time", use_container_width=True):
    if not home_input or not flight_input:
        st.warning("Please enter both flight number and location.")
    else:
        with st.spinner("Analyzing traffic and flight schedules..."):
            flight = get_flight_data(flight_input)
            
            if flight:
                # 1. Parse Times
                # AirLabs provides dep_time in 'YYYY-MM-DD HH:MM'
                takeoff_dt = parser.parse(flight['dep_time'])
                boarding_dt = takeoff_dt - timedelta(minutes=45)
                
                # 2. Get Traffic to the specific Departure Airport
                traffic = get_travel_metrics(home_input, flight['dep_iata'])
                
                if traffic:
                    # 3. Apply Your Specific Safety Logic
                    # Buffers: 60m (Security) + 15m (Sec Buffer) + 30m (Travel Buffer)
                    safety_buffer_mins = 60 + 15 + 30
                    total_transit_seconds = traffic['seconds'] + (safety_buffer_mins * 60)
                    
                    leave_home_dt = boarding_dt - timedelta(seconds=total_transit_seconds)
                    
                    # --- RESULTS DISPLAY ---
                    st.balloons()
                    st.success(f"### 🚪 Recommended Departure: **{leave_home_dt.strftime('%I:%M %p')}**")
                    
                    # Visual Timeline
                    
                    
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Takeoff Time", takeoff_dt.strftime("%I:%M %p"))
                    m2.metric("Boarding Starts", boarding_dt.strftime("%I:%M %p"))
                    m3.metric("Current Traffic", traffic['text'])

                    # --- GEMINI ANALYSIS ---
                    st.markdown("---")
                    st.subheader("🤖 AI Travel Advisory")
                    
                    prompt = f"""
                    Context: 
                    User is flying {flight_input} from {flight['dep_iata']}. 
                    Takeoff: {takeoff_dt.strftime('%I:%M %p')}.
                    Boarding: {boarding_dt.strftime('%I:%M %p')}.
                    Google Traffic: {traffic['text']}.
                    Calculated Leave Time: {leave_home_dt.strftime('%I:%M %p')}.
                    
                    Logic used: 
                    - 45 min before takeoff for boarding.
                    - 1 hour for security check-in.
                    - 15 min extra buffer for airport queues.
                    - 30 min extra buffer for travel delays.
                    
                    Task: 
                    Explain this timeline to the user in a friendly, reassuring way. 
                    Emphasize why leaving at {leave_home_dt.strftime('%I:%M %p')} keeps them safe from traffic and long lines.
                    """
                    
                    ai_response = ai_model.generate_content(prompt)
                    st.info(ai_response.text)
                    
                else:
                    st.error("Could not calculate travel time. Please check your address.")
            else:
                st.error("Flight not found. Please check the flight number.")

st.markdown("---")
st.caption("Powered by Gemini AI, Google Maps, and AirLabs.")
