import re
import os

for filename in ["backend/src/agents/tools/query_hotel.py", "backend/src/agents/tools/query_hotel_rooms.py"]:
    with open(filename, "r") as f:
        content = f.read()
    
    # Replace TripState with TravelGraphState
    content = content.replace("from src.agents.state import TripState", "from src.agents.graph.state import TravelGraphState")
    content = content.replace("runtime: ToolRuntime[None, TripState]", "runtime: ToolRuntime[None, TravelGraphState]")
    content = content.replace("pending_hotel_selection", "hotel_options")
    
    with open(filename, "w") as f:
        f.write(content)

