import streamlit as st
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types
from datetime import datetime, timedelta
from dateutil import parser

# --- 1. INITIALIZATION (FIREBASE & AI) ---
if not firebase_admin._apps:
    # Ensure serviceAccountKey.json is in your project directory
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

client = genai.Client(api_key=st.secrets["GEMINI_KEY"])

# --- 2. RAG HELPER FUNCTION ---
def get_itinerary_context(city_name):
    """Retrieves local place data from Firestore to act as RAG context"""
    # Query your uploaded collection
    docs = db.collection("itineraries_knowledge_base").where("City", "==", city_name.title()).stream()
    
    context_data = []
    for doc in docs:
        d = doc.to_dict()
        # Formatting specific fields into a readable string for the AI
        place_info = (
            f"- {d['Name']} ({d['Type']}): {d['Significance']}. "
            f"Entry Fee: {d['Entrance Fee in INR']} INR. "
            f"Time needed: {d['time needed to visit in hrs']} hours. "
            f"Best time: {d['Best Time to visit']}."
        )
        context_data.append(place_info)
    
    return "\n".join(context_data) if context_data else "No specific database records found for this city."

# --- 3. FLIGHT & TRAFFIC FUNCTIONS ---
def get_flight_data(flight_input):
    clean_iata = flight_input.replace(" ", "").upper()
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={st.secrets['AIRLABS_KEY']}"
    try:
        response = requests.get(url).json()
        if "response" in response and response["response"]:
            return response["response"][0]
    except: return None

def get_travel_metrics(origin, airport_code):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {"origins": origin, "destinations": f"{airport_code} Airport", "mode": "driving", "departure_time": "now", "key": st.secrets["GOOGLE_MAPS_KEY"]}
    try:
        data = requests.get(url, params=params).json()
        if data['status'] == 'OK' and data['rows'][0]['elements'][0]['status'] == 'OK':
            element = data['rows'][0]['elements'][0]
            return {"seconds": element['duration_in_traffic']['value'], "text": element['duration_in_traffic']['text']}
    except: return None

# --- 4. STREAMLIT UI ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️", layout="centered")
st.title("✈️ Departly.ai")
st.write("Precision travel planning + RAG-Powered Itineraries.")

# State management
if 'dest_city' not in st.session_state:
    st.session_state.dest_city = None

col1, col2 = st.columns(2)
with col1:
    flight_input = st.text_input("Flight Number", placeholder="e.g. 6E 6021")
with col2:
    home_input = st.text_input("Pickup Point", placeholder="e.g. Hoodi, Bangalore")

if st.button("Calculate My Safe Departure", use_container_width=True):
    if not home_input or not flight_input:
        st.warning("Please enter both fields.")
    else:
        with st.spinner("Processing flight and traffic data..."):
            flight = get_flight_data(flight_input)
            if flight:
                takeoff_dt = parser.parse(flight['dep_time'])
                boarding_dt = takeoff_dt - timedelta(minutes=45)
                traffic = get_travel_metrics(home_input, flight['dep_iata'])
                
                if traffic:
                    st.session_state.dest_city = flight.get('arr_city', 'your destination')
                    leave_dt = boarding_dt - timedelta(seconds=traffic['seconds'] + (105 * 60))
                    
                    st.success(f"### 🚪 Leave Home by: **{leave_dt.strftime('%I:%M %p')}**")
                    
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Takeoff", takeoff_dt.strftime("%I:%M %p"))
                    m2.metric("Boarding", boarding_dt.strftime("%I:%M %p"))
                    m3.metric("Traffic", traffic['text'])
                else:
                    st.error("Traffic data unavailable.")
            else:
                st.error("Flight not found.")

# --- 5. RAG ITINERARY GENERATION SECTION ---
if st.session_state.dest_city:
    st.divider()
    st.subheader(f"🗺️ Plan Your Visit to {st.session_state.dest_city}")
    
    # User selects number of days
    days = st.slider("How many days are you staying?", 1, 7, 3)
    
    if st.button(f"Generate {days}-Day Itinerary", use_container_width=True):
        with st.spinner(f"Retrieving local data for {st.session_state.dest_city}..."):
            
            # 1. RETRIEVAL: Pull context from Firebase
            rag_context = get_itinerary_context(st.session_state.dest_city)
            
            # 2. GENERATION: Feed RAG context to Gemini
            itinerary_prompt = f"""
            You are a luxury travel concierge. 
            Destination: {st.session_state.dest_city}
            Duration: {days} days
            
            USE THIS VERIFIED DATA FROM OUR DATABASE TO BUILD THE PLAN:
            {rag_context}
            
            INSTRUCTIONS:
            - Create a day-by-day itinerary.
            - Include 'Significance' and 'Entrance Fees' mentioned in the data.
            - Optimize the route based on the 'time needed to visit' for each place.
            - If the database context is limited, use your own knowledge to fill gaps, but prioritize the provided data.
            """
            
            try:
                response = client.models.generate_content(
                    model='gemini-3-flash-preview',
                    contents=itinerary_prompt
                )
                st.markdown(f"### ✨ {days}-Day Itinerary for {st.session_state.dest_city}")
                st.info(response.text)
            except Exception as e:
                st.error("AI Generation failed. Please try again.")

st.markdown("---")
st.caption("2025 Departly.ai | Powered by Firebase Firestore & Gemini 3")
