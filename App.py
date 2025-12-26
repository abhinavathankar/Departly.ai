import streamlit as st
import requests
import re
import google.auth.transport.requests
from google.oauth2 import service_account
from google import genai
from datetime import datetime, timedelta
from dateutil import parser

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️", layout="centered")

# --- 2. THE REGEX SCRAPER (Bypasses JSON Errors) ---
def extract_credentials_manually(text_content):
    """
    Scrapes the credentials using Regex, ignoring JSON formatting errors.
    """
    creds = {}
    
    # 1. Extract Project ID
    # Looks for: "project_id": "something"
    pid_match = re.search(r'"project_id"\s*:\s*"([^"]+)"', text_content)
    if pid_match:
        creds["project_id"] = pid_match.group(1)
        
    # 2. Extract Client Email
    # Looks for: "client_email": "something"
    email_match = re.search(r'"client_email"\s*:\s*"([^"]+)"', text_content)
    if email_match:
        creds["client_email"] = email_match.group(1)
        
    # 3. Extract Private Key (The Hard Part)
    # Looks for: "private_key": "ANYTHING HERE"
    # [^"]* matches everything including newlines until the next quote
    key_match = re.search(r'"private_key"\s*:\s*"([^"]*)"', text_content)
    if key_match:
        raw_key = key_match.group(1)
        # Fix the key: Convert literal \n to real newlines
        creds["private_key"] = raw_key.replace("\\n", "\n")
        
    return creds

# --- 3. ROBUST REST CLIENT ---
class FirestoreREST:
    def __init__(self, secrets):
        try:
            # Get the raw string from secrets
            raw_key_string = secrets["FIREBASE_KEY"]
            
            # USE THE SCRAPER instead of json.loads
            key_dict = extract_credentials_manually(raw_key_string)
            
            # Validate extraction
            if "project_id" not in key_dict or "private_key" not in key_dict:
                st.error("❌ Regex Failed: Could not find 'project_id' or 'private_key' in the secrets string.")
                st.stop()
            
            # Authenticate
            self.creds = service_account.Credentials.from_service_account_info(
                key_dict, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            self.project_id = key_dict.get("project_id")
            self.base_url = f"https://firestore.googleapis.com/v1/projects/{self.project_id}/databases/(default)/documents"
            
        except Exception as e:
            st.error(f"🔥 Auth Setup Error: {e}")
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

# Initialize Database
db_http = FirestoreREST(st.secrets)
client = genai.Client(api_key=st.secrets["GEMINI_KEY"])

# --- 4. DATA LOGIC ---
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
        elem = data['rows'][0]['elements'][0]
        return {"sec": elem['duration_in_traffic']['value'], "txt": elem['duration_in_traffic']['text']}
    except: return None

# --- 5. UI ---
if 'flight_info' not in st.session_state:
    st.session_state.flight_info = None

st.title("✈️ Departly.ai")
col1, col2 = st.columns(2)
with col1: f_in = st.text_input("Flight Number", placeholder="e.g. 6E 6433")
with col2: p_in = st.text_input("Pickup Point", placeholder="e.g. Hoodi, Bangalore")

if st.button("Calculate Departure", type="primary", use_container_width=True):
    with st.spinner("Analyzing..."):
        flight = get_flight_data(f_in)
        if flight:
            st.session_state.flight_info = flight
            traffic = get_traffic(p_in, flight['dest_code'])
            if traffic:
                takeoff = parser.parse(flight['dep_time'])
                leave = (takeoff - timedelta(minutes=45)) - timedelta(seconds=traffic['sec'] + 3600)
                st.balloons()
                st.success(f"### 🚪 Leave Home by: **{leave.strftime('%I:%M %p')}**")
                st.info(f"Flight to **{flight['display']}** detected.")
            else:
                st.error("Traffic Error.")
        else:
            st.error("Flight not found.")

if st.session_state.flight_info:
    st.divider()
    targets = st.session_state.flight_info['targets']
    display = st.session_state.flight_info['display']
    
    st.subheader(f"🗺️ Guide for {display}")
    days = st.slider("Days", 1, 7, 3)
    
    if st.button("Generate Verified Itinerary", use_container_width=True):
        with st.spinner(f"Fetching data via HTTP for {targets}..."):
            rag_docs = get_rag_data_http(targets)
            
            with st.expander(f"📚 Data Inspector ({len(rag_docs)} records)"):
                st.write(rag_docs)

            if rag_docs:
                context = "\n".join(rag_docs)
                prompt = f"Create a {days}-day itinerary for {display} using this data:\n{context}"
                res = client.models.generate_content(model='gemini-2.0-flash-exp', contents=prompt)
                st.markdown(res.text)
            else:
                st.warning("No records found via HTTP. Check City Name in CSV.")
