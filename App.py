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
        st.error(f"Firebase Config Error: {e}")
        st.stop()

db = firestore.client()
client = genai.Client(api_key=st.secrets["GEMINI_KEY"])

# --- 2. SYNONYM MAPPER (To match your specific CSV) ---
def map_city_to_csv(city_name):
    """Maps API city names to the exact strings in your CSV file."""
    if not city_name: return "Unknown"
    
    mapping = {
        "Bangalore": "Bengaluru",
        "Bengaluru": "Bengaluru",
        "New Delhi": "Delhi",
        "Delhi": "Delhi",
        "Madras": "Chennai",
        "Bombay": "Mumbai"
    }
    # Check if the city name contains any of our keys
    for key, value in mapping.items():
        if key.lower() in city_name.lower():
            return value
    return city_name.title()

# --- 3. THE RAG ENGINE ---
def get_itinerary_context(city_name):
    """Fetches documents from Firestore 'itineraries_knowledge_base'"""
    # Clean and map city name to match CSV headers
    search_term = map_city_to_csv(city_name)
    
    try:
        # EXACT MATCH query on field 'City' (Case sensitive in Firestore)
        docs = db.collection("itineraries_knowledge_base").where("City", "==", search_term).get(timeout=10)
        
        context_data = []
        for doc in docs:
            d = doc.to_dict()
            # Safety check: only add if Name exists
            if d.get('Name'):
                info = (f"Place: {d.get('Name')} | Type: {d.get('Type')} | "
                        f"Significance: {d.get('Significance')} | "
                        f"Fee: {d.get('Entrance Fee in INR')} INR | "
                        f"Time: {d.get('time needed to visit in hrs')} hrs")
                context_data.append(info)
        return context_data
    except Exception as e:
        st.error(f"Firestore Query Failed: {e}")
        return []

# --- 4. API FETCHERS ---
def get_flight_info(flight_id):
    clean = flight_id.replace(" ", "").upper()
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean}&api_key={st.secrets['AIRLABS_KEY']}"
    try:
        res = requests.get(url).json()
        if "response" in res and res["response"]:
            f = res["response"][0]
            # Get IATA code to resolve city
            dest_code = f.get('arr_iata')
            
            # Resolve City Name via AirLabs Airports API
            city_url = f"https://airlabs.co/api/v9/airports?iata_code={dest_code}&api_key={st.secrets['AIRLABS_KEY']}"
            city_res = requests.get(city_url).json()
            raw_city = "Unknown"
            if "response" in city_res and city_res["response"]:
                raw_city = city_res["response"][0].get('city', 'Unknown')
            
            f['mapped_city'] = map_city_to_csv(raw_city)
            return f
    except: return None

def get_traffic(origin, dest_iata):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {"origins": origin, "destinations": f"{dest_iata} Airport", "mode": "driving", "departure_time": "now", "key": st.secrets["GOOGLE_MAPS_KEY"]}
    try:
        data = requests.get(url, params=params).json()
        return {"sec": data['rows'][0]['elements'][0]['duration_in_traffic']['value'], "txt": data['rows'][0]['elements'][0]['duration_in_traffic']['text']}
    except: return None

# --- 5. UI ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️")

if 'city' not in st.session_state:
    st.session_state.city = None

st.title("✈️ Departly.ai")

col1, col2 = st.columns(2)
with col1: f_input = st.text_input("Flight Number", placeholder="e.g. 6E 2134")
with col2: h_input = st.text_input("Pickup Point", placeholder="e.g. Hoodi")

if st.button("Calculate My Safe Departure", use_container_width=True):
    with st.spinner("Analyzing..."):
        flight = get_flight_info(f_input)
        if flight:
            st.session_state.city = flight['mapped_city']
            traffic_data = get_traffic(h_input, flight['dep_iata'])
            
            if traffic_data:
                takeoff = parser.parse(flight['dep_time'])
                leave_by = (takeoff - timedelta(minutes=45)) - timedelta(seconds=traffic_data['sec'] + (105 * 60))
                
                st.success(f"### 🚪 Leave Home by: **{leave_by.strftime('%I:%M %p')}**")
                st.write(f"Destination Recognized: **{st.session_state.city}**")
            else: st.error("Traffic Error")
        else: st.error("Flight Not Found")

# --- 6. RAG SECTION ---
if st.session_state.city and st.session_state.city != "Unknown":
    st.divider()
    st.subheader(f"🗺️ RAG Itinerary for {st.session_state.city}")
    days = st.slider("Duration?", 1, 7, 3)
    
    if st.button("Generate Verified Itinerary"):
        with st.spinner("Connecting to Firebase..."):
            # 1. RETRIEVAL
            results = get_itinerary_context(st.session_state.city)
            
            # DEBUG
            st.caption(f"Found {len(results)} source documents in Firebase for {st.session_state.city}")

            if results:
                # 2. GENERATION
                context_str = "\n".join(results)
                prompt = f"""
                Grounded Itinerary Request:
                Destination: {st.session_state.city}
                Data: {context_str}
                
                Create a logical {days}-day plan. Mention entrance fees and significance from the data.
                """
                res = client.models.generate_content(model='gemini-3-flash-preview', contents=prompt)
                st.info(res.text)
            else:
                st.warning(f"No match in Firebase for '{st.session_state.city}'. Please check if your CSV uses this exact spelling.")

st.markdown("---")
st.caption("2025 Departly.ai | RAG-Grounded Intelligence")
