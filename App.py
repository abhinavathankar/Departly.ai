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

db_http = FirestoreREST(st.secrets)
client = genai.Client(api_key=st.secrets["GEMINI_KEY"])
AVAILABLE_MODELS = ['gemini-2.0-flash-exp', 'gemini-1.5-flash', 'gemini-1.5-pro']

# --- 3. FLIGHT & TRAFFIC LOGIC ---
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

def get_flight_data(flight_input):
    clean_iata = flight_input.replace(" ", "").upper()
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={st.secrets['AIRLABS_KEY']}"
    try:
        res = requests.get(url, timeout=5).json()
        if "response" in res and res["response"]:
            f_data = res["response"][0]
            code = f_data.get('arr_iata') or f_data.get('arr_icao')
            f_data['dest_code'] = code
            if code in CITY_VARIANTS:
                f_data['targets'] = CITY_VARIANTS[code]
                f_data['display'] = CITY_VARIANTS[code][0]
            else:
                f_data['targets'] = ["Delhi"]
                f_data['display'] = "Unknown"
            return f_data
    except: pass
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
if 'flight_info' not in st.session_state:
    st.session_state.flight_info = None

st.title("✈️ Departly.ai")
col1, col2 = st.columns(2)
with col1: f_in = st.text_input("Flight Number", placeholder="e.g. 6E 6433")
with col2: p_in = st.text_input("Pickup Point", placeholder="e.g. Hoodi, Bangalore")

if st.button("Calculate Departure", type="primary", use_container_width=True):
    with st.spinner("Fetching Data..."):
        flight = get_flight_data(f_in)
        
        if flight:
            st.session_state.flight_info = flight
            
            # --- NEW: RAW DATA VISUALIZER ---
            with st.expander("🔍 Raw API Data (Check Time Here)", expanded=True):
                st.write(f"**Flight No:** {flight.get('flight_iata')}")
                st.write(f"**From:** {flight.get('dep_iata')} ➝ **To:** {flight.get('arr_iata')}")
                st.write(f"**Dep Time (API):** `{flight.get('dep_time')}`")
                st.write(f"**Arr Time (API):** `{flight.get('arr_time')}`")
                st.json(flight) # Full JSON dump
            
            traffic = get_traffic(p_in, flight['dest_code'])
            
            # Logic
            takeoff_dt = parser.parse(flight['dep_time'])
            total_buffer_sec = traffic['sec'] + (45 * 60) + (60 * 60)
            leave_dt = takeoff_dt - timedelta(seconds=total_buffer_sec)
            
            st.success(f"### 🚪 Leave Home by: **{leave_dt.strftime('%I:%M %p')}**")

            # Calculation breakdown
            c1, c2, c3 = st.columns(3)
            c1.metric("Takeoff", takeoff_dt.strftime('%I:%M %p'))
            c2.metric("Traffic", traffic['txt'])
            c3.metric("Buffer", "1h 45m")

        else:
            st.error("Flight not found.")

if st.session_state.flight_info:
    st.divider()
    targets = st.session_state.flight_info['targets']
    display = st.session_state.flight_info['display']
    
    st.subheader(f"🗺️ Guide for {display}")
    
    c1, c2 = st.columns([1, 2])
    with c1: days = st.slider("Trip Duration (Days)", 1, 7, 3)
    with c2: selected_model = st.selectbox("AI Model", AVAILABLE_MODELS, index=1)
    
    if st.button("Generate Verified Itinerary", use_container_width=True):
        with st.spinner(f"Fetching verified data for {display}..."):
            rag_docs = get_rag_data_http(targets)
            
            with st.expander(f"📚 Data Inspector ({len(rag_docs)} records)"):
                st.write(rag_docs)

            if rag_docs:
                context = "\n".join(rag_docs)
                prompt = f"Create a {days}-day itinerary for {display} using this data:\n{context}"
                try:
                    res = client.models.generate_content(model=selected_model, contents=prompt)
                    st.markdown("### ✨ Your Verified Itinerary")
                    st.markdown(res.text)
                except Exception as e:
                    st.error(f"AI Error: {e}")
            else:
                st.warning("No records found via HTTP.")
