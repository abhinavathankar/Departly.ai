import streamlit as st
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from google.genai import types
from datetime import datetime, timedelta
from dateutil import parser

# --- 1. INITIALIZATION ---
# Initialize Firebase with the Service Account Key
if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

# Initialize Gemini AI Client using Streamlit Secrets
client = genai.Client(api_key=st.secrets["GEMINI_KEY"])

# --- 2. RAG HELPER FUNCTION ---
def get_itinerary_context(city_name):
    """Retrieves place data from Firestore with error handling and case normalization"""
    # Force Title Case to match CSV format (e.g., 'delhi' -> 'Delhi')
    formatted_city = city_name.strip().title()
    
    try:
        # Query the collection broadly by City
        # Added a timeout to prevent the UI from 'circling' indefinitely
        docs = db.collection("itineraries_knowledge_base").where("City", "==", formatted_city).get(timeout=10)
        
        context_data = []
        for doc in docs:
            d = doc.to_dict()
            # Use .get() to handle missing fields in specific CSV rows safely
            name = d.get('Name', 'Unknown Attraction')
            sig = d.get('Significance', 'Cultural site')
            fee = d.get('Entrance Fee in INR', 'Check locally')
            time_req = d.get('time needed to visit in hrs', '2')
            best_time = d.get('Best Time to visit', 'Morning/Evening')
            
            context_data.append(
                f"- {name}: {sig}. Fee: {fee} INR. Duration: {time_req} hrs. Best time: {best_time}."
            )
        
        return "\n".join(context_data) if context_data else None
    except Exception as e:
        st.error(f"Database Fetch Error: {e}")
        return None

# --- 3. API WRAPPERS ---
def get_flight_data(flight_input):
    """Fetches flight details and cleans carrier codes"""
    clean_iata = flight_input.replace(" ", "").upper()
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={st.secrets['AIRLABS_KEY']}"
    try:
        res = requests.get(url).json()
        return res["response"][0] if "response" in res and res["response"] else None
    except: return None

def get_travel_metrics(origin, airport_code):
    """Fetches driving metrics from Google Maps Distance Matrix"""
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

# --- 4. UI SETUP ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️", layout="centered")

# Initialize Session State to persist the destination after the first button click
if 'dest_city' not in st.session_state:
    st.session_state.dest_city = None

st.title("✈️ Departly.ai")
st.write("Precision Departure Planning with RAG-Powered Itineraries.")

col1, col2 = st.columns(2)
with col1:
    flight_input = st.text_input("Flight Number", placeholder="e.g. 6E 2134")
with col2:
    home_input = st.text_input("Pickup Point", placeholder="e.g. Hoodi, Bangalore")

if st.button("Calculate My Safe Departure", use_container_width=True):
    if not home_input or not flight_input:
        st.warning("Please enter both flight and pickup location.")
    else:
        with st.spinner("Analyzing schedule and traffic..."):
            flight = get_flight_data(flight_input)
            if flight:
                takeoff_dt = parser.parse(flight['dep_time'])
                boarding_dt = takeoff_dt - timedelta(minutes=45)
                traffic = get_travel_metrics(home_input, flight['dep_iata'])
                
                if traffic:
                    # Save destination to session state so 'Generate Itinerary' button can access it
                    st.session_state.dest_city = flight.get('arr_city', 'Destination')
                    leave_dt = boarding_dt - timedelta(seconds=traffic['seconds'] + (105 * 60))
                    
                    st.success(f"### 🚪 Leave Home by: **{leave_dt.strftime('%I:%M %p')}**")
                    
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Takeoff", takeoff_dt.strftime("%I:%M %p"))
                    m2.metric("Boarding", boarding_dt.strftime("%I:%M %p"))
                    m3.metric("Traffic", traffic['text'])
                else:
                    st.error("Google Maps could not find your location.")
            else:
                st.error("Flight not found.")

# --- 5. RAG ITINERARY GENERATOR ---
if st.session_state.dest_city:
    st.divider()
    st.subheader(f"🗺️ Plan Your {st.session_state.dest_city} Visit")
    
    # Input for number of days
    num_days = st.slider("Number of days staying?", 1, 7, 3)
    
    if st.button(f"Generate {num_days}-Day Itinerary", use_container_width=True):
        with st.spinner(f"Retrieving RAG context from Firestore..."):
            
            # Step 1: Retrieval (Fetch from Firestore)
            rag_context = get_itinerary_context(st.session_state.dest_city)
            
            # Step 2: Augmentation and Generation
            prompt = f"""
            You are a luxury travel concierge for Departly.ai.
            Target City: {st.session_state.dest_city}
            Duration: {num_days} days
            
            DATABASE RECORDS (Use this for planning):
            {rag_context if rag_context else "No specific database records found. Use general knowledge."}
            
            TASK:
            1. Create a logical day-by-day itinerary.
            2. Incorporate 'Significance' and 'Entrance Fees' from the database records.
            3. Optimize timings based on 'time needed to visit' for each attraction.
            4. If no database records exist, provide a premium itinerary based on general facts.
            Format with bold headers and professional bullet points.
            """
            
            try:
                response = client.models.generate_content(
                    model='gemini-3-flash-preview',
                    contents=prompt
                )
                st.markdown(f"### ✨ Your {num_days}-Day Itinerary")
                st.info(response.text)
            except Exception as e:
                st.error(f"AI Generation Error: {e}")

st.markdown("---")
st.caption("Powered by Firebase Firestore RAG & Gemini 3")
