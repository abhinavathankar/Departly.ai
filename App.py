import streamlit as st
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types
from datetime import datetime, timedelta
from dateutil import parser

# --- 1. INITIALIZATION ---
if not firebase_admin._apps:
    # Ensure serviceAccountKey.json is in your project folder
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

client = genai.Client(api_key=st.secrets["GEMINI_KEY"])

# --- 2. RAG HELPER FUNCTION ---
def get_itinerary_context(city_name):
    """Retrieves place data from Firestore with error handling"""
    # Force Title Case to match CSV format (e.g., 'delhi' -> 'Delhi')
    formatted_city = city_name.strip().title()
    
    try:
        # Use a timeout to prevent infinite 'circling' if the DB is slow
        docs = db.collection("itineraries_knowledge_base").where("City", "==", formatted_city).get(timeout=10)
        
        context_data = []
        for doc in docs:
            d = doc.to_dict()
            # Use .get() to avoid crashes on empty CSV cells
            place_info = (
                f"- {d.get('Name', 'Unknown')}: {d.get('Significance', 'No details')}. "
                f"Fee: {d.get('Entrance Fee in INR', 'N/A')} INR. "
                f"Time: {d.get('time needed to visit in hrs', '2')} hrs."
            )
            context_data.append(place_info)
        
        return "\n".join(context_data) if context_data else None
    except Exception as e:
        st.error(f"Database Error: {e}")
        return None

# --- 3. API WRAPPERS ---
def get_flight_data(flight_input):
    clean_iata = flight_input.replace(" ", "").upper()
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={st.secrets['AIRLABS_KEY']}"
    try:
        res = requests.get(url).json()
        return res["response"][0] if "response" in res and res["response"] else None
    except: return None

def get_travel_metrics(origin, airport_code):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {"origins": origin, "destinations": f"{airport_code} Airport", "mode": "driving", "departure_time": "now", "key": st.secrets["GOOGLE_MAPS_KEY"]}
    try:
        data = requests.get(url, params=params).json()
        element = data['rows'][0]['elements'][0]
        return {"seconds": element['duration_in_traffic']['value'], "text": element['duration_in_traffic']['text']}
    except: return None

# --- 4. UI SETUP ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️", layout="centered")

# Use Session State to keep data across button clicks
if 'dest_city' not in st.session_state:
    st.session_state.dest_city = None

st.title("✈️ Departly.ai")
st.write("Luxury Travel Advisor with Firebase RAG.")

col1, col2 = st.columns(2)
with col1:
    flight_input = st.text_input("Flight Number", placeholder="e.g. 6E 2134")
with col2:
    home_input = st.text_input("Pickup Point", placeholder="e.g. Hoodi, Bangalore")

if st.button("Calculate My Safe Departure", use_container_width=True):
    if not home_input or not flight_input:
        st.warning("Please enter both flight and pickup location.")
    else:
        with st.spinner("Analyzing schedule..."):
            flight = get_flight_data(flight_input)
            if flight:
                takeoff_dt = parser.parse(flight['dep_time'])
                boarding_
