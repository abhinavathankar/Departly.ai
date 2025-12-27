import streamlit as st
import requests
import json
import time
import google.auth.transport.requests
from google.oauth2 import service_account
import google.generativeai as genai
from datetime import datetime, timedelta
from dateutil import parser
from streamlit_js_eval import get_geolocation

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️", layout="centered")

# --- 2. AUTH & MODEL SETUP ---
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
    genai.configure(api_key=st.secrets["GEMINI_KEY"])
    db_http = FirestoreREST(st.secrets)
except Exception as e:
    st.error(f"Service Init Error: {e}")
    st.stop()

# --- MODEL FALLBACK LOGIC ---
AVAILABLE_MODELS = ['gemini-1.5-flash', 'gemini-2.0-flash-exp']
model = None
current_engine = ""

for model_name in AVAILABLE_MODELS:
    try:
        test_model = genai.GenerativeModel(model_name)
        test_model.count_tokens("Ping")
        model = test_model
        current_engine = model_name
        break
    except Exception:
        continue

if not model:
    model = genai.GenerativeModel('gemini-1.5-flash')
    current_engine = "gemini-1.5-flash (Fallback)"

# --- 3. SESSION STATE ---
if 'flight_info' not in st.session_state: st.session_state.flight_info = None
if 'journey_meta' not in st.session_state: st.session_state.journey_meta = None
if 'itinerary_data' not in st.session_state: st.session_state.itinerary_data = None
if 'pickup_address' not in st.session_state: st.session_state.pickup_address = ""

# --- 4. HELPERS & DATA ---
INDIAN_AIRLINES = {
    "IndiGo": "6E", "Air India": "AI", "Vistara": "UK", 
    "SpiceJet": "SG", "Air India Express": "IX", "Akasa Air": "QP",
    "Alliance Air": "9I", "Star Air": "S5", "Fly91": "IC"
}

