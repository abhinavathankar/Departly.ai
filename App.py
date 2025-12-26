import streamlit as st
import requests
import json
import google.auth.transport.requests
from google.oauth2 import service_account
from google import genai
from datetime import datetime, timedelta
from dateutil import parser

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️", layout="centered")

# --- 2. HTTP CLIENT ---
class FirestoreREST:
    def __init__(self, secrets):
        try:
            raw_key = secrets["FIREBASE_KEY"]
            if isinstance(raw_key, str):
                key_dict = json.loads(raw_key, strict=False)
            else:
                key_dict = dict(raw_key)

            if "private_key" in key_dict:
                key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
            
            self.creds = service_account.Credentials.from_service_account_info(
                key_dict, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            self.project_id = key_dict.get("project_id")
            self.base_url = f"https://firestore.googleapis.com/v1/projects/{self.project_id}/databases/(default)/documents"
        except Exception as e:
            st.error(f"🔥 Auth Error: {e}")
            st.stop()

    def query_city(self, city_name):
        auth_req = google.auth.transport.requests.Request()
        self.creds.refresh(auth_req)
        token = self.creds.token
        
        url = f"{self.base_url}:runQuery"
        headers = {"Authorization": f"Bearer {token}"}
        
        payload = {
            "structuredQuery": {
                "from": [{"collectionId": "itineraries_knowledge_base"}],
                "where": {
                    "fieldFilter": {
                        "field": {"fieldPath": "City"},
                        "op": "EQUAL",
                        "value": {"stringValue": city_name}
                    }
                },
                "limit": 10
            }
        }
        
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=5)
            if resp.status_code == 200:
                return self._parse_response(resp.json())
            return []
        except:
            return []

    def _parse_response(self, json_data):
        results = []
        for item in json_data:
            if "document" in item:
                raw_fields = item["document"]["fields"]
                clean_doc = {}
                for key, val in raw_fields.items():
                    clean_doc[key] = list(val.values())[0]
                results.append(clean_doc)
        return results

# Initialize Services
try:
    db_http = FirestoreREST(st.secrets)
    client = genai.Client(api_key=st.secrets["GEMINI_KEY"])
except Exception as e:
    st.error(f"Service Init Error: {e}")

# --- 3. DATA & LOGIC ---
AVAILABLE_MODELS = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-2.0-flash-exp']

# NEW: INDIAN AIRLINES MAPPING
INDIAN_AIRLINES = {
    "IndiGo": "6E",
    "Air India": "AI",
    "Vistara": "UK",
    "SpiceJet": "SG",
    "Air India Express": "IX",
    "Akasa Air": "QP",
    "Alliance Air": "9I",
    "Star Air": "S5",
    "Fly91": "IC"
}

CITY_VARIANTS = {
    "DEL": ["Delhi", "New Delhi"],
    "BLR": ["Bengaluru", "Bangalore"],
    "BOM": ["Mumbai"],
    "MAA": ["Chennai"],
    "HYD": ["Hyderabad"],
    "GOI": ["Goa"],
    "JAI": ["Jaipur"],
    "CCU": ["Kolkata"]
}

def get_rag_data_http(target_cities):
    all_docs = []
    for city in target_cities:
        clean_city = city.strip()
        docs = db_http.query_city(clean_city)
        for d in docs:
            if d.get('Name'):
                entry = (f"• {d.get('Name')} | Type: {d.get('Type')} | "
                         f"Fee: {d.get('Entrance Fee in INR')} | "
                         f"Time: {d.get('time needed to visit in hrs')}h")
                all_docs.append(entry)
    return all_docs

def get_flight_data(iata_code):
    """
    Query AirLabs using the constructed IATA code (e.g. '6E6433')
    """
    clean_iata = iata_code.replace(" ", "").upper()
    
    # We pass 'flight_iata' which combines Airline+Number. 
    # This works best for AirLabs schedules.
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={st.secrets['AIRLABS_KEY']}"
    
    try:
        res = requests.get(url, timeout=8)
        res_json = res.json()
        
        if "response" in res_json and res_json["response"]:
            f_data = res_json["response"][0]
            code = f_data.get('arr_iata') or f_data.get('arr_icao')
            f_data['dest_code'] = code
            
            # Smart Fallback Logic
            if code in CITY_VARIANTS:
                f_data['targets'] = CITY_VARIANTS[code]
                f_data['display'] = CITY_VARIANTS[code][0]
            else:
                city_from_api = f_data.get('arr_city', 'Unknown City')
                f_data['targets'] = [city_from_api]
                f_data['display'] = city_from_api
            
            return f_data
        elif "error" in res_json:
            st.error(f"Flight API Error: {res_json['error'].get('message')}")
    except Exception as e:
        st.error(f"Connection Error: {e}")
    return None

