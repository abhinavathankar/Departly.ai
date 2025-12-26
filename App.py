import streamlit as st
import requests
import json
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types
from datetime import datetime, timedelta
from dateutil import parser

# --- 1. CONFIGURATION & SETUP ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️", layout="centered")

# Initialize Firebase
if not firebase_admin._apps:
    try:
        key_dict = json.loads(st.secrets["FIREBASE_KEY"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🔥 Firebase Init Error: {e}")
        st.stop()

db = firestore.client()
client = genai.Client(api_key=st.secrets["GEMINI_KEY"])

# --- 2. THE "GROUND TRUTH" DATA ---
# This dictionary maps IATA codes to ALL possible names in your CSV
# This prevents "Unknown" errors for 99% of Indian flights.
IATA_SMART_MAP = {
    "DEL": ["Delhi", "New Delhi"],
    "BLR": ["Bangalore", "Bengaluru"],
    "BOM": ["Mumbai"],
    "MAA": ["Chennai"],
    "CCU": ["Kolkata"],
    "HYD": ["Hyderabad"],
    "GOI": ["Goa"],
    "AMD": ["Ahmedabad"],
    "PNQ": ["Pune"],
    "JAI": ["Jaipur"],
    "LKO": ["Lucknow"],
    "COK": ["Kochi", "Cochin"],
    "VNS": ["Varanasi"],
    "TRV": ["Thiruvananthapuram", "Trivandrum"],
    "ATQ": ["Amritsar"],
    "IXC": ["Chandigarh"],
    "IXL": ["Leh"],
    "SXR": ["Srinagar"],
    "GAU": ["Guwahati"],
    "BBI": ["Bhubaneswar"],
    "VTZ": ["Visakhapatnam"],
    "NAG": ["Nagpur"],
    "IDR": ["Indore"],
    "PAT": ["Patna"],
    "IXZ": ["Port Blair"],
    "DED": ["Dehradun"],
    "UDR": ["Udaipur"],
    "JDH": ["Jodhpur"],
    "IXB": ["Darjeeling", "Siliguri"], # Bagdogra
    "JGA": ["Jamnagar"],
    "HJR": ["Khajuraho"]
}

# Complete list of cities from your CSV for the manual fallback
ALL_CSV_CITIES = sorted([
    'Agra', 'Ahmedabad', 'Ajmer', 'Alappuzha', 'Alibaug', 'Allahabad', 'Almora', 'Amritsar', 
    'Andaman', 'Aurangabad', 'Ayodhya', 'Badrinath', 'Bangalore', 'Barot', 'Bengaluru', 'Bhopal', 
    'Bhubaneswar', 'Bikaner', 'Chandigarh', 'Chennai', 'Chikmagalur', 'Coorg', 'Dalhousie', 
    'Darjeeling', 'Dehradun', 'Delhi', 'Dharamshala', 'Dwarka', 'Gangtok', 'Goa', 'Gokarna', 
    'Gulmarg', 'Gurgaon', 'Guwahati', 'Gwalior', 'Hampi', 'Haridwar', 'Hyderabad', 'Indore', 
    'Jabalpur', 'Jaipur', 'Jaisalmer', 'Jammu', 'Jhansi', 'Jodhpur', 'Kanyakumari', 'Kasol', 
    'Kedarnath', 'Khajuraho', 'Kochi', 'Kodaikanal', 'Kolkata', 'Kovalam', 'Kullu', 'Leh', 
    'Lonavala', 'Lucknow', 'Ludhiana', 'Madurai', 'Mahabalipuram', 'Manali', 'Mangalore', 
    'Mathura', 'McLeod Ganj', 'Mount Abu', 'Mumbai', 'Munnar', 'Mussoorie', 'Mysore', 'Nainital', 
    'Nashik', 'New Delhi', 'Ooty', 'Pahalgam', 'Patna', 'Pondicherry', 'Port Blair', 'Pune', 
    'Puri', 'Pushkar', 'Raipur', 'Rameswaram', 'Ranchi', 'Rishikesh', 'Shillong', 'Shimla', 
    'Shirdi', 'Somnath', 'Spiti Valley', 'Srinagar', 'Surat', 'Thanjavur', 'Thiruvananthapuram', 
    'Tirupati', 'Udaipur', 'Ujjain', 'Vadodara', 'Varanasi', 'Varkala', 'Vijayawada', 
    'Visakhapatnam', 'Vrindavan', 'Wayanad'
])

# --- 3. INTELLIGENT FUNCTIONS ---

def get_flight_data_robust(flight_input):
    """
    Fetches flight data and strictly enforces a City match.
    """
    clean_iata = flight_input.replace(" ", "").upper()
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={st.secrets['AIRLABS_KEY']}"
    
    try:
        res = requests.get(url).json()
        if "response" in res and res["response"]:
            f_data = res["response"][0]
            
            # 1. Get Destination Airport Code
            dest_code = f_data.get('arr_iata') or f_data.get('arr_icao')
            f_data['dest_code'] = dest_code
            
            # 2. Try Smart Map First
            if dest_code in IATA_SMART_MAP:
                f_data['target_cities'] = IATA_SMART_MAP[dest_code]
                f_data['display_city'] = IATA_SMART_MAP[dest_code][0]
                return f_data
            
            # 3. Fallback: Try AirLabs City Name
            try:
                # If code is not in our smart map, ask API
                air_url = f"https://airlabs.co/api/v9/airports?iata_code={dest_code}&api_key={st.secrets['AIRLABS_KEY']}"
                air_res = requests.get(air_url).json()
                if "response" in air_res:
                    api_city = air_res["response"][0].get('city')
                    if api_city:
                        f_data['target_cities'] = [api_city]
                        f_data['display_city'] = api_city
                        return f_data
            except:
                pass
            
            # 4. Total Failure: Return Unknown
            f_data['target_cities'] = []
            f_data['display_city'] = "Unknown"
            return f_data
            
    except Exception as e:
        st.error(f"API Error: {e}")
    return None

def get_rag_context(target_cities_list):
    """
    Queries Firestore for ANY of the target cities (e.g. Delhi OR New Delhi).
    """
    if not target_cities_list:
        return []
    
    all_context = []
    
    # Firestore 'IN' query handles multiple variations (limit 10)
    try:
        # We query for rows where 'City' is in our list of synonyms
        # e.g. City IN ['Delhi', 'New Delhi']
        docs = db.collection("itineraries_knowledge_base").where("City", "in", target_cities_list).get()
        
        for doc in docs:
            d = doc.to_dict()
            if d.get('Name'):
                info = (f"• {d.get('Name')} ({d.get('Type')}): {d.get('Significance')}. "
                        f"Entry: {d.get('Entrance Fee in INR')} INR. "
                        f"Time: {d.get('time needed to visit in hrs')}h. "
                        f"Rating: {d.get('Google review rating')}/5")
                all_context.append(info)
                
    except Exception as e:
        st.error(f"RAG Error: {e}")
        
    return all_context

def get_traffic_metrics(origin, dest_code):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": origin, 
        "destinations": f"{dest_code} Airport", 
        "mode": "driving", 
        "departure_time": "now", 
        "key": st.secrets["GOOGLE_MAPS_KEY"]
    }
    try:
        data = requests.get(url, params=params).json()
        elem = data['rows'][0]['elements'][0]
        return {"sec": elem['duration_in_traffic']['value'], "txt": elem['duration_in_traffic']['text']}
    except: return None

# --- 4. UI LOGIC ---

# Initialize Session State
if 'flight_data' not in st.session_state:
    st.session_state.flight_data = None
if 'manual_city' not in st.session_state:
    st.session_state.manual_city = None

st.title("✈️ Departly.ai")
st.write("Precision Flight Planning + Database-Grounded Itineraries")

col1, col2 = st.columns(2)
with col1:
    f_num = st.text_input("Flight Number", placeholder="e.g. 6E 2134")
with col2:
    pickup = st.text_input("Pickup Point", placeholder="e.g. Hoodi, Bangalore")

if st.button("Calculate Departure", use_container_width=True):
    with st.spinner("Connecting to Aviation Network..."):
        # 1. Fetch Flight
        raw_flight = get_flight_data_robust(f_num)
        
        if raw_flight:
            st.session_state.flight_data = raw_flight
            st.session_state.manual_city = None # Reset manual override
            
            # 2. Calc Traffic
            traffic = get_traffic_metrics(pickup, raw_flight['dep_iata'])
            
            if traffic:
                # 3. Calc Times
                takeoff = parser.parse(raw_flight['dep_time'])
                leave_by = (takeoff - timedelta(minutes=45)) - timedelta(seconds=traffic['sec'] + (105 * 60))
                
                # 4. Display Result
                st.balloons()
                st.success(f"### 🚪 Leave Home by: **{leave_by.strftime('%I:%M %p')}**")
                
                # Flight Info Bar
                st.info(f"Flight **{raw_flight['flight_iata']}** | "
                        f"Departs: **{raw_flight['dep_iata']}** | "
                        f"Arrives: **{raw_flight['dest_code']}** ({raw_flight['display_city']})")
                
                # Metrics
                m1, m2, m3 = st.columns(3)
                m1.metric("Takeoff", takeoff.strftime("%H:%M"))
                m2.metric("Traffic", traffic['txt'])
                m3.metric("Buffer", "1hr 45m")
            else:
                st.error("Could not calculate traffic from your pickup point.")
        else:
            st.error("Flight not found.")

# --- 5. THE FAIL-SAFE ITINERARY SECTION ---
if st.session_state.flight_data:
    st.divider()
    
    # DETERMINE THE TARGET CITY
    # Logic: If API returned "Unknown", use Manual Override. Else use API data.
    active_city_list = st.session_state.flight_data['target_cities']
    display_name = st.session_state.flight_data['display_city']
    
    st.subheader("🗺️ Destination Intelligence")

    # >>> THE MANUAL OVERRIDE (KILL SWITCH) <<<
    # If the system failed to detect a city, OR if the user wants to change it.
    if display_name == "Unknown":
        st.warning("⚠️ We couldn't automatically match this airport to our database.")
        selected_manual = st.selectbox("Please select your destination city:", ALL_CSV_CITIES)
        # Update logic to use manual selection
        active_city_list = [selected_manual]
        display_name = selected_manual
    else:
        # Even if we found it, give option to correct it if wrong
        with st.expander(f"Planning for **{display_name}**. Change City?"):
            selected_manual = st.selectbox("Override City:", ALL_CSV_CITIES, index=ALL_CSV_CITIES.index(display_name) if display_name in ALL_CSV_CITIES else 0)
            if selected_manual != display_name:
                active_city_list = [selected_manual]
                display_name = selected_manual

    # GENERATE BUTTON
    days = st.slider("Trip Duration", 1, 7, 3)
    
    if st.button(f"Generate Plan for {display_name}", type="primary"):
        with st.spinner("Querying Firebase Knowledge Base..."):
            
            # 1. RAG LOOKUP
            rag_results = get_rag_context(active_city_list)
            
            # Debug Stats
            st.caption(f"✓ Found {len(rag_results)} verified places in database for {active_city_list}")
            
            # 2. AI GENERATION
            if rag_results:
                context_blob = "\n".join(rag_results)
                prompt = f"""
                Act as a luxury travel planner.
                Destination: {display_name}
                Duration: {days} Days
                
                STRICTLY USE THIS DATABASE DATA FOR RECOMMENDATIONS:
                {context_blob}
                
                INSTRUCTIONS:
                - Create a day-by-day itinerary.
                - You MUST mention the 'Entry Fee' and 'Rating' for every place you list.
                - Group nearby places together based on your general knowledge of the city.
                """
                res = client.models.generate_content(model='gemini-3-flash-preview', contents=prompt)
                st.markdown(res.text)
            else:
                st.error(f"Sorry, our database has no records for {display_name}. Try selecting a major city from the dropdown above.")

st.markdown("---")
st.caption("Powered by Firebase RAG & Gemini 3")
