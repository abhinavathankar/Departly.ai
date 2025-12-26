import streamlit as st
import requests
import json
import google.auth.transport.requests
from google.oauth2 import service_account
from google import genai
from datetime import datetime, timedelta
from dateutil import parser
from streamlit_js_eval import get_geolocation

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️", layout="centered")

# --- 2. OPTIMIZED SERVICES (Cached) ---
@st.cache_resource
def get_firestore_client(firebase_key_json):
    # We pass ONLY the JSON string or dict, not the whole st.secrets object
    try:
        if isinstance(firebase_key_json, str):
            key_dict = json.loads(firebase_key_json, strict=False)
        else:
            key_dict = dict(firebase_key_json)

        if "private_key" in key_dict:
            key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
        
        creds = service_account.Credentials.from_service_account_info(
            key_dict, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        return creds, key_dict.get("project_id")
    except Exception as e:
        return None, None

class FirestoreREST:
    def __init__(self, secrets):
        # FIX: We pass only the specific key section, which is hashable
        self.creds, self.project_id = get_firestore_client(dict(secrets["FIREBASE_KEY"]))
        
        if not self.creds:
            st.error("🔥 Auth Failed")
            st.stop()
        self.base_url = f"https://firestore.googleapis.com/v1/projects/{self.project_id}/databases/(default)/documents"

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
# We convert the secrets section to a standard dict to ensure it is hashable
db_http = FirestoreREST(st.secrets)
client = genai.Client(api_key=st.secrets["GEMINI_KEY"])

# --- SETTINGS ---
MODEL_ID = 'gemini-3-flash-preview'
INDIAN_AIRLINES = {
    "IndiGo": "6E", "Air India": "AI", "Vistara": "UK", 
    "SpiceJet": "SG", "Air India Express": "IX", "Akasa Air": "QP",
    "Alliance Air": "9I", "Star Air": "S5", "Fly91": "IC"
}
CITY_VARIANTS = {
    "DEL": ["Delhi", "New Delhi"], "BLR": ["Bengaluru", "Bangalore"],
    "BOM": ["Mumbai"], "MAA": ["Chennai"], "HYD": ["Hyderabad"],
    "GOI": ["Goa"], "JAI": ["Jaipur"], "CCU": ["Kolkata"]
}

# --- 3. HELPER FUNCTIONS (Cached) ---
@st.cache_data(ttl=300) 
def get_flight_data(iata_code):
    clean_iata = iata_code.replace(" ", "").upper()
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={st.secrets['AIRLABS_KEY']}"
    try:
        res = requests.get(url, timeout=8)
        res_json = res.json()
        if "response" in res_json and res_json["response"]:
            f_data = res_json["response"][0]
            f_data['origin_code'] = f_data.get('dep_iata') or f_data.get('dep_icao')
            dest_code = f_data.get('arr_iata') or f_data.get('arr_icao')
            f_data['dest_code'] = dest_code
            if dest_code in CITY_VARIANTS:
                f_data['targets'] = CITY_VARIANTS[dest_code]
                f_data['display'] = CITY_VARIANTS[dest_code][0]
            else:
                city_from_api = f_data.get('arr_city', 'Unknown City')
                f_data['targets'] = [city_from_api]
                f_data['display'] = city_from_api
            return f_data
    except: pass
    return None

@st.cache_data(ttl=600) 
def reverse_geocode(lat, lng):
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"latlng": f"{lat},{lng}", "key": st.secrets["GOOGLE_MAPS_KEY"]}
    try:
        res = requests.get(url, params=params).json()
        if res.get('status') == 'OK':
            return res['results'][0]['formatted_address']
    except: pass
    return None

def get_traffic(pickup_address, target_airport_code):
    destination_query = f"{target_airport_code} Airport"
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": pickup_address, "destinations": destination_query, 
        "mode": "driving", "departure_time": "now", "key": st.secrets["GOOGLE_MAPS_KEY"]
    }
    try:
        data = requests.get(url, params=params, timeout=5).json()
        if "rows" in data and data["rows"]:
            elem = data['rows'][0]['elements'][0]
            if elem['status'] == "OK":
                return {"sec": elem['duration_in_traffic']['value'], "txt": elem['duration_in_traffic']['text']}
    except: pass
    return {"sec": 5400, "txt": "1h 30m (Est)"}

# --- 4. MAIN UI ---
st.title("✈️ Departly.ai")

