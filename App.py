import streamlit as st
import requests
import json
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types
from datetime import datetime, timedelta
from dateutil import parser

# --- 1. FIREBASE & AI INITIALIZATION ---
if not firebase_admin._apps:
    try:
        # Pulls from st.secrets["FIREBASE_KEY"]
        key_dict = json.loads(st.secrets["FIREBASE_KEY"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Firebase Config Error: {e}")
        st.stop()

db = firestore.client()
client = genai.Client(api_key=st.secrets["GEMINI_KEY"])

# --- 2. CITY MAPPING FALLBACK ---
# Sometimes APIs return 'DEL' instead of 'Delhi'. This maps common codes to your CSV City names.
IATA_CITY_MAP = {
    "DEL": "Delhi",
    "BLR": "Bengaluru",
    "BOM": "Mumbai",
    "MAA": "Chennai",
    "HYD": "Hyderabad",
    "CCU": "Kolkata",
    "GOI": "Goa",
    "PNQ": "Pune",
    "AMD": "Ahmedabad",
    "JAI": "Jaipur",
    "LKO": "Lucknow",
    "COK": "Kochi",
    "VNS": "Varanasi"
}

# --- 3. RAG ENGINE ---
def get_itinerary_context(city_name):
    """Fetches data from Firestore collection 'itineraries_knowledge_base'"""
    if not city_name or city_name == "Unknown":
        return []
        
    search_term = city_name.strip().title()
    # Handle "New Delhi" vs "Delhi" mapping if necessary
    if search_term == "New Delhi": search_term = "Delhi"
    
    try:
        # EXACT Match query on the 'City' field
        docs = db.collection("itineraries_knowledge_base").where("City", "==", search_term).get(timeout=10)
        
        context_data = []
        for doc in docs:
            d = doc.to_dict()
            info = f"- {d.get('Name')}: {d.get('Significance')}. Fee: {d.get('Entrance Fee in INR')} INR. Time: {d.get('time needed to visit in hrs')} hrs."
            context_data.append(info)
        return context_data
    except Exception as e:
        st.error(f"Database Query Error: {e}")
        return []

# --- 4. FLIGHT & TRAFFIC LOGIC ---
def get_flight_data(flight_input):
    clean_iata = flight_input.replace(" ", "").upper()
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={st.secrets['AIRLABS_KEY']}"
    try:
        res = requests.get(url).json()
        if "response" in res and res["response"]:
            f_data = res["response"][0]
            # IMPROVED CITY DETECTION
            city = f_data.get('arr_city')
            iata = f_data.get('arr_iata')
            
            # If city is missing, use the IATA map, otherwise use IATA itself
            final_city = city if city else IATA_CITY_MAP.get(iata, iata)
            f_data['detected_city'] = final_city
            return f_data
    except: return None
    return None

def get_travel_metrics(origin, airport_code):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {"origins": origin, "destinations": f"{airport_code} Airport", "mode": "driving", "departure_time": "now", "key": st.secrets["GOOGLE_MAPS_KEY"]}
    try:
        data = requests.get(url, params=params).json()
        if data['status'] == 'OK':
            element = data['rows'][0]['elements'][0]
            return {"seconds": element['duration_in_traffic']['value'], "text": element['duration_in_traffic']['text']}
    except: return None

# --- 5. UI ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️")

if 'dest_city' not in st.session_state:
    st.session_state.dest_city = None

st.title("✈️ Departly.ai")

col1, col2 = st.columns(2)
with col1:
    flight_input = st.text_input("Flight Number", placeholder="e.g. 6E 2134")
with col2:
    home_input = st.text_input("Pickup Point", placeholder="e.g. Hoodi, Bangalore")

if st.button("Calculate My Safe Departure", use_container_width=True):
    with st.spinner("Analyzing Journey..."):
        flight = get_flight_data(flight_input)
        if flight:
            # Using our improved detection logic
            st.session_state.dest_city = flight.get('detected_city', 'Unknown')
            
            takeoff_dt = parser.parse(flight['dep_time'])
            boarding_dt = takeoff_dt - timedelta(minutes=45)
            traffic = get_travel_metrics(home_input, flight['dep_iata'])
            
            if traffic:
                leave_dt = boarding_dt - timedelta(seconds=traffic['seconds'] + (105 * 60))
                st.balloons()
                st.success(f"### 🚪 Leave Home by: **{leave_dt.strftime('%I:%M %p')}**")
                st.write(f"Confirmed: Heading to **{st.session_state.dest_city}**")
            else:
                st.error("Traffic calculation failed.")
        else:
            st.error("Flight not found. Try a different number.")

# --- 6. RAG ITINERARY GENERATOR ---
if st.session_state.dest_city and st.session_state.dest_city != 'Unknown':
    st.divider()
    st.subheader(f"🗺️ {st.session_state.dest_city} Travel Plan")
    
    days = st.slider("Trip Duration (Days)", 1, 7, 3)
    
    if st.button("Generate RAG Itinerary", use_container_width=True):
        with st.spinner("Accessing Firebase Knowledge Base..."):
            results = get_itinerary_context(st.session_state.dest_city)
            
            # DEBUG INFO
            st.caption(f"Found {len(results)} local attractions in database for {st.session_state.dest_city}.")

            if len(results) > 0:
                context_str = "\n".join(results)
                prompt = f"""
                Grounded Itinerary Task:
                Based ONLY on this database data:
                {context_str}
                
                Create a logical {days}-day itinerary for {st.session_state.dest_city}. 
                Mention entrance fees and why these places are significant.
                """
                try:
                    response = client.models.generate_content(model='gemini-3-flash-preview', contents=prompt)
                    st.info(response.text)
                except Exception as e:
                    st.error(f"AI Error: {e}")
            else:
                st.warning(f"City '{st.session_state.dest_city}' recognized, but no specific matches in your CSV/Firebase. Try 'Delhi' or 'Bengaluru'.")

st.markdown("---")
st.caption("Powered by Firebase RAG & Gemini 3")
