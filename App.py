import streamlit as st
import json
import requests
import google.auth.transport.requests
from google.oauth2 import service_account

st.set_page_config(page_title="REST API Bypass")
st.title("🌐 Firestore via HTTP (No-Hang Mode)")

# --- 1. SETUP CREDENTIALS ---
try:
    # Load Key
    raw_key = st.secrets["FIREBASE_KEY"]
    key_dict = json.loads(raw_key) if isinstance(raw_key, str) else dict(raw_key)

    # Fix Newlines (Standard safety)
    if "private_key" in key_dict:
        key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")

    # Create Credentials Object
    creds = service_account.Credentials.from_service_account_info(
        key_dict,
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    
    # Get Project ID
    project_id = key_dict.get("project_id")
    st.write(f"**Target Project:** `{project_id}`")

except Exception as e:
    st.error(f"Key Error: {e}")
    st.stop()

# --- 2. HTTP REQUEST FUNCTION ---
def fetch_via_rest():
    st.info("Step 1: Authenticating via HTTP...")
    
    # Refresh Auth Token
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    token = creds.token
    
    st.info("Step 2: Sending GET Request to Firestore API...")
    
    # REST Endpoint
    # format: https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/{collection_id}
    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/itineraries_knowledge_base"
    
    # Add limit
    params = {"pageSize": 3} 
    headers = {"Authorization": f"Bearer {token}"}
    
    # The Actual Request
    response = requests.get(url, headers=headers, params=params, timeout=10)
    
    return response

# --- 3. RUN TEST ---
if st.button("🚀 Fetch Data via HTTP"):
    try:
        resp = fetch_via_rest()
        
        if resp.status_code == 200:
            data = resp.json()
            st.success("✅ SUCCESS! Connection Established via HTTP.")
            
            if "documents" in data:
                docs = data["documents"]
                st.write(f"Found {len(docs)} documents:")
                
                # Parse the weird Firestore JSON format
                # Firestore REST returns data like: {"fields": {"Name": {"stringValue": "Delhi"}}}
                for doc in docs:
                    raw_fields = doc["fields"]
                    # Quick cleaner
                    clean_doc = {k: list(v.values())[0] for k, v in raw_fields.items()}
                    st.json(clean_doc)
            else:
                st.warning("Connected, but collection is empty (0 documents).")
                st.json(data)
                
        else:
            st.error(f"❌ API Error {resp.status_code}")
            st.text(resp.text)
            
    except requests.exceptions.Timeout:
        st.error("❌ HTTP Request Timed Out. Your internet might be down.")
    except Exception as e:
        st.error(f"❌ Script Error: {e}")
