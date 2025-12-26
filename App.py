import streamlit as st
import json
import firebase_admin
from firebase_admin import credentials, firestore

st.set_page_config(page_title="Schema Inspector")
st.title("🔍 Firebase Schema Inspector")

# --- 1. ROBUST CONNECTION ---
if not firebase_admin._apps:
    try:
        raw_key = st.secrets["FIREBASE_KEY"]
        key_dict = json.loads(raw_key) if isinstance(raw_key, str) else dict(raw_key)
        
        # The mandatory newline fix
        if "private_key" in key_dict:
            key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")
            
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Auth Error: {e}")
        st.stop()

db = firestore.client()

# --- 2. THE BLIND DUMP ---
if st.button("🔴 Fetch First Available Record"):
    st.info("Attempting to pull 1 arbitrary document from 'itineraries_knowledge_base'...")
    
    try:
        # No 'where' clause. Just get the first thing in the DB.
        # This proves if the Collection Name is correct.
        docs = db.collection("itineraries_knowledge_base").limit(1).get()
        
        found = False
        for doc in docs:
            found = True
            st.success(f"✅ Connection Open! Found Document ID: `{doc.id}`")
            
            data = doc.to_dict()
            st.subheader("Raw Data Structure:")
            st.json(data)
            
            # DIAGNOSTIC CHECK
            st.divider()
            st.write("### 🕵️ Field Analysis")
            
            # Check City Field
            if "City" in data:
                st.write(f"✅ 'City' field exists. Value: `'{data['City']}'`")
            elif "city" in data:
                st.warning(f"⚠️ Field is lowercase 'city'. Update your code query to match.")
            else:
                st.error("❌ No 'City' field found! Check the JSON above for the correct name.")

            # Check Name Field (Critical for RAG)
            if "Name" in data:
                st.write(f"✅ 'Name' field exists. Value: `'{data['Name']}'`")
            else:
                st.error("❌ 'Name' field missing! Your RAG code `d.get('Name')` will return None.")

        if not found:
            st.error("❌ Connection successful, but Collection is EMPTY.")
            st.write("Double check: Is the collection name in Firebase definitely `itineraries_knowledge_base`?")

    except Exception as e:
        st.error(f"❌ Read Error: {e}")
