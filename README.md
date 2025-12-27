✈️ Departly.ai: Intelligent Flight Logistics & Itinerary Planner

**Link:** https://departlyai.streamlit.app/

Departly.ai is a streamlined travel assistant designed to solve the two biggest pain points of air travel: "Airport Math" anxiety (knowing exactly when to leave) and Destination Planning.
By orchestration real-time flight data, live traffic telemetry, and Generative AI, Departly eliminates the guesswork of travel day logistics. It doesn't just track your flight; it reverse-engineers your schedule to ensure you never miss a boarding call, then seamlessly pivots to planning your trip upon arrival using verified local data.

<img width="1400" height="850" alt="is" src="https://github.com/user-attachments/assets/425cbf26-2e99-4e19-aa4e-06d325a2548d" />

**Core Capabilities**
**Predictive Logistics Engine:** The application ingests live flight manifests via the AirLabs API. It correlates this data with real-time traffic latency from Google Maps. The system utilizes a deterministic algorithm to calculate precise departure windows. This logic optimizes the time-to-gate metric and mitigates travel anxiety.

**RAG-Powered Planning:** We implement a Retrieval-Augmented Generation (RAG) architecture for itinerary creation. The backend queries a structured Firestore knowledge base for verified points of interest. It feeds this context into the Gemini 2.0 Flash model for high-speed inference. This grounded approach eliminates model hallucinations and ensures actionable outputs.

**Automated Signal Processing:** The interface leverages browser-based geolocation signals. It performs immediate reverse geocoding to resolve user origin points. This reduces input friction and streamlines the user journey.

**Technical Stack**
Frontend: Streamlit
Model: Google Gemini 3 Flash
Data Store: Google Firestore (NoSQL)
Telemetry: AirLabs, Google Distance Matrix
Architecture: RESTful API Integration

**Example:**
1. Enter the flight details and your location/give application the permission to access your location. Click on Calculate Journey.
<img width="940" height="487" alt="image" src="https://github.com/user-attachments/assets/a8324a75-3f96-4ec4-abc8-ec9d9979ffc9" />

2. You will get the flight details and suggested time to leave your location. This uses Google Maps API to indentify the time it will take you to travel to the flight origin airport. 
<img width="925" height="691" alt="image" src="https://github.com/user-attachments/assets/78c9de33-e6c9-4f4a-bf46-3feb133e24a3" />

3. Select number of days you are planning to stay, AI will use dedicated must visit places Data base to provide you with the best travel itinerary. 
<img width="967" height="680" alt="image" src="https://github.com/user-attachments/assets/60fab28e-db40-4a87-9bb0-44d518f80238" />
