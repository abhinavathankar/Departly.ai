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

try:
    db_http = FirestoreREST(st.secrets)
    client = genai.Client(api_key=st.secrets["GEMINI_KEY"])
except Exception as e:
    st.error(f"Service Init Error: {e}")

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

# --- 4. MAIN UI ---
st.title("✈️ Departly.ai")

airline_name = st.selectbox("Select Airline", list(INDIAN_AIRLINES.keys()))
airline_code = INDIAN_AIRLINES[airline_name]
flight_num = st.text_input("Flight Number", placeholder="e.g. 6433")
p_in = st.text_input("Pickup Point", placeholder="e.g. Hoodi, Bangalore")

# Create a placeholder for the Departure Dashboard
dashboard_placeholder = st.empty()

if 'flight_info' not in st.session_state:
    st.session_state.flight_info = None

calc_button = st.button("Calculate Journey", type="primary", use_container_width=True)

if calc_button:
    if not (flight_num and p_in):
        st.warning("Please enter both details.")
    else:
        full_flight_code = f"{airline_code}{flight_num}"
        with st.spinner(f"Analyzing {full_flight_code}..."):
            flight = get_flight_data(full_flight_code)
            if flight:
                st.session_state.flight_info = flight
                
                # We put everything inside a "with" block of the placeholder
                with dashboard_placeholder.container():
                    st.markdown("---")
                    st.subheader(f"🎫 Flight {flight.get('flight_iata')}")
                    
                    m1, m2 = st.columns(2)
                    m1.metric("Origin", flight.get('dep_iata'))
                    m2.metric("Destination", flight.get('arr_iata'))
                    
                    m3, m4 = st.columns(2)
                    m3.metric("Departure", parser.parse(flight['dep_time']).strftime('%I:%M %p'))
                    m4.metric("Arrival", parser.parse(flight['arr_time']).strftime('%I:%M %p'))

                    traffic = get_traffic(p_in, flight['origin_code'])
                    takeoff_dt = parser.parse(flight['dep_time'])
                    total_buffer_sec = traffic['sec'] + (45 * 60) + (30 * 60)
                    leave_dt = takeoff_dt - timedelta(seconds=total_buffer_sec)
                    
                    st.success(f"### 🚪 Leave Home by: **{leave_dt.strftime('%I:%M %p')}**")
            else:
                st.error("Flight not found.")

# --- 5. ITINERARY SECTION ---
if st.session_state.flight_info:
    st.markdown("---")
    targets = st.session_state.flight_info['targets']
    display = st.session_state.flight_info['display']
    st.subheader(f"🗺️ Plan Your Trip")
    days = st.slider("Trip Duration (Days)", 1, 7, 3)
    
    gen_itinerary = st.button(f"Generate Itinerary for {display}", use_container_width=True)

    if gen_itinerary:
        # STEP 1: Clear the Departure Dashboard to remove background clutter
        dashboard_placeholder.empty()
        
        with st.spinner("Generating with Gemini 3 Flash..."):
            rag_docs = []
            for city in targets:
                rag_docs.extend(db_http.query_city(city.strip()))
            
            if rag_docs:
                context = "\n".join([f"• {d.get('Name')} ({d.get('Type')})" for d in rag_docs])
                prompt = f"Create a {days}-day itinerary for {display} using only this data:\n{context}"
                try:
                    res = client.models.generate_content(model=MODEL_ID, contents=prompt)
                    st.markdown(res.text)
                except Exception as e:
                    st.error(f"AI Error: {e}")
            else:
                st.warning("No records found.")
