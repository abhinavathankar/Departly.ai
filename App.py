import streamlit as st
import json
import time
import firebase_admin
from firebase_admin import credentials, firestore

st.set_page_config(page_title="Firebase Speed Test", layout="centered")

st.title("🔥 Firestore Connection Doctor")

# --- 1. KEY REPAIR FUNCTION (The Fix) ---
def get_db_client():
    # Check if app is already initialized to avoid "App already exists" error
    if not firebase_admin._apps:
        try:
            # Load the raw secret string
            raw_key = st.secrets["FIREBASE_KEY"]
            
            # Parse it into a dict
            if isinstance(raw_key, str):
                key_dict = json.loads(raw_key)
            else:
                key_dict = dict(raw_key)
            
            # CRITICAL FIX: Replace literal "\\n" with actual newlines "\n"
            # This is the #1 cause of "hanging" connections in Streamlit
            if "private_key" in key_dict:
                key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")

            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
            st.success("✅ Auth Credentials Formatted & Initialized")
        except Exception as e:
            st.error(f"❌ Auth Failed: {e}")
            return None
            
    return firestore.client()

# --- 2. SPEED TEST ---
if st.button("Test Connection Speed"):
    db = get_db_client()
    
    if db:
        st.write("---")
        status_text = st.empty()
        status_text.info("⏳ Pinging Firestore...")
        
        start_time = time.time()
        
        try:
            # Try to fetch JUST 1 document to test latency
            # Using limit(1) makes it instant regardless of DB size
            docs = db.collection("itineraries_knowledge_base").limit(1).get()
            
            end_time = time.time()
            duration = end_time - start_time
            
            count = 0
            for doc in docs:
                st.json(doc.to_dict()) # Show the raw data proof
                count += 1
            
            status_text.empty()
            if count > 0:
                st.success(f"⚡ FAST! Connection successful in {duration:.2f} seconds.")
                st.write("Your database is accessible. The previous issue was likely the Private Key formatting.")
            else:
                st.warning(f"Connected in {duration:.2f}s, but collection is empty.")
                
        except Exception as e:
            st.error(f"❌ Connection Timed Out or Failed: {e}")
