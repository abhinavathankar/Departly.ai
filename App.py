import streamlit as st
import requests
import json
import time
import google.auth.transport.requests
from google.oauth2 import service_account
from google import genai
from datetime import datetime, timedelta
from dateutil import parser
from streamlit_js_eval import get_geolocation

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

@st.cache_resource
def get_db_client():
    return FirestoreREST(st.secrets)

try:
    db_http = get_db_client()
    client = genai.Client(api_key=st.secrets["GEMINI_KEY"])
except Exception as e:
    st.error(f"Service Init Error: {e}")

# --- SETTINGS ---
# Using the Stable Production Model to avoid 429 Limit 0 errors
MODEL_ID = 'gemini-1.5-flash' 

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

# --- 3. HELPERS ---
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

def reverse_geocode(lat, lng):
    url = f"https://maps.googleapis.com/maps/api/geocode/json?latlng={lat},{lng}&key={st.secrets['GOOGLE_MAPS_KEY']}"
    try:
        data = requests.get(url, timeout=5).json()
        if data['status'] == 'OK':
            return data['results'][0]['formatted_address']
    except: pass
    return f"{lat},{lng}"

# --- UPDATED HELPER: ROBUST RETRY LOGIC ---
def generate_with_retry(client, model_id, prompt, max_retries=3):
    """
    Attempts to generate content with exponential backoff.
    Uses string checking to avoid import errors.
    """
    base_delay = 2 
    
    for attempt in range(max_retries):
        try:
            return client.models.generate_content(
                model=model_id, 
                contents=prompt
            )
        except Exception as e:
            error_str = str(e)
            # Check for 429 / Resource Exhausted errors
            if "429" in error_str or "ResourceExhausted" in type(e).__name__:
                if attempt == max_retries - 1:
                    st.error(f"⚠️ Quota exceeded on {model_id}. Please try again later.")
                    return None
                
                wait_time = base_delay * (2 ** attempt)
                st.toast(f"⏳ High traffic. Retrying in {wait_time}s...", icon="🔄")
                time.sleep(wait_time)
            else:
                # If it's a different error, stop retrying
                st.error(f"❌ API Error: {e}")
                return None
    return None

# --- 4. MAIN UI ---
st.title("✈️ Departly.ai")

# PERSISTENT DATA
if 'flight_info' not in st.session_state: st.session_state.flight_info = None
if 'journey_meta' not in st.session_state: st.session_state.journey_meta = None
if 'pickup_address' not in st.session_state: st.session_state.pickup_address = ""

# --- INVISIBLE GPS LOGIC ---
loc_data = get_geolocation(component_key='gps_trigger')
if loc_data and 'coords' in loc_data:
    lat = loc_data['coords']['latitude']
    lng = loc_data['coords']['longitude']
    if not st.session_state.pickup_address:
        st.session_state.pickup_address = reverse_geocode(lat, lng)

# --- INPUTS ---
col1, col2 = st.columns([1, 1])
with col1:
    airline_name = st.selectbox("Select Airline", list(INDIAN_AIRLINES.keys()))
with col2:
    flight_num = st.text_input("Flight Number", placeholder="e.g. 6433")

p_in = st.text_input("Pickup Point", 
                     value=st.session_state.pickup_address, 
                     placeholder="e.g. Hoodi, Bangalore")

if p_in != st.session_state.pickup_address:
    st.session_state.pickup_address = p_in

airline_code = INDIAN_AIRLINES[airline_name]

# -----------------------------

if st.button("Calculate Journey", type="primary", use_container_width=True):
    if not (flight_num and p_in):
        st.warning("Please enter both details.")
    else:
        full_flight_code = f"{airline_code}{flight_num}"
        with st.spinner(f"Analyzing {full_flight_code}..."):
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
    
    c1, c2 = st.columns(2)
    c1.metric("From", j["dep_iata"])
    c2.metric("To", j["arr_iata"])
    
    c3, c4 = st.columns(2)
    c3.metric("Takeoff", j["takeoff"])
    c4.metric("Landing", j["landing"])

    st.success(f"### 🚪 Leave Home by: **{j['leave_time']}**")
    
    with st.expander("⏱️ Journey Breakdown", expanded=True):
        st.write(f"🚗 **Travel to Airport:** {j['traffic_txt']}")
        st.write(f"🛂 **Security & Baggage Drop:** 30 mins")
        st.write(f"✈️ **Boarding Gate Close:** 45 mins")

# --- 5. ITINERARY SECTION (Updated) ---
if st.session_state.flight_info:
    st.markdown("---")
    targets = st.session_state.flight_info['targets']
    display = st.session_state.flight_info['display']
    st.subheader(f"🗺️ Plan Trip: {display}")
    days = st.slider("Trip Duration (Days)", 1, 7, 3)
    
    # Using the stable model defined at the top
    CURRENT_MODEL = MODEL_ID
    
    if st.button(f"Generate Itinerary (Gemini)", use_container_width=True):
        
        with st.spinner(f"Creating itinerary using {CURRENT_MODEL}..."):
            # 1. RAG Retrieval
            rag_docs = []
            for city in targets:
                try:
                    rag_docs.extend(db_http.query_city(city.strip()))
                except:
                    pass
            
            if rag_docs:
                context = "\n".join([f"• {d.get('Name')} ({d.get('Type')})" for d in rag_docs])
                prompt = f"""
                You are an expert travel agent. Create a {days}-day itinerary for {display}.
                Strictly use the following local recommendations if relevant:
                {context}
                
                Format the response with Markdown, using emojis for each section.
                """
                
                # 2. Call AI with Retry Handler
                res = generate_with_retry(client, CURRENT_MODEL, prompt)
                
                if res:
                    st.markdown("### ✨ Your Verified Itinerary")
                    st.markdown(res.text)
            else:
                st.warning("No database records found for this city. Try a major city like 'DEL' or 'BLR' to test.")
