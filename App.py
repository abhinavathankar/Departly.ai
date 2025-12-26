import streamlit as st
import requests
import json
import firebase_admin
from firebase_admin import credentials, firestore
from google import genai
from datetime import datetime, timedelta
from dateutil import parser

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Departly.ai", page_icon="✈️", layout="centered")

# --- 2. FIREBASE CONNECTION (With Cache) ---
@st.cache_resource
def get_db():
    """Initializes Firebase only once per session."""
    if not firebase_admin._apps:
        try:
            raw_key = st.secrets["FIREBASE_KEY"]
            key_dict = json.loads(raw_key) if isinstance(raw_key, str) else dict(raw_key)
            
            # The safety fix for newlines
            if "private_key" in key_dict:
                key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
            
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
        except Exception as e:
            st.error(f"🔥 Auth Error: {e}")
            st.stop()
    return firestore.client()

db = get_db()
client = genai.Client(api_key=st.secrets["GEMINI_KEY"])

# --- 3. DATA FUNCTIONS (With Caching) ---

# CACHING THIS FUNCTION STOPS THE "LOOP OF DEATH"
@st.cache_data(ttl=3600) 
def fetch_rag_data(city_names):
    """Queries Firestore and caches the result for 1 hour."""
    all_docs = []
    logs = []
    
    # Use the DB client from the outer scope
    db_client = firestore.client()
    
    for city in city_names:
        clean_city = city.strip()
        logs.append(f"Querying: {clean_city}")
        try:
            # stream() is efficient for larger reads
            docs = db_client.collection("itineraries_knowledge_base").where("City", "==", clean_city).stream()
            
            count = 0
            for doc in docs:
                d = doc.to_dict()
                if d.get('Name'):
                    # Format data tightly for the LLM
                    entry = (f"• {d.get('Name')} | {d.get('Type')} | "
                             f"Fee: {d.get('Entrance Fee in INR')} INR | "
                             f"Time: {d.get('time needed to visit in hrs')}h")
                    all_docs.append(entry)
                    count += 1
            logs.append(f"  -> Found {count} items")
        except Exception as e:
            logs.append(f"  -> Error: {e}")
            
    return all_docs, logs

def get_flight_data(flight_input):
    clean_iata = flight_input.replace(" ", "").upper()
    url = f"https://airlabs.co/api/v9/schedules?flight_iata={clean_iata}&api_key={st.secrets['AIRLABS_KEY']}"
    try:
        res = requests.get(url).json()
        if "response" in res and res["response"]:
            f_data = res["response"][0]
            code = f_data.get('arr_iata') or f_data.get('arr_icao')
            f_data['dest_code'] = code
            return f_data
    except: pass
    return None

def resolve_city_targets(code):
    """Maps IATA Code to City Synonyms"""
    CITY_VARIANTS = {
        "DEL": ["Delhi", "New Delhi"],
        "BLR": ["Bengaluru", "Bangalore"],
        "BOM": ["Mumbai"],
        "MAA": ["Chennai"],
        "CCU": ["Kolkata"],
        "HYD": ["Hyderabad"],
        "GOI": ["Goa"],
        "AMD": ["Ahmedabad"],
        "PNQ": ["Pune"],
        "JAI": ["Jaipur"],
        "COK": ["Kochi", "Cochin"],
        "IXC": ["Chandigarh"],
        "ATQ": ["Amritsar"],
        "IXB": ["Darjeeling", "Siliguri"]
    }
    return CITY_VARIANTS.get(code, ["Unknown"])

# --- 4. UI LOGIC ---

if 'flight_info' not in st.session_state:
    st.session_state.flight_info = None

st.title("✈️ Departly.ai")
st.write("Precision Planning with Persistent Data.")

col1, col2 = st.columns(2)
with col1: f_in = st.text_input("Flight Number", placeholder="e.g. 6E 6433")
with col2: p_in = st.text_input("Pickup Point", placeholder="e.g. Hoodi, Bangalore")

if st.button("Calculate Departure", type="primary", use_container_width=True):
    with st.spinner("Processing..."):
        flight = get_flight_data(f_in)
        if flight:
            # Save to session state immediately
            st.session_state.flight_info = flight
            
            # Simple Time Calc
            takeoff = parser.parse(flight['dep_time'])
            st.success(f"Flight Confirmed: **{flight['dest_code']}**")
        else:
            st.error("Flight not found.")

# --- 5. RAG SECTION (PERSISTENT) ---
if st.session_state.flight_info:
    st.divider()
    
    code = st.session_state.flight_info['dest_code']
    targets = resolve_city_targets(code)
    display_city = targets[0]
    
    st.subheader(f"🗺️ Guide for {display_city}")
    
    # Manual Fallback
    if display_city == "Unknown":
        st.warning("City not auto-detected.")
        display_city = st.selectbox("Select City:", ["Delhi", "Mumbai", "Bangalore", "Goa", "Jaipur"])
        targets = [display_city]

    if st.button("Load Itinerary Data"):
        with st.spinner(f"Reading Database for {targets}..."):
            
            # CALL THE CACHED FUNCTION
            docs, logs = fetch_rag_data(targets)
            
            # INSPECT THE DATA
            with st.expander("🔍 Click to see Verified Database Data", expanded=True):
                st.write(f"**Status:** Found {len(docs)} attractions.")
                st.write("Logs:", logs)
                if docs:
                    st.json(docs[:5]) # Show first 5 items
                else:
                    st.error("0 Records found. The query worked, but the collection has no matching city name.")

            # GENERATE AI
            if docs:
                context = "\n".join(docs)
                prompt = f"Create a 3-day itinerary for {display_city} using only this data:\n{context}"
                res = client.models.generate_content(model='gemini-2.0-flash-exp', contents=prompt)
                st.markdown("### ✨ AI Itinerary")
                st.markdown(res.text)
