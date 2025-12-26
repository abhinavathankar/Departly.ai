import streamlit as st
import requests
import json
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types
from datetime import datetime, timedelta
from dateutil import parser

# --- 1. SECURE FIREBASE & AI INITIALIZATION ---
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

# --- 2. RAG HELPER FUNCTION ---
def get_itinerary_context(city_name):
    """Retrieves local attraction data from Firestore"""
    # Normalize city name to Title Case (e.g., 'delhi' -> 'Delhi')
    formatted_city = city_name.strip().title()
    
    try:
        # Querying the collection broadly by the 'City' field
        docs = db.collection("itineraries_knowledge_base").where("City", "==", formatted_city).get(timeout=10)
        
        context_data = []
        for doc in docs:
            d = doc.to_dict()
            # Safe data extraction using .get() to handle missing CSV cells
            place_info = (
                f"- {d.get('Name')}: {d.get('Significance')}. "
                f"Fee: {d.get('Entrance Fee in INR')} INR. "
                f"Visit Duration: {d.get('time needed to visit in hrs')} hrs. "
                f"Best Time: {d.get('Best Time to visit')}."
            )
            context_data.append(place_info)
        
        return "\n".join(context_data) if context_data else None
    except Exception as e:
        st.sidebar.error(f"DB Error: {e}")
        return None

# --- 3. API WRAPPERS ---
def get_flight_data(flight_input):
    clean_iata = flight_input.replace(" ", "").upper()
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={st.secrets['AIRLABS_KEY']}"
    try:
        res = requests.get(url).json()
        return res["response"][0] if "response" in res and res["response"] else None
    except: return None

def get_travel_metrics(origin, airport_code):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": origin, 
        "destinations": f"{airport_code} Airport", 
        "mode": "driving", 
        "departure_time": "now", 
        "key": st.secrets["GOOGLE_MAPS_KEY"]
    }
    try:
        data = requests.get(url, params=params).json()
        element = data['rows'][0]['elements'][0]
        return {"seconds": element['duration_in_traffic']['value'], "text": element['duration_in_traffic']['text']}
    except: return None

# --- 4. STREAMLIT UI ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️", layout="centered")

# Use Session State to keep the destination city persistent
if 'dest_city' not in st.session_state:
    st.session_state.dest_city = None

st.title("✈️ Departly.ai")
st.write("Precision Departure Planning + RAG Itineraries.")

col1, col2 = st.columns(2)
with col1:
    flight_input = st.text_input("Flight Number", placeholder="e.g. 6E 2134")
with col2:
    home_input = st.text_input("Pickup Point", placeholder="e.g. Hoodi, Bangalore")

if st.button("Calculate My Safe Departure", use_container_width=True):
    if not home_input or not flight_input:
        st.warning("Please enter all fields.")
    else:
        with st.spinner("Analyzing schedule and live traffic..."):
            flight = get_flight_data(flight_input)
            if flight:
                takeoff_dt = parser.parse(flight['dep_time'])
                boarding_dt = takeoff_dt - timedelta(minutes=45)
                traffic = get_travel_metrics(home_input, flight['dep_iata'])
                
                if traffic:
                    st.session_state.dest_city = flight.get('arr_city', 'your destination')
                    leave_dt = boarding_dt - timedelta(seconds=traffic['seconds'] + (105 * 60))
                    
                    st.balloons()
                    st.success(f"### 🚪 Leave Home by: **{leave_dt.strftime('%I:%M %p')}**")
                    
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Takeoff", takeoff_dt.strftime("%I:%M %p"))
                    m2.metric("Boarding", boarding_dt.strftime("%I:%M %p"))
                    m3.metric("Traffic", traffic['text'])
                else:
                    st.error("Could not calculate traffic route.")
            else:
                st.error("Flight not found.")

# --- 5. THE RAG ITINERARY GENERATOR ---
if st.session_state.dest_city:
    st.divider()
    st.subheader(f"🗺️ Explore {st.session_state.dest_city}")
    
    num_days = st.slider("Select your trip duration (days):", 1, 7, 3)
    
    if st.button(f"Generate {num_days}-Day Itinerary", use_container_width=True):
        with st.spinner(f"Pulling verified data for {st.session_state.dest_city}..."):
            
            # Step 1: RETRIEVAL (The RAG Part)
            rag_context = get_itinerary_context(st.session_state.dest_city)
            
            # Step 2: GENERATION (The AI Part)
            itinerary_prompt = f"""
            You are an elite travel concierge for Departly.ai. 
            City: {st.session_state.dest_city}
            Duration: {num_days} days
            
            USE THIS DATA FROM OUR FIRESTORE DATABASE TO GROUND YOUR RESPONSE:
            {rag_context if rag_context else "No specific database records found. Use general premium knowledge."}
            
            STRICT INSTRUCTIONS:
            - Build a logical daily schedule.
            - Include 'Entrance Fees' and 'Significance' as per the provided database data.
            - Organize the flow using 'Visit Duration' and 'Best Time' fields from the data.
            - Format with bold day headers and professional bullet points.
            """
            
            try:
                response = client.models.generate_content(
                    model='gemini-3-flash-preview',
                    contents=itinerary_prompt
                )
                st.markdown(f"### ✨ Your Custom Itinerary for {st.session_state.dest_city}")
                st.info(response.text)
            except Exception as e:
                st.error("AI failed to generate itinerary. Please try again.")

st.markdown("---")
st.caption("Powered by Firebase Cloud RAG & Gemini 3 Intelligence.")
