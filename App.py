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

# --- 2. THE UNIVERSAL KEY FIX ---
# This function stops the app from "hanging" by fixing the private key format
def initialize_firebase():
    if not firebase_admin._apps:
        try:
            # 1. Load from Secrets
            if "FIREBASE_KEY" in st.secrets:
                raw_key = st.secrets["FIREBASE_KEY"]
            else:
                st.error("🚨 Secrets Error: 'FIREBASE_KEY' not found.")
                st.stop()
            
            # 2. Parse JSON string
            key_dict = json.loads(raw_key)
            
            # 3. CRITICAL FIX: Replace escaped newlines with real ones
            if "private_key" in key_dict:
                key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
            
            # 4. Initialize
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
            
        except Exception as e:
            st.error(f"🔥 Firebase Auth Error: {e}")
            st.stop()

# Run initialization immediately
initialize_firebase()
db = firestore.client()
client = genai.Client(api_key=st.secrets["GEMINI_KEY"])

# --- 3. DATA MAPPING (Synonyms) ---
# Maps Airport Codes -> List of synonyms to search in Firestore
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
    "IXB": ["Darjeeling", "Siliguri"]
}

# --- 4. CORE FUNCTIONS ---

def get_flight_data(flight_input):
    """Fetches flight and determines target cities."""
    clean_iata = flight_input.replace(" ", "").upper()
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={st.secrets['AIRLABS_KEY']}"
    
    try:
        res = requests.get(url).json()
        if "response" in res and res["response"]:
            f_data = res["response"][0]
            
            # Identify Destination Code
            code = f_data.get('arr_iata') or f_data.get('arr_icao')
            f_data['dest_code'] = code
            
            # Map Code to City List
            if code in CITY_VARIANTS:
                f_data['targets'] = CITY_VARIANTS[code]
                f_data['display'] = CITY_VARIANTS[code][0]
            else:
                # Fallback: API Lookup for rare airports
                try:
                    air_url = f"https://airlabs.co/api/v9/airports?iata_code={code}&api_key={st.secrets['AIRLABS_KEY']}"
                    air_res = requests.get(air_url).json()
                    city = air_res["response"][0].get('city')
                    f_data['targets'] = [city] if city else []
                    f_data['display'] = city if city else "Unknown"
                except:
                    f_data['targets'] = []
                    f_data['display'] = "Unknown"
                
            return f_data
    except Exception as e:
        st.error(f"Flight API Error: {e}")
    return None

def get_rag_data(target_cities):
    """
    Loops through synonyms (e.g. 'Delhi', 'New Delhi') to fetch data.
    Returns: List of formatted strings, List of debug logs
    """
    all_docs = []
    logs = []
    
    for city in target_cities:
        clean_city = city.strip()
        logs.append(f"Searching for: '{clean_city}'")
        try:
            # Simple query
            docs = db.collection("itineraries_knowledge_base").where("City", "==", clean_city).stream()
            
            count = 0
            for doc in docs:
                d = doc.to_dict()
                if d.get('Name'):
                    # Create a clean text block for the AI
                    entry = (f"• {d.get('Name')} ({d.get('Type')}): {d.get('Significance')}. "
                             f"Fee: {d.get('Entrance Fee in INR')} INR. "
                             f"Time: {d.get('time needed to visit in hrs')}h. ")
                    all_docs.append(entry)
                    count += 1
            logs.append(f"  -> Found {count} records")
        except Exception as e:
            logs.append(f"  -> Error: {e}")
            
    return all_docs, logs

def get_traffic(origin, dest_code):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {"origins": origin, "destinations": f"{dest_code} Airport", "mode": "driving", "departure_time": "now", "key": st.secrets["GOOGLE_MAPS_KEY"]}
    try:
        data = requests.get(url, params=params).json()
        elem = data['rows'][0]['elements'][0]
        return {"sec": elem['duration_in_traffic']['value'], "txt": elem['duration_in_traffic']['text']}
    except: return None

# --- 5. UI LOGIC ---

if 'flight_info' not in st.session_state:
    st.session_state.flight_info = None

st.title("✈️ Departly.ai")
st.write("Precision Flight Planning + Database-Grounded Itineraries")

col1, col2 = st.columns(2)
with col1: f_in = st.text_input("Flight Number", placeholder="e.g. 6E 6433")
with col2: p_in = st.text_input("Pickup Point", placeholder="e.g. Hoodi, Bangalore")

if st.button("Calculate Departure", type="primary", use_container_width=True):
    with st.spinner("Analyzing Flight Network..."):
        flight = get_flight_data(f_in)
        if flight:
            st.session_state.flight_info = flight
            traffic = get_traffic(p_in, flight['dep_iata'])
            
            if traffic:
                takeoff = parser.parse(flight['dep_time'])
                # 45m boarding + traffic + 60m buffer
                leave = (takeoff - timedelta(minutes=45)) - timedelta(seconds=traffic['sec'] + (60 * 60)) 
                
                st.balloons()
                st.success(f"### 🚪 Leave Home by: **{leave.strftime('%I:%M %p')}**")
                
                st.info(f"Flight **{flight['flight_iata']}** to **{flight['display']}** ({flight['dest_code']})")
                
                m1, m2, m3 = st.columns(3)
                m1.metric("Takeoff", takeoff.strftime("%H:%M"))
                m2.metric("Traffic", traffic['txt'])
                m3.metric("Status", "On Time")
            else:
                st.error("Could not find route. Check Pickup Point.")
        else:
            st.error("Flight not found.")

# --- 6. RAG ITINERARY GENERATOR ---
if st.session_state.flight_info:
    st.divider()
    
    current_targets = st.session_state.flight_info['targets']
    display_city = st.session_state.flight_info['display']
    
    st.subheader(f"🗺️ Plan Your {display_city} Trip")
    
    # Manual Override for 'Unknown' cities
    if display_city == "Unknown" or not current_targets:
        st.warning("⚠️ City not automatically matched.")
        manual_city = st.selectbox("Select City Manually:", ["Delhi", "Mumbai", "Bangalore", "Goa", "Hyderabad", "Kolkata", "Jaipur"])
        current_targets = [manual_city]
        display_city = manual_city
    
    days = st.slider("Trip Duration (Days)", 1, 7, 3)
    
    if st.button("Generate Verified Itinerary", use_container_width=True):
        with st.spinner(f"Querying verified data for {display_city}..."):
            
            # 1. FETCH DATA
            rag_docs, debug_logs = get_rag_data(current_targets)
            
            # 2. DEBUGGER (Click this to see if data was found!)
            with st.expander(f"📚 Database Inspector ({len(rag_docs)} records)"):
                st.write("Logs:", debug_logs)
                if rag_docs:
                    st.write(rag_docs[:5]) # Show first 5 records
                else:
                    st.error("❌ No documents found. Check Firebase collection name 'itineraries_knowledge_base'.")

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
                - Use 'Best Time' to order the day.
                - Mention 'Entry Fee' and 'Significance' for every place.
                - Do not invent places.
                """
                try:
                    res = client.models.generate_content(model='gemini-2.0-flash-exp', contents=prompt)
                    st.markdown("### ✨ Your Verified Itinerary")
                    st.markdown(res.text)
                except Exception as e:
                    st.error(f"Gemini API Error: {e}")
            else:
                st.warning("The database returned 0 results, so an itinerary could not be generated.")

st.markdown("---")
st.caption("2025 Departly.ai | RAG-Grounded Intelligence")
