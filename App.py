import streamlit as st
import requests
import json
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types
from datetime import datetime, timedelta
from dateutil import parser

# --- 1. INITIALIZATION ---
if not firebase_admin._apps:
    try:
        key_dict = json.loads(st.secrets["FIREBASE_KEY"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Firebase Init Error: {e}")
        st.stop()

db = firestore.client()
client = genai.Client(api_key=st.secrets["GEMINI_KEY"])

# --- 2. THE CITY RESOLVER (Critical Fix) ---
def get_city_from_airport_code(code):
    """
    Looks up the full City name from an IATA/ICAO code.
    Matches the 'City' field in your Firebase.
    """
    if not code: return "Unknown"
    
    # 1. Quick Map for Common Indian Cities
    local_map = {
        "DEL": "Delhi", "BLR": "Bengaluru", "BOM": "Mumbai", "MAA": "Chennai",
        "HYD": "Hyderabad", "CCU": "Kolkata", "GOI": "Goa", "PNQ": "Pune",
        "AMD": "Ahmedabad", "JAI": "Jaipur", "LKO": "Lucknow", "COK": "Kochi"
    }
    if code.upper() in local_map:
        return local_map[code.upper()]
    
    # 2. Live API Lookup
    url = f"https://airlabs.co/api/v9/airports?iata_code={code}&api_key={st.secrets['AIRLABS_KEY']}"
    try:
        res = requests.get(url).json()
        if "response" in res and res["response"]:
            # Prioritize 'city' field from AirLabs
            city = res["response"][0].get('city')
            if city:
                # Handle 'New Delhi' vs 'Delhi' mismatch
                if "Delhi" in city: return "Delhi"
                return city
    except:
        pass
    return "Unknown"

# --- 3. FLIGHT DATA FETCHING ---
def get_flight_data(flight_input):
    """Fetches flight and resolves the destination city name"""
    clean_iata = flight_input.replace(" ", "").upper()
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={st.secrets['AIRLABS_KEY']}"
    
    try:
        res = requests.get(url).json()
        if "response" in res and res["response"]:
            f_data = res["response"][0]
            
            # Capture destination code (IATA or ICAO)
            dest_code = f_data.get('arr_iata') or f_data.get('arr_icao')
            
            # Resolve the Code to a City Name for Firebase RAG
            f_data['resolved_city'] = get_city_from_airport_code(dest_code)
            return f_data
    except Exception as e:
        st.sidebar.error(f"Flight API Error: {e}")
    return None

# --- 4. RAG HELPER ---
def get_itinerary_context(city_name):
    """Retrieves place data from Firestore"""
    search_term = city_name.strip().title()
    try:
        # Search the 'City' field (Exact match)
        docs = db.collection("itineraries_knowledge_base").where("City", "==", search_term).get(timeout=10)
        
        context_data = []
        for doc in docs:
            d = doc.to_dict()
            info = f"- {d.get('Name')}: {d.get('Significance')}. Fee: {d.get('Entrance Fee in INR')} INR. Time: {d.get('time needed to visit in hrs')} hrs."
            context_data.append(info)
        return context_data
    except Exception as e:
        return []

# --- 5. GOOGLE MAPS ---
def get_travel_metrics(origin, airport_code):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {"origins": origin, "destinations": f"{airport_code} Airport", "mode": "driving", "departure_time": "now", "key": st.secrets["GOOGLE_MAPS_KEY"]}
    try:
        data = requests.get(url, params=params).json()
        element = data['rows'][0]['elements'][0]
        return {"seconds": element['duration_in_traffic']['value'], "text": element['duration_in_traffic']['text']}
    except: return None

# --- 6. UI ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️")

if 'dest_city' not in st.session_state:
    st.session_state.dest_city = None

st.title("✈️ Departly.ai")

col1, col2 = st.columns(2)
with col1:
    flight_input = st.text_input("Flight Number", placeholder="e.g. 6E 2134")
with col2:
    home_input = st.text_input("Pickup Point", placeholder="e.g. Mahaveer Tuscan, Hoodi")

if st.button("Calculate My Safe Departure", use_container_width=True):
    with st.spinner("Connecting to Aviation & Traffic APIs..."):
        flight = get_flight_data(flight_input)
        
        if flight:
            # Update Session State with resolved city name
            st.session_state.dest_city = flight['resolved_city']
            
            takeoff_dt = parser.parse(flight['dep_time'])
            boarding_dt = takeoff_dt - timedelta(minutes=45)
            traffic = get_travel_metrics(home_input, flight['dep_iata'])
            
            if traffic:
                leave_dt = boarding_dt - timedelta(seconds=traffic['seconds'] + (105 * 60))
                st.balloons()
                st.success(f"### 🚪 Leave Home by: **{leave_dt.strftime('%I:%M %p')}**")
                st.write(f"Confirmed: You are heading to **{st.session_state.dest_city}**")
            else:
                st.error("Google Maps could not calculate the route.")
        else:
            st.error("Flight not found. Please verify the number.")

# --- 7. RAG SECTION ---
if st.session_state.dest_city and st.session_state.dest_city != 'Unknown':
    st.divider()
    st.subheader(f"🗺️ Plan Your {st.session_state.dest_city} Visit")
    days = st.slider("Duration (Days)", 1, 7, 3)
    
    if st.button("Generate RAG Itinerary"):
        with st.spinner(f"Querying Firebase Knowledge Base for {st.session_state.dest_city}..."):
            results = get_itinerary_context(st.session_state.dest_city)
            
            if results:
                st.caption(f"Success: Found {len(results)} attractions in database.")
                context_str = "\n".join(results)
                prompt = f"Using this data: {context_str}, create a {days}-day itinerary for {st.session_state.dest_city}. Include fees and significance."
                response = client.models.generate_content(model='gemini-3-flash-preview', contents=prompt)
                st.info(response.text)
            else:
                st.warning(f"No records found for '{st.session_state.dest_city}' in our database. Ensure your Firebase data uses the correct city names.")

st.markdown("---")
st.caption("2025 Departly.ai | RAG-Powered Travel Concierge.")
