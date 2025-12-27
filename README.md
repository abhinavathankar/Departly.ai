✈️ Departly.ai: Intelligent Flight Logistics & Itinerary Planner

**Link:** https://departlyai.streamlit.app/

Departly.ai is a streamlined travel assistant designed to solve the two biggest pain points of air travel: "Airport Math" anxiety (knowing exactly when to leave) and Destination Planning.
By orchestration real-time flight data, live traffic telemetry, and Generative AI, Departly eliminates the guesswork of travel day logistics. It doesn't just track your flight; it reverse-engineers your schedule to ensure you never miss a boarding call, then seamlessly pivots to planning your trip upon arrival using verified local data.

<img width="1400" height="850" alt="is" src="https://github.com/user-attachments/assets/425cbf26-2e99-4e19-aa4e-06d325a2548d" />

**Core Capabilities**
**Predictive Logistics Engine****:** The application ingests live flight manifests via the AirLabs API. It correlates this data with real-time traffic latency from Google Maps. The system utilizes a deterministic algorithm to calculate precise departure windows. This logic optimizes the time-to-gate metric and mitigates travel anxiety.

**RAG-Powered Planning****:** We implement a Retrieval-Augmented Generation (RAG) architecture for itinerary creation. The backend queries a structured Firestore knowledge base for verified points of interest. It feeds this context into the Gemini 2.0 Flash model for high-speed inference. This grounded approach eliminates model hallucinations and ensures actionable outputs.

**Automated Signal Processing****:** The interface leverages browser-based geolocation signals. It performs immediate reverse geocoding to resolve user origin points. This reduces input friction and streamlines the user journey.

**Technical Stack**
Frontend: Streamlit
Model: Google Gemini 3 Flash
Data Store: Google Firestore (NoSQL)
Telemetry: AirLabs, Google Distance Matrix
Architecture: RESTful API Integration
