import streamlit as st
import json
import time
import firebase_admin
from firebase_admin import credentials, firestore
import threading
import queue

st.set_page_config(page_title="Hard Timeout Test")
st.title("🔥 10-Second Connection Test")

# Global queue to get results from the thread
result_queue = queue.Queue()

def attempt_connection():
    """Attempts to connect and puts the result in a queue."""
    try:
        # 1. SETUP AUTH
        if not firebase_admin._apps:
            raw_key = st.secrets["FIREBASE_KEY"]
            key_dict = json.loads(raw_key) if isinstance(raw_key, str) else dict(raw_key)
            
            # THE FIX: We apply it here to see if it works
            if "private_key" in key_dict:
                key_dict["private_key"] = key_dict["private_key"].replace("\\n", "\n")

            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)

        # 2. PERFORM REQUEST
        db = firestore.client()
        # Try to get 1 document
        docs = db.collection("itineraries_knowledge_base").limit(1).get()
        
        # If we reach here, it worked
        count = sum(1 for _ in docs)
        result_queue.put({"status": "success", "count": count})
        
    except Exception as e:
        result_queue.put({"status": "error", "message": str(e)})

if st.button("Start Test"):
    progress = st.progress(0)
    status = st.empty()
    status.write("⏳ Starting background thread...")
    
    # Run Firebase in a separate thread so it doesn't freeze the UI
    t = threading.Thread(target=attempt_connection)
    t.start()
    
    # Wait for 10 seconds max
    for i in range(10):
        time.sleep(1)
        progress.progress((i + 1) * 10)
        status.write(f"⏳ Connecting... ({i+1}/10s)")
        
        # Check if done
        if not t.is_alive():
            break
    
    # Analyze Result
    if t.is_alive():
        status.error("❌ CRITICAL FAILURE: Connection Hard-Locked (Timeout > 10s)")
        st.error("""
        **Diagnosis:** The app froze while verifying credentials.
        **Cause:** Your Private Key format in `secrets.toml` is definitely broken (newlines are escaping to `\\n`).
        **Solution:** You MUST use the `.replace('\\n', '\\n')` fix in your main code.
        """)
    else:
        # Thread finished, check result
        if not result_queue.empty():
            res = result_queue.get()
            if res["status"] == "success":
                status.success(f"✅ SUCCESS! Found {res['count']} docs.")
                st.write("The connection works nicely when the newlines are fixed.")
            else:
                status.error(f"❌ Connection Error: {res['message']}")