if 'flight_info' not in st.session_state: st.session_state.flight_info = None
if 'journey_meta' not in st.session_state: st.session_state.journey_meta = None
if 'pickup_loc' not in st.session_state: st.session_state.pickup_loc = ""

# --- INPUT CONTAINER ---
with st.container():
    # Row 1: Flight Details
    c1, c2 = st.columns([1, 1])
    with c1:
        airline_name = st.selectbox("Airline", list(INDIAN_AIRLINES.keys()))
        airline_code = INDIAN_AIRLINES[airline_name]
    with c2:
        flight_num = st.text_input("Flight Number", placeholder="e.g. 6433")

    # Row 2: Pickup & GPS (Aligned)
    c3, c4 = st.columns([3, 1]) 
    with c3:
        p_in = st.text_input("Pickup Point", value=st.session_state.pickup_loc, placeholder="Address or use GPS ->")
    with c4:
        st.write("") 
        st.write("") 
        loc_data = get_geolocation(component_key='get_loc', label="📍 Detect")

    # GPS Logic Handler
    if loc_data:
        lat = loc_data.get('coords', {}).get('latitude')
        lng = loc_data.get('coords', {}).get('longitude')
        if lat and lng:
            new_address = reverse_geocode(lat, lng)
            if new_address and new_address != st.session_state.pickup_loc:
                st.session_state.pickup_loc = new_address
                st.rerun()

    # Calculate Button
    if st.button("Calculate Journey", type="primary", use_container_width=True):
        if not (flight_num and p_in):
            st.warning("Please enter both details.")
        else:
            full_flight_code = f"{airline_code}{flight_num}"
            with st.spinner("Calculating timeline..."):
                flight = get_flight_data(full_flight_code)
                if flight:
                    traffic = get_traffic(p_in, flight['origin_code'])
                    takeoff_dt = parser.parse(flight['dep_time'])
                    total_buffer_sec = traffic['sec'] + (45 * 60) + (30 * 60)
                    leave_dt = takeoff_dt - timedelta(seconds=total_buffer_sec)
                    
                    st.session_state.flight_info = flight
                    st.session_state.journey_meta = {
                        "leave_time": leave_dt.strftime('%I:%M %p'),
                        "traffic_txt": traffic['txt'],
                        "dep_iata": flight.get('dep_iata'),
                        "arr_iata": flight.get('arr_iata'),
                        "takeoff": parser.parse(flight['dep_time']).strftime('%I:%M %p'),
                        "landing": parser.parse(flight['arr_time']).strftime('%I:%M %p')
                    }
                else:
                    st.error("Flight not found.")

# --- DISPLAY JOURNEY ---
if st.session_state.journey_meta:
    j = st.session_state.journey_meta
    st.markdown("---")
    st.subheader(f"🎫 Flight Dashboard")
    
    c_a, c_b = st.columns(2)
    c_a.metric("Origin", j["dep_iata"])
    c_b.metric("Dest", j["arr_iata"])
    
    c_c, c_d = st.columns(2)
    c_c.metric("Departure", j["takeoff"])
    c_d.metric("Arrival", j["landing"])

    st.success(f"### 🚪 Leave Home by: **{j['leave_time']}**")
    
    with st.expander("⏱️ Journey Breakdown", expanded=True):
        st.write(f"🚗 **Travel to Airport:** {j['traffic_txt']}")
        st.write(f"🛂 **Security Check:** 30 mins")
        st.write(f"✈️ **Boarding Gate:** 45 mins")

# --- ITINERARY SECTION ---
if st.session_state.flight_info:
    st.markdown("---")
    targets = st.session_state.flight_info['targets']
    display = st.session_state.flight_info['display']
    st.subheader(f"🗺️ Plan Trip: {display}")
    days = st.slider("Trip Duration (Days)", 1, 7, 3)
    
    if st.button(f"Generate Itinerary (Gemini 3 Flash)", use_container_width=True):
        with st.spinner("Generating itinerary..."):
            rag_docs = []
            for city in targets:
                rag_docs.extend(db_http.query_city(city.strip()))
            
            if rag_docs:
                context = "\n".join([f"• {d.get('Name')} ({d.get('Type')})" for d in rag_docs])
                prompt = f"Create a {days}-day itinerary for {display} using only this data:\n{context}"
                try:
                    res = client.models.generate_content(model=MODEL_ID, contents=prompt)
                    st.markdown("### ✨ Your Verified Itinerary")
                    st.markdown(res.text)
                except Exception as e:
                    st.error(f"AI Error: {e}")
            else:
                st.warning("No database records found for this city.")