# --- EXTENDED CITY VARIANTS MAPPING ---
CITY_VARIANTS = {
    # Metro Hubs & North
    "DEL": ["Delhi", "New Delhi", "Noida", "Gurugram", "Greater Noida", "Meerut", "Mathura", "Vrindavan", "Aligarh", "Faridabad"],
    "AGR": ["Agra", "Fatehpur Sikri", "Mathura", "Vrindavan", "Bharatpur"],
    "LKO": ["Lucknow", "Ayodhya", "Kanpur", "Naimisharanya"],
    "VNS": ["Varanasi", "Sarnath", "Mirzapur", "Prayagraj"],
    "IXD": ["Allahabad", "Prayagraj", "Chitrakoot", "Kaushambi"],
    "ATQ": ["Amritsar", "Dalhousie", "Pathankot", "Gurdaspur"],
    "IXC": ["Chandigarh", "Shimla", "Kasauli", "Solan", "Chail", "Parwanoo"],
    "DED": ["Dehradun", "Mussoorie", "Rishikesh", "Haridwar", "Dhanaulti", "Kanatal", "Tehri"],
    "PGH": ["Pantnagar", "Nainital", "Jim Corbett", "Ranikhet", "Almora", "Bhimtal", "Mukteshwar"],
    
    # Himachal / Mountains (Often accessed via IXC, ATQ or DEL, but if flying to KUU/DHM)
    "KUU": ["Kullu", "Manali", "Manikaran", "Kasol", "Shoja", "Jibhi", "Tirthan Valley", "Spiti Valley", "Keylong"],
    "DHM": ["Dharamshala", "McLeod Ganj", "Palampur", "Bir Billing", "Kangra", "Barot"],
    "SLV": ["Shimla", "Kufri", "Narkanda", "Chail"],
    
    # J&K / Ladakh
    "SXR": ["Srinagar", "Gulmarg", "Pahalgam", "Sonamarg", "Anantnag", "Baramulla"],
    "IXL": ["Leh", "Nubra Valley", "Pangong Tso", "Kargil", "Diskit", "Hemis", "Dras", "Turtuk"],
    "IXJ": ["Jammu", "Katra", "Vaishno Devi", "Udhampur", "Patnitop", "Kishtwar"],

    # West (Maharashtra / Gujarat / Goa)
    "BOM": ["Mumbai", "Lonavala", "Alibaug", "Matheran", "Khandala", "Elephanta Caves", "Igatpuri"],
    "PNQ": ["Pune", "Lonavala", "Mahabaleshwar", "Lavasa", "Panchgani", "Satara", "Matheran"],
    "NAG": ["Nagpur", "Pench", "Tadoba"],
    "IXU": ["Aurangabad", "Ajanta", "Ellora", "Shirdi"],
    "ISK": ["Nashik", "Shirdi", "Trimbakeshwar", "Igatpuri"],
    "SAG": ["Shirdi", "Shani Shingnapur"],
    "KLH": ["Kolhapur", "Panhala"],
    
    "AMD": ["Ahmedabad", "Gandhinagar", "Kevadia", "Statue of Unity", "Modhera", "Patan", "Mount Abu"],
    "STV": ["Surat", "Daman", "Silvassa"],
    "BDQ": ["Vadodara", "Kevadia", "Champaner"],
    "RAJ": ["Rajkot"],
    "JGA": ["Jamnagar", "Dwarka"],
    "PBD": ["Porbandar", "Dwarka", "Somnath"],
    "DIU": ["Diu", "Somnath", "Gir National Park"],
    "BHJ": ["Bhuj", "Rann of Kutch", "Dholavira"],
    "GOI": ["Goa", "Panjim", "Calangute", "Anjuna", "Dudhsagar", "Madgaon"],
    "GOX": ["Goa", "North Goa", "Mopa"],

    # Rajasthan
    "JAI": ["Jaipur", "Pushkar", "Ajmer", "Ranthambore", "Sawai Madhopur", "Alwar", "Bhangarh"],
    "UDR": ["Udaipur", "Chittorgarh", "Kumbhalgarh", "Mount Abu", "Nathdwara"],
    "JDH": ["Jodhpur", "Osian", "Khimsar"],
    "JSA": ["Jaisalmer", "Sam Sand Dunes", "Tanot"],
    "BKB": ["Bikaner", "Deshnoke"],

    # South (Karnataka / Tamil Nadu / Kerala / AP / Telangana)
    "BLR": ["Bengaluru", "Bangalore", "Mysore", "Coorg", "Chikmagalur", "Nandi Hills", "Hassan", "Belur", "Halebidu", "Lepakshi"],
    "IXE": ["Mangalore", "Udupi", "Gokarna", "Murudeshwar", "Bekal", "Coorg", "Dharmasthala"],
    "MYQ": ["Mysore", "Bandipur", "Kabini", "Nagarhole", "Srirangapatna"],
    "HBX": ["Hubli", "Hampi", "Badami", "Pattadakal", "Aihole", "Bijapur", "Dandeli"],
    "MAA": ["Chennai", "Mahabalipuram", "Kanchipuram", "Puducherry", "Auroville", "Tirupati", "Vellore"],
    "CJB": ["Coimbatore", "Ooty", "Coonoor", "Isha Yoga Center", "Pollachi"],
    "IXM": ["Madurai", "Rameswaram", "Kodaikanal", "Karaikudi", "Thanjavur"],
    "TRZ": ["Trichy", "Thanjavur", "Velankanni", "Chidambaram", "Kumbakonam"],
    "TCR": ["Tuticorin", "Tirunelveli", "Kanyakumari"],
    "HYD": ["Hyderabad", "Secunderabad", "Warangal", "Srisailam", "Bidar"],
    "COK": ["Kochi", "Munnar", "Alappuzha", "Thekkady", "Kumarakom", "Thrissur", "Guruvayur"],
    "TRV": ["Thiruvananthapuram", "Kovalam", "Varkala", "Kanyakumari", "Poovar"],
    "CCJ": ["Kozhikode", "Wayanad", "Vythiri", "Kannur"],
    "CNN": ["Kannur", "Bekal", "Coorg"],
    "VTZ": ["Visakhapatnam", "Araku Valley", "Vizianagaram"],
    "VGA": ["Vijayawada", "Amaravati", "Guntur"],
    "TIR": ["Tirupati", "Srikalahasti", "Puttaparthi"],
    "CDP": ["Kadapa", "Gandikota"],
    "KJB": ["Kurnool", "Mantralayam"],

    # East & North East
    "CCU": ["Kolkata", "Sundarbans", "Digha", "Mandarmani", "Bolpur", "Shantiniketan", "Murshidabad", "Mayapur", "Hooghly"],
    "IXB": ["Bagdogra", "Darjeeling", "Gangtok", "Pelling", "Kalimpong", "Siliguri", "Namchi", "Ravangla", "Lachung"],
    "GAU": ["Guwahati", "Shillong", "Kaziranga", "Cherrapunji", "Dawki", "Manas", "Hajo", "Kamakhya"],
    "JRH": ["Jorhat", "Majuli", "Sivasagar", "Kaziranga"],
    "IXA": ["Agartala", "Unakoti", "Dumboor"],
    "IXS": ["Silchar"],
    "IMF": ["Imphal"],
    "DMU": ["Dimapur", "Kohima", "Dzukou Valley"],
    "BBI": ["Bhubaneswar", "Puri", "Konark", "Chilika", "Cuttack", "Udayagiri"],
    "JRG": ["Jharsuguda", "Sambalpur", "Rourkela"],
    "PAT": ["Patna", "Bodh Gaya", "Nalanda", "Rajgir", "Vaishali"],
    "IXR": ["Ranchi", "Deoghar", "Netarhat"],
    "DGR": ["Deoghar", "Baidyanath Dham"],

    # Central India & Islands
    "BHO": ["Bhopal", "Sanchi", "Bhimbetka", "Pachmarhi"],
    "IDR": ["Indore", "Ujjain", "Mandu", "Omkareshwar", "Maheshwar"],
    "JLR": ["Jabalpur", "Kanha", "Bandhavgarh", "Bhedaghat", "Amarkantak"],
    "GWL": ["Gwalior", "Orchha", "Jhansi", "Shivpuri"],
    "HJR": ["Khajuraho", "Panna"],
    "RPR": ["Raipur", "Bastar", "Jagdalpur", "Chitrakoot Falls"],
    "IXZ": ["Port Blair", "Havelock Island", "Neil Island", "Baratang Island", "Ross Island"]
}

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

