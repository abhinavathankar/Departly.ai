import streamlit as st
import json
import requests
import google.auth.transport.requests
from google.oauth2 import service_account

st.set_page_config(page_title="REST Bypass", page_icon="🌐")
st.title("🌐 Firebase HTTP Connector")
st.caption("Using standard HTTP to bypass firewall blocking.")

# --- 1. SETUP CREDENTIALS ---
try:
    # Load Key from Secrets
    raw_key = st.secrets["FIREBASE_KEY"]
    key_dict = json.loads(raw_key) if isinstance(raw_key, str) else dict(raw_key)

    # Standard Newline Fix
    if "private_key" in key_dict:
        key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")

    # Generate Auth Token
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

# --- 2. HTTP FETCH FUNCTION ---
def fetch_via_rest():
    # A. Refresh Token
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    token = creds.token
    
    # B. Define URL (Standard Firestore REST Endpoint)
    # URL format: https://firestore.googleapis.com/v1/projects/{id}/databases/(default)/documents/{collection}
    url = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents/itineraries_knowledge_base"
    
    # C. Headers & Params
    headers = {"Authorization": f"Bearer {token}"}
    params = {"pageSize": 3} # Fetch only 3 docs
    
    # D. Send Request (This will TIMEOUT if it fails, it won't hang)
    response = requests.get(url, headers=headers, params=params, timeout=10)
    return response

# --- 3. RUN TEST ---
if st.button("🚀 Fetch Data (HTTP Mode)"):
    with st.spinner("Connecting via HTTP..."):
        try:
            resp = fetch_via_rest()
            
            if resp.status_code == 200:
                data = resp.json()
                st.success("✅ SUCCESS! Connection Established.")
                
                if "documents" in data:
                    docs = data["documents"]
                    st.write(f"Found {len(docs)} documents.")
                    
                    st.divider()
                    st.subheader("🕵️ Data Inspector")
                    
                    # Loop through docs and show cleaned data
                    for doc in docs:
                        # Firestore REST API returns weird structure: {"fields": {"City": {"stringValue": "Delhi"}}}
                        # We clean it here for you:
                        raw_fields = doc["fields"]
                        clean_doc = {}
                        for key, val in raw_fields.items():
                            # Grab the first value inside the type wrapper (stringValue, integerValue, etc.)
                            clean_doc[key] = list(val.values())[0]
                        
                        st.json(clean_doc)
                else:
                    st.warning("Connected successfully, but the collection is empty.")
                    
            else:
                st.error(f"❌ API Error {resp.status_code}")
                st.text(resp.text)
                
        except requests.exceptions.Timeout:
            st.error("❌ Request Timed Out. Check your internet connection.")
        except Exception as e:
            st.error(f"❌ Script Error: {e}")
