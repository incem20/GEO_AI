AfetRota: GeoAI Agent for Risk-Aware Evacuation

AfetRota is a sophisticated routing agent designed to provide the safest possible evacuation
paths to assembly points in Istanbul following a major seismic event. Unlike standard navigation
tools that prioritize the shortest path, AfetRota dynamically evaluates seismic risk data to steer
users away from high-vulnerability zones and potential debris bottlenecks.

Key Features
1. Risk-Aware Dijkstra Algorithm: Custom implementation that weights road segments based on environmental risk scores (structural vulnerability, road width, and slope).
2. Live Network Processing: Leverages OSMnx to download and build real-time graph models of the Istanbul street network.
3. Seismic Scenario Integration: Pre-processed IBB M7.5 Nighttime scenario data used to identify "Avoidance Zones."
4. Intelligent Agent Logic: Powered by LangGraph to handle geocoding, shelter finding and risk assessment tasks autonomously.
️ 
Installation
To set up the environment, run the following command to install all necessary Python libraries:
python -m pip install python-dotenv requests shapely folium networkx osmnx scikit-learn langchain langgraph

Environment Setup
Create a .env file in the root directory. Based on the current project requirements, your file should look like this:
USE_LIVE_OSM=true
LLM_MODEL=claude-sonnet-4-6

Dataset & Supported Districts
Due to the current availability of live IBB scenario data and the high computational cost of city-wide risk mapping, the current demo is optimized for the following districts:

Ataköy
Yeşilköy
Bakırköy
Fatih
Küçükçekmece
Bağcılar
Bahçelievler
Maltepe

Other districts will also give a result by downloading the live maps from OSMnx, however risk-mapping is non-existent there because the IBB live dataset is currently unavailable.