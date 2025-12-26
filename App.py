import streamlit as st
import requests
import json
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types
from datetime import datetime, timedelta
from dateutil import parser

# --- 1. FIREBASE INITIALIZATION ---
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

# --- 2. THE RAG ENGINE ---
def get_itinerary_context(city_name):
    """Fetches data and provides debug info to the UI"""
    # Force Title Case (e.g., 'delhi' -> 'Delhi')
    search_term = city_name.strip().title()
    
    try:
        # Note: 'City' must match your Firestore field name exactly
        docs = db.collection("itineraries_knowledge_base").where("City", "==", search_term).get(timeout=10)
        
        context_data = []
        for doc in docs:
            d = doc.to_dict()
            # Mapping CSV columns to readable text
            info = f"- {d.get('Name')}: {d.get('Significance')}. Fee: {d.get('Entrance Fee in INR')} INR. Visit: {d.get('time needed to visit in hrs')} hrs."
            context_data.append(info)
        
        return context_data # Returns a LIST
    except Exception as e:
        st.error(f"Database Query Failed: {e}")
        return []

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
        return {"seconds": data['rows'][0]['elements'][0]['duration_in_traffic']['value'], "text": data['rows'][0]['elements'][0]['duration_in_traffic']['text']}
    except: return None

# --- 4. MAIN UI ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️")

# Persistent state
if 'dest_city' not in st.session_state:
    st.session_state.dest_city = None

st.title("✈️ Departly.ai")

col1, col2 = st.columns(2)
with col1:
    flight_input = st.text_input("Flight Number", placeholder="e.g. 6E 2134")
with col2:
    home_input = st.text_input("Pickup Point", placeholder="e.g. Hoodi, Bangalore")

if st.button("Calculate My Safe Departure", use_container_width=True):
    with st.spinner("Calculating..."):
        flight = get_flight_data(flight_input)
        if flight:
            st.session_state.dest_city = flight.get('arr_city', 'Unknown')
            # (Time calculations simplified for brevity)
            st.success(f"Heading to: {st.session_state.dest_city}")
        else:
            st.error("Flight not found.")

# --- 5. RAG SECTION ---
if st.session_state.dest_city and st.session_state.dest_city != 'Unknown':
    st.divider()
    st.subheader(f"🗺️ Plan Your {st.session_state.dest_city} Trip")
    
    days = st.slider("Days?", 1, 7, 3)
    
    if st.button("Generate Itinerary"):
        with st.spinner("Fetching Data from Firebase..."):
            # Step 1: Retrieval
            results = get_itinerary_context(st.session_state.dest_city)
            
            # DEBUG LABEL (Remove after testing)
            st.write(f"🔍 Database Check: Found {len(results)} places for {st.session_state.dest_city}")

            if len(results) > 0:
                # Step 2: Generation
                context_str = "\n".join(results)
                prompt = f"Using this data: {context_str}, create a {days}-day itinerary for {st.session_state.dest_city}."
                
                try:
                    response = client.models.generate_content(model='gemini-3-flash-preview', contents=prompt)
                    st.info(response.text)
                except Exception as e:
                    st.error(f"AI Error: {e}")
            else:
                st.warning(f"No records for '{st.session_state.dest_city}' in your database. Ensure the City name in Firebase starts with a Capital letter.")

st.markdown("---")
st.caption("Powered by Firebase RAG & Gemini 3")
