import streamlit as st
import requests
import json
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types
from datetime import datetime, timedelta
from dateutil import parser

# --- 1. INITIALIZATION ---
if not firebase_admin._apps:
    try:
        # Pulls the JSON string from Streamlit Secrets (FIREBASE_KEY)
        key_dict = json.loads(st.secrets["FIREBASE_KEY"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Firebase Init Error: {e}")
        st.stop()

db = firestore.client()
client = genai.Client(api_key=st.secrets["GEMINI_KEY"])

# --- 2. CITY RESOLVER (The Bridge between AirLabs and Firebase) ---
def get_city_name_from_iata(iata_code):
    """
    AirLabs Schedules API only gives codes (DEL). 
    We fetch the actual City name (Delhi) from the Airports API.
    """
    # 1. Local Quick Map (Fallback)
    local_map = {
        "DEL": "Delhi", "BLR": "Bengaluru", "BOM": "Mumbai", "MAA": "Chennai",
        "HYD": "Hyderabad", "CCU": "Kolkata", "GOI": "Goa", "PNQ": "Pune",
        "AMD": "Ahmedabad", "JAI": "Jaipur", "LKO": "Lucknow", "COK": "Kochi",
        "VNS": "Varanasi", "IXC": "Chandigarh", "GAU": "Guwahati"
    }
    if iata_code in local_map:
        return local_map[iata_code]
    
    # 2. Live Lookup via AirLabs Airports API
    url = f"https://airlabs.co/api/v9/airports?iata_code={iata_code}&api_key={st.secrets['AIRLABS_KEY']}"
    try:
        res = requests.get(url).json()
        if "response" in res and res["response"]:
            return res["response"][0].get('city', iata_code)
    except:
        pass
    return iata_code

# --- 3. RAG HELPER FUNCTION ---
def get_itinerary_context(city_name):
    """Retrieves place data from Firestore"""
    # Normalize City Name (e.g. 'New Delhi' -> 'Delhi' if your CSV uses Delhi)
    search_term = city_name.strip().title()
    if search_term == "New Delhi": search_term = "Delhi"
    
    try:
        # Searching the 'City' field (Capital C as per your CSV)
        docs = db.collection("itineraries_knowledge_base").where("City", "==", search_term).get(timeout=10)
        
        context_data = []
        for doc in docs:
            d = doc.to_dict()
            info = f"- {d.get('Name')}: {d.get('Significance')}. Fee: {d.get('Entrance Fee in INR')} INR. Visit: {d.get('time needed to visit in hrs')} hrs."
            context_data.append(info)
        return context_data
    except Exception as e:
        st.sidebar.error(f"DB Error: {e}")
        return []

# --- 4. FLIGHT & TRAFFIC LOGIC ---
def get_flight_data(flight_input):
    clean_iata = flight_input.replace(" ", "").upper()
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={st.secrets['AIRLABS_KEY']}"
    try:
        res = requests.get(url).json()
        if "response" in res and res["response"]:
            f_data = res["response"][0]
            # AirLabs schedules does NOT have city names, only codes.
            iata = f_data.get('arr_iata')
            # Resolve code to city name for Firebase
            f_data['detected_city'] = get_city_name_from_iata(iata)
            return f_data
    except: return None
    return None

def get_travel_metrics(origin, airport_code):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {"origins": origin, "destinations": f"{airport_code} Airport", "mode": "driving", "departure_time": "now", "key": st.secrets["GOOGLE_MAPS_KEY"]}
    try:
        data = requests.get(url, params=params).json()
        element = data['rows'][0]['elements'][0]
        return {"seconds": element['duration_in_traffic']['value'], "text": element['duration_in_traffic']['text']}
    except: return None

# --- 5. STREAMLIT UI ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️", layout="centered")

if 'dest_city' not in st.session_state:
    st.session_state.dest_city = None

st.title("✈️ Departly.ai")
st.write("Precision Flight Planning with RAG-Powered Insights.")

col1, col2 = st.columns(2)
with col1:
    flight_input = st.text_input("Flight Number", placeholder="6E 2134")
with col2:
    home_input = st.text_input("Pickup Point", placeholder="Hoodi, Bengaluru")

if st.button("Calculate My Safe Departure", use_container_width=True):
    with st.spinner("Analyzing schedule and city data..."):
        flight = get_flight_data(flight_input)
        if flight:
            st.session_state.dest_city = flight.get('detected_city', 'Unknown')
            
            takeoff_dt = parser.parse(flight['dep_time'])
            boarding_dt = takeoff_dt - timedelta(minutes=45)
            traffic = get_travel_metrics(home_input, flight['dep_iata'])
            
            if traffic:
                leave_dt = boarding_dt - timedelta(seconds=traffic['seconds'] + (105 * 60))
                st.balloons()
                st.success(f"### 🚪 Leave Home by: **{leave_dt.strftime('%I:%M %p')}**")
                st.write(f"Destination detected as: **{st.session_state.dest_city}**")
            else:
                st.error("Google Maps traffic error.")
        else:
            st.error("Flight not found. Try '6E 2134' or 'AI 803'.")

# --- 6. ITINERARY RAG SECTION ---
if st.session_state.dest_city and st.session_state.dest_city != 'Unknown':
    st.divider()
    st.subheader(f"🗺️ Explore {st.session_state.dest_city}")
    
    days = st.slider("Trip Duration (Days)", 1, 7, 3)
    
    if st.button("Generate RAG Itinerary", use_container_width=True):
        with st.spinner(f"Querying Firebase Knowledge Base for {st.session_state.dest_city}..."):
            # Step 1: RETRIEVAL
            results = get_itinerary_context(st.session_state.dest_city)
            
            # Debug message
            st.caption(f"Found {len(results)} local places for {st.session_state.dest_city} in database.")

            if len(results) > 0:
                # Step 2: GENERATION
                context_str = "\n".join(results)
                prompt = f"""
                You are a luxury travel assistant. 
                Using ONLY this verified data:
                {context_str}
                
                Create a logical {days}-day itinerary for {st.session_state.dest_city}. 
                Mention specific entrance fees and why these places are significant.
                Format with bold headers.
                """
                try:
                    response = client.models.generate_content(
                        model='gemini-3-flash-preview', 
                        contents=prompt
                    )
                    st.info(response.text)
                except Exception as e:
                    st.error(f"AI Error: {e}")
            else:
                st.warning(f"City '{st.session_state.dest_city}' recognized, but no matching places in your Firebase collection. Try 'Delhi'.")

st.markdown("---")
st.caption("Powered by Firebase RAG & Gemini 3")
