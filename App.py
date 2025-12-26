import streamlit as st
import requests
import json
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from datetime import datetime, timedelta
from dateutil import parser

# --- 1. SETUP & CONFIG ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️", layout="centered")

# Initialize Firebase
if not firebase_admin._apps:
    try:
        key_dict = json.loads(st.secrets["FIREBASE_KEY"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🔥 Critical Firebase Error: {e}")
        st.stop()

db = firestore.client()
client = genai.Client(api_key=st.secrets["GEMINI_KEY"])

# --- 2. DATA MAPPING (The "Brain") ---
# Maps Airport Codes -> List of EXACT CSV City Names
# Based on your file: "Delhi", "New Delhi", "Bengaluru", "Bangalore" are all distinct.
CITY_VARIANTS = {
    "DEL": ["Delhi", "New Delhi"],
    "BLR": ["Bengaluru", "Bangalore"],
    "BOM": ["Mumbai"],
    "MAA": ["Chennai"],
    "CCU": ["Kolkata"],
    "HYD": ["Hyderabad"],
    "GOI": ["Goa"],
    "AMD": ["Ahmedabad"],
    "PNQ": ["Pune"],
    "JAI": ["Jaipur"],
    "COK": ["Kochi", "Cochin"],
    "VNS": ["Varanasi"],
    "IXC": ["Chandigarh"],
    "ATQ": ["Amritsar"],
    "JGA": ["Jamnagar"],
    "IXZ": ["Port Blair"],
    "IXB": ["Darjeeling", "Siliguri"]
}

# --- 3. ROBUST FUNCTIONS ---

def get_flight_data(flight_input):
    """Fetches flight and determines target cities."""
    clean_iata = flight_input.replace(" ", "").upper()
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={st.secrets['AIRLABS_KEY']}"
    
    try:
        res = requests.get(url).json()
        if "response" in res and res["response"]:
            f_data = res["response"][0]
            
            # 1. Identify Destination Code
            code = f_data.get('arr_iata') or f_data.get('arr_icao')
            f_data['dest_code'] = code
            
            # 2. Map Code to City List
            if code in CITY_VARIANTS:
                f_data['targets'] = CITY_VARIANTS[code]
                f_data['display'] = CITY_VARIANTS[code][0]
            else:
                # API Fallback for rare airports
                f_data['targets'] = []
                f_data['display'] = "Unknown"
                
            return f_data
    except Exception as e:
        st.error(f"Flight API Error: {e}")
    return None

def get_rag_data(target_cities):
    """
    Loops through ALL variants (e.g. Delhi AND New Delhi) to fetch every possible row.
    """
    all_docs = []
    debug_log = []
    
    for city in target_cities:
        # Clean the string perfectly
        clean_city = city.strip() 
        debug_log.append(f"Querying Firestore for City == '{clean_city}'...")
        
        try:
            # Simple, direct query for this specific variant
            docs = db.collection("itineraries_knowledge_base").where("City", "==", clean_city).stream()
            
            count = 0
            for doc in docs:
                d = doc.to_dict()
                if d.get('Name'): # Ensure valid data
                    # Format as a clean string for Gemini
                    entry = (f"• {d.get('Name')} ({d.get('Type')}): {d.get('Significance')}. "
                             f"Fee: {d.get('Entrance Fee in INR')} INR. "
                             f"Time: {d.get('time needed to visit in hrs')}h.")
                    all_docs.append(entry)
                    count += 1
            debug_log.append(f"  -> Found {count} records.")
            
        except Exception as e:
            debug_log.append(f"  -> Error: {e}")
            
    return all_docs, debug_log

def get_traffic(origin, dest_code):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {"origins": origin, "destinations": f"{dest_code} Airport", "mode": "driving", "departure_time": "now", "key": st.secrets["GOOGLE_MAPS_KEY"]}
    try:
        data = requests.get(url, params=params).json()
        elem = data['rows'][0]['elements'][0]
        return {"sec": elem['duration_in_traffic']['value'], "txt": elem['duration_in_traffic']['text']}
    except: return None

# --- 4. UI LOGIC ---
if 'flight_info' not in st.session_state:
    st.session_state.flight_info = None

st.title("✈️ Departly.ai")
st.write("Precision Flight Planning + Database-Grounded Itineraries")

col1, col2 = st.columns(2)
with col1: f_in = st.text_input("Flight Number", placeholder="e.g. 6E 2134")
with col2: p_in = st.text_input("Pickup Point", placeholder="e.g. Hoodi, Bangalore")

if st.button("Calculate Departure", type="primary", use_container_width=True):
    with st.spinner("Analyzing..."):
        flight = get_flight_data(f_in)
        if flight:
            st.session_state.flight_info = flight
            traffic = get_traffic(p_in, flight['dep_iata'])
            
            if traffic:
                takeoff = parser.parse(flight['dep_time'])
                leave = (takeoff - timedelta(minutes=45)) - timedelta(seconds=traffic['sec'] + (6300)) # 105 mins buffer
                
                st.balloons()
                st.success(f"### 🚪 Leave Home by: **{leave.strftime('%I:%M %p')}**")
                
                # Show detected destination clearly
                st.info(f"Flight to **{flight['display']}** ({flight['dest_code']})")
                
                m1, m2, m3 = st.columns(3)
                m1.metric("Takeoff", takeoff.strftime("%H:%M"))
                m2.metric("Traffic", traffic['txt'])
                m3.metric("Status", "On Time")
            else:
                st.error("Could not find route. Check Pickup Point.")
        else:
            st.error("Flight not found.")

# --- 5. RAG ITINERARY GENERATOR ---
if st.session_state.flight_info:
    st.divider()
    
    # Allow Manual Override if "Unknown"
    current_targets = st.session_state.flight_info['targets']
    display_city = st.session_state.flight_info['display']
    
    st.subheader(f"🗺️ Intelligence for {display_city}")
    
    if display_city == "Unknown":
        st.warning("⚠️ City not automatically matched.")
        # Fallback list of top cities
        manual_city = st.selectbox("Select City Manually:", ["Delhi", "Mumbai", "Bangalore", "Goa", "Hyderabad"])
        current_targets = [manual_city]
        display_city = manual_city
    
    days = st.slider("Days", 1, 7, 3)
    
    if st.button("Generate Verified Itinerary", use_container_width=True):
        with st.spinner(f"Querying database for {current_targets}..."):
            
            # 1. FETCH DATA
            rag_docs, logs = get_rag_data(current_targets)
            
            # 2. DEBUG INSPECTOR (Crucial for you to see what happened)
            with st.expander("🔍 Database Inspector (Click to see raw data)"):
                st.write("Debug Logs:", logs)
                if rag_docs:
                    st.write(f"Loaded {len(rag_docs)} attractions:")
                    st.write(rag_docs)
                else:
                    st.error("❌ No documents found. Check if Firestore collection name is 'itineraries_knowledge_base' and City spelling matches.")

            # 3. GENERATE AI RESPONSE
            if rag_docs:
                context_str = "\n".join(rag_docs)
                prompt = f"""
                You are a luxury travel planner.
                Destination: {display_city}
                Verified Database Data:
                {context_str}
                
                Task: Create a {days}-day itinerary using ONLY the data above.
                Requirements:
                - Mention 'Entry Fee' and 'Significance' for every place.
                - Do not hallucinate places not in the data.
                """
                try:
                    res = client.models.generate_content(model='gemini-3-flash-preview', contents=prompt)
                    st.markdown("### ✨ Your Verified Itinerary")
                    st.markdown(res.text)
                except Exception as e:
                    st.error(f"Gemini API Error: {e}")
            else:
                st.warning("The database returned 0 results, so an itinerary could not be generated.")

st.markdown("---")
st.caption("2025 Departly.ai | Firebase RAG Diagnostic Mode")
