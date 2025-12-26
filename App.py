import streamlit as st
import requests
import json
import google.auth.transport.requests
from google.oauth2 import service_account
from google import genai
from datetime import datetime, timedelta
from dateutil import parser

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Departly Debugger", page_icon="🐞", layout="centered")

st.title("🐞 Departly Debug Mode")
st.write("This mode prints every step to find the hidden error.")

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

# Initialize
try:
    db_http = FirestoreREST(st.secrets)
    client = genai.Client(api_key=st.secrets["GEMINI_KEY"])
except Exception as e:
    st.error(f"Startup Error: {e}")

AVAILABLE_MODELS = ['gemini-2.0-flash-exp', 'gemini-1.5-flash', 'gemini-1.5-pro']
CITY_VARIANTS = {"DEL": ["Delhi"], "BLR": ["Bangalore"], "BOM": ["Mumbai"]}

# --- 3. DEBUGGED FLIGHT FUNCTION ---
def get_flight_data_debug(flight_input):
    clean_iata = flight_input.replace(" ", "").upper()
    api_key = st.secrets.get('AIRLABS_KEY', '')
    
    st.write(f"🔹 **Step 1:** Searching API for `{clean_iata}`...")
    
    if not api_key:
        st.error("❌ CRITICAL: 'AIRLABS_KEY' is missing from secrets.toml")
        return None

    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={api_key}"
    
    try:
        res = requests.get(url, timeout=10)
        st.write(f"🔹 **Step 2:** API Status Code: `{res.status_code}`")
        
        try:
            res_json = res.json()
        except:
            st.error("❌ API returned non-JSON response.")
            st.text(res.text)
            return None

        # SHOW RAW RESPONSE IMMEDIATELY
        with st.expander("🔍 Click to see RAW API Response", expanded=True):
            st.json(res_json)

        if "error" in res_json:
            st.error(f"❌ API Error Message: {res_json['error'].get('message')}")
            return None

        if "response" in res_json and res_json["response"]:
            f_data = res_json["response"][0]
            st.success("✅ **Step 3:** Flight Data Found!")
            
            # Map Data
            code = f_data.get('arr_iata') or f_data.get('arr_icao')
            f_data['dest_code'] = code
            
            if code in CITY_VARIANTS:
                f_data['targets'] = CITY_VARIANTS[code]
                f_data['display'] = CITY_VARIANTS[code][0]
            else:
                city_api = f_data.get('arr_city', 'Unknown')
                f_data['targets'] = [city_api]
                f_data['display'] = city_api
            
            return f_data
        else:
            st.warning("⚠️ **Step 3 Failed:** API returned success (200) but the 'response' list is empty. This means AirLabs has no data for this flight number today.")
            return None

    except Exception as e:
        st.error(f"❌ Connection Exception: {e}")
        return None

def get_traffic(origin, dest_code):
    # Simplified for debug
    return {"sec": 5400, "txt": "1h 30m (Debug Default)"}

# --- 4. UI ---
col1, col2 = st.columns(2)
with col1: f_in = st.text_input("Flight Number", value="6E 6433")
with col2: p_in = st.text_input("Pickup Point", value="Hoodi, Bangalore")

if st.button("Run Debug Trace", type="primary"):
    st.divider()
    
    # 1. GET FLIGHT
    flight = get_flight_data_debug(f_in)
    
    # 2. CHECK RESULT
    if flight:
        st.divider()
        st.header("🎫 FLIGHT DASHBOARD")
        
        # BLUE BOXES
        c1, c2, c3, c4 = st.columns(4)
        c1.info(f"**Flight:** {flight.get('flight_iata')}")
        c2.info(f"**Departs:** {flight.get('dep_time')}")
        c3.info(f"**Arrives:** {flight.get('arr_time')}")
        c4.info(f"**Dest:** {flight.get('dest_code')}")
        
        # 3. GET ITINERARY DATA
        st.divider()
        st.write(f"🔹 **Step 4:** Querying Database for {flight['targets']}...")
        docs = get_rag_data_http(flight['targets'])
        
        if docs:
            st.success(f"✅ **Step 5:** Found {len(docs)} documents.")
            st.write(docs)
        else:
            st.warning("⚠️ **Step 5:** Database returned 0 documents.")
            
    else:
        st.error("🛑 STOP: Could not proceed because Flight Data was None.")