# --- 5. MAIN UI ---
st.title("✈️ Departly.ai")
st.caption(f"Engine: {current_engine}")

loc_data = get_geolocation(component_key='gps_trigger')
if loc_data and 'coords' in loc_data:
    lat = loc_data['coords']['latitude']
    lng = loc_data['coords']['longitude']
    if not st.session_state.pickup_address:
        st.session_state.pickup_address = reverse_geocode(lat, lng)

col1, col2 = st.columns([1, 1])
with col1:
    airline_name = st.selectbox("Select Airline", list(INDIAN_AIRLINES.keys()))
with col2:
    flight_num = st.text_input("Flight Number", placeholder="e.g. 6433")

p_in = st.text_input("Pickup Point", value=st.session_state.pickup_address, placeholder="e.g. Hoodi, Bangalore")
if p_in != st.session_state.pickup_address: st.session_state.pickup_address = p_in
airline_code = INDIAN_AIRLINES[airline_name]

if st.button("Calculate Journey", type="primary", use_container_width=True):
    if not (flight_num and p_in):
        st.warning("Please enter both details.")
    else:
        full_flight_code = f"{airline_code}{flight_num}"
        with st.spinner(f"Tracking {full_flight_code}..."):
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
                st.session_state.itinerary_data = None
            else:
                st.error("Flight not found.")

if st.session_state.journey_meta:
    j = st.session_state.journey_meta
    st.markdown("---")
    st.subheader("🎫 Flight Dashboard")
    c1, c2 = st.columns(2)
    c1.metric("From", j["dep_iata"])
    c2.metric("To", j["arr_iata"])
    c3, c4 = st.columns(2)
    c3.metric("Takeoff", j["takeoff"])
    c4.metric("Landing", j["landing"])
    st.success(f"### 🚪 Leave Home by: **{j['leave_time']}**")
    with st.expander("⏱️ Journey Breakdown", expanded=False):
        st.write(f"🚗 **Travel to Airport:** {j['traffic_txt']}")
        st.write("🛂 **Security & Baggage:** 30 mins")
        st.write("✈️ **Gate Close:** 45 mins")

# --- 6. ITINERARY SECTION ---
if st.session_state.flight_info:
    st.markdown("---")
    display = st.session_state.flight_info['display']
    st.subheader(f"🗺️ Plan Trip: {display}")
    
    days = st.slider("Trip Duration (Days)", 1, 7, 3)
    
    if st.button("Generate Itinerary", use_container_width=True):
        with st.spinner(f"Designing trip with {current_engine}..."):
            rag_docs = []
            for city in st.session_state.flight_info['targets']:
                try: rag_docs.extend(db_http.query_city(city.strip()))
                except: pass
            
            context = "\n".join([f"• {d.get('Name')} ({d.get('Type')})" for d in rag_docs]) if rag_docs else "No specific database data."
            
            prompt = f"""
            Act as a travel API. Create a {days}-day itinerary for {display}.
            Use these local recommendations if possible: {context}

            Return a strict JSON OBJECT with this structure:
            {{
                "title": "Trip Title",
                "days": [
                    {{
                        "day": 1,
                        "theme": "Theme of day",
                        "activities": ["Activity 1", "Activity 2"]
                    }}
                ]
            }}
            """
            
            try:
                response = model.generate_content(
                    prompt,
                    generation_config={"response_mime_type": "application/json"}
                )
                data = json.loads(response.text)
                st.session_state.itinerary_data = data
            except Exception as e:
                st.error(f"Generation Error: {e}")

if st.session_state.itinerary_data:
    data = st.session_state.itinerary_data
    st.markdown(f"### {data.get('title', 'Your Itinerary')}")
    for day in data.get('days', []):
        with st.expander(f"Day {day['day']}: {day['theme']}", expanded=True):
            for activity in day.get('activities', []):
                st.write(f"• {activity}")
