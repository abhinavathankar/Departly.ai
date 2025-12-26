import streamlit as st
import json
import time
import firebase_admin
from firebase_admin import credentials, firestore

st.set_page_config(page_title="Firebase Connection Test")
st.title("🔥 Firebase Connection Doctor")

def test_connection():
    # 1. TIMEOUT CHECK START
    start_time = time.time()
    
    try:
        # --- AUTHENTICATION ---
        if not firebase_admin._apps:
            # Load from Streamlit Secrets
            if "FIREBASE_KEY" not in st.secrets:
                st.error("❌ 'FIREBASE_KEY' not found in secrets.toml")
                return

            raw_key = st.secrets["FIREBASE_KEY"]
            
            # Handle String vs Dict format
            key_dict = json.loads(raw_key) if isinstance(raw_key, str) else dict(raw_key)

            # CRITICAL FIX: Repair broken newlines (The #1 cause of hanging)
            if "private_key" in key_dict:
                key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")

            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
            st.write("✅ Authentication Step: Passed")

        # --- DB CONNECTION & FETCH ---
        db = firestore.client()
        
        # Enforce manual timeout logic
        # Note: Firestore 'timeout' param isn't always respected by the grpc layer during auth hangs, 
        # so we check time before and after operations.
        
        st.write("⏳ Pinging database (Limit 1)...")
        
        # Try to fetch 1 document
        docs = db.collection("itineraries_knowledge_base").limit(1).get(timeout=5)
        
        # Check if we exceeded 10s total
        if time.time() - start_time > 10:
             st.error("❌ FAILED: Connection took longer than 10 seconds.")
             return

        # Verify data
        count = 0
        for doc in docs:
            st.success(f"✅ SUCCESS! Connection took {time.time() - start_time:.2f}s")
            with st.expander("View Raw Data Record"):
                st.json(doc.to_dict())
            count += 1
            
        if count == 0:
            st.warning(f"⚠️ Connected in {time.time() - start_time:.2f}s, but found 0 documents. Check Collection Name.")

    except Exception as e:
        st.error(f"❌ CONNECTION FAILED: {e}")

if st.button("Run Diagnostics"):
    test_connection()