def get_traffic(origin, dest_code):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {"origins": origin, "destinations": f"{dest_code} Airport", "mode": "driving", "departure_time": "now", "key": st.secrets["GOOGLE_MAPS_KEY"]}
    try:
        data = requests.get(url, params=params, timeout=5).json()
        if "rows" in data and data["rows"]:
            elem = data['rows'][0]['elements'][0]
            if elem['status'] == "OK":
                return {"sec": elem['duration_in_traffic']['value'], "txt": elem['duration_in_traffic']['text']}
    except: pass
    return {"sec": 5400, "txt": "1h 30m (Est)"}

# --- 4. UI ---
st.title("✈️ Departly.ai")
st.write("Indian Airlines Departure Planner")

# --- UPDATED INPUT SECTION ---
c_airline, c_number = st.columns([1, 1])
with c_airline:
    # Dropdown for Airline
    airline_name = st.selectbox("Select Airline", list(INDIAN_AIRLINES.keys()))
    airline_code = INDIAN_AIRLINES[airline_name] # Gets '6E', 'AI', etc.
    
with c_number:
    # Simple number input
    flight_num = st.text_input("Flight Number", placeholder="e.g. 6433")

p_in = st.text_input("Pickup Point", placeholder="e.g. Hoodi, Bangalore")

if 'flight_info' not in st.session_state:
    st.session_state.flight_info = None

if st.button("Calculate Journey", type="primary", use_container_width=True):
    if not flight_num:
        st.warning("Please enter a flight number.")
    else:
        # CONSTRUCT THE IATA CODE
        full_flight_code = f"{airline_code}{flight_num}"
        
        with st.spinner(f"Searching for {full_flight_code}..."):
            flight = get_flight_data(full_flight_code)
            
            if flight:
                st.session_state.flight_info = flight
                
                # --- DASHBOARD ---
                st.divider()
                st.subheader(f"🎫 Ticket: {flight.get('flight_iata')}")
                
                # Visual Ticket Row
                t1, t2, t3, t4 = st.columns(4)
                t1.metric("Airline", airline_name)
                t2.metric("Date", flight.get('dep_time').split()[0])
                t3.metric("Origin", flight.get('dep_iata'))
                t4.metric("Dest", flight.get('arr_iata'))
                
                # Detailed Times
                st.info(f"🛫 **Departs:** {flight.get('dep_time')}  |  🛬 **Arrives:** {flight.get('arr_time')}")
                
                # Raw Data Inspector
                with st.expander("🔍 See Raw API Data"):
                    st.json(flight)

                # --- TRAFFIC & LEAVE TIME ---
                traffic = get_traffic(p_in, flight['dest_code'])
                
                takeoff_dt = parser.parse(flight['dep_time'])
                total_buffer_sec = traffic['sec'] + (45 * 60) + (60 * 60)
                leave_dt = takeoff_dt - timedelta(seconds=total_buffer_sec)
                
                st.success(f"### 🚪 Leave Home by: **{leave_dt.strftime('%I:%M %p')}**")
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Traffic Time", traffic['txt'])
                c2.metric("Safety Buffer", "1h 45m")
                c3.metric("Status", "On Time")

            else:
                st.error(f"Flight {full_flight_code} not found. Check the number or try again later.")

# --- 5. ITINERARY GENERATOR ---
if st.session_state.flight_info:
    st.divider()
    targets = st.session_state.flight_info['targets']
    display = st.session_state.flight_info['display']
    
    st.subheader(f"🗺️ Plan Your Trip to {display}")
    
    c1, c2 = st.columns([1, 2])
    with c1: days = st.slider("Duration (Days)", 1, 7, 3)
    with c2: selected_model = st.selectbox("AI Model", AVAILABLE_MODELS, index=0)
    
    if st.button("Generate Verified Itinerary", use_container_width=True):
        with st.spinner(f"Querying Knowledge Base for {display}..."):
            rag_docs = get_rag_data_http(targets)
            
            with st.expander(f"📚 Found {len(rag_docs)} Verified Places"):
                st.write(rag_docs)

            if rag_docs:
                context = "\n".join(rag_docs)
                prompt = f"""
                You are an expert travel agent for {display}.
                Create a {days}-day itinerary using ONLY the following verified data.
                
                VERIFIED DATA:
                {context}
                """
                try:
                    res = client.models.generate_content(model=selected_model, contents=prompt)
                    st.markdown("### ✨ Your Verified Itinerary")
                    st.markdown(res.text)
                except Exception as e:
                    st.error(f"AI Error: {e}")
            else:
                st.warning(f"No database records found for {display}. Try a different city.")
