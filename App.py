import streamlit as st
import requests
import google.generativeai as genai
from datetime import datetime, timedelta
from dateutil import parser

# --- SECURE API CONFIGURATION ---
# These will be pulled from Streamlit Cloud Secrets (Settings -> Secrets)
try:
    AIRLABS_KEY = st.secrets["AIRLABS_KEY"]
    GOOGLE_MAPS_KEY = st.secrets["GOOGLE_MAPS_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_KEY"]
except Exception:
    st.error("API Keys not found! Please add AIRLABS_KEY, GOOGLE_MAPS_KEY, and GEMINI_KEY to your Streamlit Secrets.")
    st.stop()

# --- AI SETUP ---
genai.configure(api_key=GEMINI_KEY)
ai_model = genai.GenerativeModel('gemini-1.5-flash')

# --- DATA FETCHING FUNCTIONS ---

def get_flight_data(flight_iata):
    """Fetches live flight schedule from AirLabs"""
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={flight_iata}&api_key={AIRLABS_KEY}"
    try:
        response = requests.get(url).json()
        if "response" in response and response["response"]:
            return response["response"][0]
    except Exception as e:
        st.error(f"AirLabs API Error: {e}")
    return None

def get_travel_metrics(origin, airport_code):
    """Fetches real-time traffic data from Google Maps Distance Matrix"""
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
        st.error(f"Google Maps API Error: {e}")
    return None

# --- STREAMLIT UI ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️", layout="centered")

# Custom CSS for better look
st.markdown("""
    <style>
    .main { text-align: center; }
    .stMetric { background-color: #f0f2f6; padding: 10px; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

st.title("✈️ Departly.ai")
st.subheader("Smart AI Departure Assistant")
st.write("We calculate your 'Leave Home' time using real-time traffic, flight status, and safety buffers.")
st.markdown("---")

# User Inputs
col1, col2 = st.columns(2)
with col1:
    flight_input = st.text_input("IndiGo Flight Number", value="6E2134", help="Example: 6E2134")
with col2:
    home_input = st.text_input("Your Location", placeholder="e.g., Mahaveer Tuscan, Hoodi")

if st.button("Calculate My Safe Departure Time", use_container_width=True):
    if not home_input or not flight_input:
        st.warning("Please provide both your flight number and current location.")
    else:
        with st.spinner("Analyzing live traffic and flight schedules..."):
            flight = get_flight_data(flight_input)
            
            if flight:
                # 1. Parse Times
                takeoff_dt = parser.parse(flight['dep_time'])
                boarding_dt = takeoff_dt - timedelta(minutes=45)
                
                # 2. Get Traffic
                traffic = get_travel_metrics(home_input, flight['dep_iata'])
                
                if traffic:
                    # 3. Calculate Safety Buffers
                    # 60m Security + 15m Queue Buffer + 30m Travel Buffer = 105 mins total buffer
                    safety_buffer_mins = 60 + 15 + 30
                    total_transit_seconds = traffic['seconds'] + (safety_buffer_mins * 60)
                    
                    leave_home_dt = boarding_dt - timedelta(seconds=total_transit_seconds)
                    
                    # --- RESULTS ---
                    st.balloons()
                    st.success(f"### 🚪 Recommended Departure: **{leave_home_dt.strftime('%I:%M %p')}**")
                    
                    st.write(f"Destination: **{flight['dep_iata']} Airport** | Distance: **{traffic['distance']}**")

                    m1, m2, m3 = st.columns(3)
                    m1.metric("Takeoff", takeoff_dt.strftime("%I:%M %p"))
                    m2.metric("Boarding", boarding_dt.strftime("%I:%M %p"))
                    m3.metric("Live Traffic", traffic['text'])

                    # --- GEMINI AI ADVISORY ---
                    st.markdown("---")
                    st.subheader("🤖 AI Travel Advisory")
                    
                    prompt = f"""
                    Context: 
                    The user is taking flight {flight_input} from {flight['dep_iata']} Airport. 
                    - Takeoff: {takeoff_dt.strftime('%I:%M %p')}
                    - Boarding starts: {boarding_dt.strftime('%I:%M %p')}
                    - Traffic to airport: {traffic['text']}
                    - Recommended Leave Time: {leave_home_dt.strftime('%I:%M %p')}
                    
                    Logic:
                    We added 1 hour for security, a 15-minute queue buffer, and a 30-minute travel buffer.
                    
                    Task:
                    Explain this timeline to the user in a reassuring, helpful tone. Use bullet points for the breakdown.
                    Mention that the 30-minute extra travel buffer is to protect them against unexpected traffic spikes.
                    """
                    
                    ai_response = ai_model.generate_content(prompt)
                    st.info(ai_response.text)
                    
                else:
                    st.error("Google Maps could not find a route. Please check your location address.")
            else:
                st.error("Flight not found. Please verify the Flight Number (e.g., 6E2134).")

st.markdown("---")
st.caption("Powered by Gemini 1.5 Flash, Google Maps, and AirLabs API.")
