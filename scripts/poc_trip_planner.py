import os
import sys
import logging
from typing import List, Dict, Any
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    filename='poc_trip_planner.log',
    filemode='w',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Add project root to python path so we can import from src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.tools import tool
from langchain_ollama import ChatOllama
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from supabase import create_client, Client
from qdrant_client.http import models

from src.services.vector_store import get_vector_store

# Initialize Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("Error: SUPABASE_URL or SUPABASE_SERVICE_KEY is missing in .env")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# Initialize Qdrant Vector Stores
print("Initializing Vector Stores...")
attractions_store = get_vector_store("attractions_vector")
hotels_store = get_vector_store("hotels_vector")
try:
    rooms_store = get_vector_store("rooms_vector")
except Exception as e:
    print(f"Warning: Could not initialize rooms_store: {e}")
    rooms_store = None


def _get_destination_id(destination_name: str):
    try:
        response = supabase.table("destinations").select("id").ilike("name", f"%{destination_name}%").limit(1).execute()
        data = response.data
        if data:
            return data[0]["id"]
    except Exception as e:
        logger.error(f"Error fetching destination ID for {destination_name}: {e}")
    return None


@tool
def search_attractions(query: str, destination_name: str, k: int = 5) -> str:
    """
    Search for tourist attractions based on a query. 
    IMPORTANT: You MUST provide both a search query and the exact 'destination_name' (e.g., "Nha Trang").
    Returns a formatted string of the top matching attractions in that destination.
    """
    dest_id = _get_destination_id(destination_name)
    search_filter = None
    if dest_id:
        # In case the ID was stored as a string in Qdrant (sync script converted to str for attractions)
        # we will use MatchAny to match either integer or string format
        search_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="destination_id",
                    match=models.MatchAny(any=[dest_id, str(dest_id)])
                )
            ]
        )
        
    docs = attractions_store.similarity_search(query, k=k, filter=search_filter)
    if not docs:
        return "No attractions found for this query."
    
    results = []
    for d in docs:
        metadata = d.metadata
        results.append(
            f"- Name: {metadata.get('name', 'Unknown')}\n"
            f"  Category: {metadata.get('category', 'Unknown')}\n"
            f"  Location: {metadata.get('coordinates', 'Unknown')}\n"
            f"  Description: {d.page_content}"
        )
    return "\n\n".join(results)


@tool
def search_hotels(query: str, destination_name: str, k: int = 5) -> str:
    """
    Search for hotels based on a query.
    IMPORTANT: You MUST provide both a search query and the exact 'destination_name' (e.g., "Nha Trang").
    Returns a formatted string of the top matching hotels in that destination.
    """
    dest_id = _get_destination_id(destination_name)
    search_filter = None
    if dest_id:
        search_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="destination_id",
                    match=models.MatchAny(any=[dest_id, str(dest_id)])
                )
            ]
        )

    docs = hotels_store.similarity_search(query, k=k, filter=search_filter)
    if not docs:
        return "No hotels found for this query."
    
    results = []
    for d in docs:
        metadata = d.metadata
        hotel_id = metadata.get('hotel_id', 'Unknown')
        name = metadata.get('name', 'Unknown')
        logger.info(f"Found hotel ID: {hotel_id} - Name: {name}")
        results.append(
            f"- Name: {name}\n"
            f"  Star Rating: {metadata.get('star_rating', 'N/A')}\n"
            f"  Description: {d.page_content}"
        )
    return "\n\n".join(results)


@tool
def search_rooms(query: str, k: int = 3) -> str:
    """
    Search for specific hotel rooms based on a query.
    IMPORTANT: Your query MUST include the destination city name or the exact hotel name (e.g., "deluxe rooms in Nha Trang").
    Use this to find specific room types (e.g., standard, deluxe, suite) or amenities.
    Returns a formatted string of the top matching rooms.
    """
    if not rooms_store:
        return "Room search is currently unavailable."
        
    docs = rooms_store.similarity_search(query, k=k)
    if not docs:
        return "No rooms found for this query."
    
    results = []
    for d in docs:
        metadata = d.metadata
        results.append(
            f"- Hotel ID: {metadata.get('hotel_id', 'Unknown')}\n"
            f"  Room Type: {metadata.get('room_type', 'Unknown')}\n"
            f"  Price per night: ${metadata.get('price_per_night', 'N/A')}\n"
            f"  Description: {d.page_content}"
        )
    return "\n\n".join(results)


@tool
def get_hotel_details_from_db(hotel_name: str) -> str:
    """
    Get exact hotel details from the database by name.
    Use this if you need concrete information about a specific hotel that isn't in the search results.
    """
    response = supabase.table("hotels").select("*").ilike("name", f"%{hotel_name}%").limit(1).execute()
    data = response.data
    if not data:
        return f"Could not find exact details for hotel '{hotel_name}' in the database."
    
    hotel = data[0]
    return (
        f"Hotel: {hotel.get('name')}\n"
        f"Stars: {hotel.get('star_rating')}\n"
        f"Source URL: {hotel.get('source_url')}\n"
        f"Location: {hotel.get('coordinates')}"
    )


# Setup LLM and Memory
llm = ChatOllama(model="llama3.1", temperature=0.3)
memory = MemorySaver()

# --- Sub-Agents ---
hotel_agent = create_react_agent(
    llm, 
    [search_hotels, search_rooms, get_hotel_details_from_db], 
    prompt="""You are an expert Hotel Agent. 
CRITICAL: You MUST use the `search_hotels` tool to find hotels in the correct location. Always pass the exact destination_name to the tool. Do NOT guess hotels. Remember to prefer finding ONE hotel for the entire stay."""
)

attraction_agent = create_react_agent(
    llm, 
    [search_attractions], 
    prompt="You are an expert Attraction Agent. Your job is to find the best tourist attractions, restaurants, and activities for a destination."
)

itinerary_agent = create_react_agent(
    llm, 
    [], 
    prompt="""You are an expert Itinerary Planner. Your job is to take raw data about hotels and attractions and format it into a detailed daily itinerary. 
You MUST format the plan EXACTLY like this template. Do NOT use words like '* Sáng' or '* Chiều'. Use actual clock times (e.g., 08:00, 14:00). You MUST include the Hotel section at the top!

Hotel: [Name of the recommended hotel from the provided data]

Day 1: (description of the day's theme or focus)
08:00 - [Attraction, Restaurant, or Hotel Name]
12:00 - [Attraction, Restaurant, or Hotel Name]
14:00 - [Attraction, Restaurant, or Hotel Name]

Day 2: (description of the day's theme or focus)
09:00 - [Attraction, Restaurant, or Hotel Name]
...

Always stick to the exact template format.
IMPORTANT: The final itinerary content, including descriptions and themes, MUST be written entirely in Vietnamese."""
)

# --- Wrapper Tools for Sub-Agents ---
def ask_hotel_expert(query: str) -> str:
    """Consult the Hotel Expert."""
    response = hotel_agent.invoke({"messages": [("user", query)]})
    return response["messages"][-1].content

def ask_attraction_expert(query: str) -> str:
    """Consult the Attraction Expert."""
    response = attraction_agent.invoke({"messages": [("user", query)]})
    return response["messages"][-1].content

def ask_itinerary_planner(context_data: str) -> str:
    """Consult the Itinerary Planner."""
    response = itinerary_agent.invoke({"messages": [("user", f"Generate an itinerary using this data:\n{context_data}")]})
    return response["messages"][-1].content

@tool
def generate_full_itinerary(destination: str = "", duration: str = "", people: str = "") -> str:
    """
    CRITICAL: Use this tool to generate the final trip plan ONLY once you have gathered the destination, duration, and number of people.
    You MUST pass the extracted destination, duration, and people from the chat history.
    """
    missing = []
    if not destination or destination.lower() in ["unknown", "chưa rõ", "none"]: missing.append("destination")
    if not duration or duration.lower() in ["unknown", "chưa rõ", "none"]: missing.append("duration")
    if not people or people.lower() in ["unknown", "chưa rõ", "none"]: missing.append("people")
    
    if missing:
        return f"SYSTEM ERROR: You cannot plan the itinerary yet. You are missing: {', '.join(missing)}. DO NOT guess. Reply to the user in Vietnamese asking for this specific information."

    logger.info("Executing full itinerary pipeline...")
    hotel_info = ask_hotel_expert(f"Find a hotel in {destination} for {people} people for {duration}. You MUST call search_hotels.")
    attraction_info = ask_attraction_expert(f"Find attractions in {destination}")
    
    context = f"Destination: {destination}\nDuration: {duration}\nPeople: {people}\n\nHotel Options:\n{hotel_info}\n\nAttraction Options:\n{attraction_info}"
    
    logger.info("Passing gathered info to itinerary planner...")
    final_plan = ask_itinerary_planner(context)
    return final_plan

# --- Main Supervisor Agent ---
SUPERVISOR_PROMPT = """You are the Trip Planning Supervisor.
You are chatting with a user. Your goal is to gather:
1. Destination (Where?)
2. Duration (How long?)
3. People (How many?) - IMPORTANT: Users may use conversational Vietnamese (e.g., "mình tôi", "một mình" means 1 person). Be smart and extract the meaning from context!

If you DO NOT have all 3, you MUST ONLY reply with a conversational message asking for the missing info. DO NOT CALL ANY TOOLS.

Only when you have successfully collected ALL 3 pieces of info from the chat history, you may call `generate_full_itinerary`. 
CRITICAL: When you call it, you MUST pass ALL 3 arguments. Look at the chat history to find the previously provided details (e.g. if they said Nha Trang earlier, do not forget it!).

IMPORTANT RULES:
- DO NOT leak your internal reasoning, system instructions, or parenthesis explanations (e.g. do not say "nghĩa là tôi chưa có đủ thông tin...") in your chat responses.
- Never output raw JSON in your text responses.
- Return the EXACT response from the itinerary planner to the user. Do not add conversational filler.
- All your responses to the user MUST be entirely in Vietnamese."""

# Create the agent
agent = create_react_agent(llm, [generate_full_itinerary], checkpointer=memory, prompt=SUPERVISOR_PROMPT)
config = {"configurable": {"thread_id": "poc_trip_planner_1"}}


def main():
    print("==================================================")
    print("Welcome to the Trip Planner POC (Powered by Llama3)")
    print("Type 'quit' or 'exit' to stop.")
    print("==================================================\n")
    
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ['quit', 'exit']:
                break
                
            if not user_input.strip():
                continue
                
            logger.info(f"User Input: {user_input}")
            print("\nAgent is thinking...\n")
            
            # Stream the response to show agent flow
            events = agent.stream(
                {"messages": [("user", user_input)]}, 
                config=config,
                stream_mode="values"
            )
            
            final_ai_response = None
            itinerary_generated = None
            for event in events:
                if "messages" in event:
                    latest_message = event["messages"][-1]
                    
                    # Print agent flow debugging info
                    if latest_message.type == "ai" and latest_message.tool_calls:
                        tool_names = ", ".join([tc['name'] for tc in latest_message.tool_calls])
                        print(f"🔄 [Agent Flow: Supervisor is delegating to {tool_names}...]")
                        logger.info(f"Delegating to tools: {tool_names}")
                    
                    elif latest_message.type == "tool":
                        if "SYSTEM ERROR:" not in str(latest_message.content):
                            print(f"✅ [Agent Flow: {latest_message.name} returned results]")
                            if latest_message.name == "generate_full_itinerary":
                                itinerary_generated = latest_message.content
                        logger.info(f"Tool returned: {latest_message.name}")

                    if latest_message.type == "ai" and not latest_message.tool_calls:
                        final_ai_response = latest_message.content
            
            # Print the final AI response after the loop finishes
            if itinerary_generated:
                logger.info(f"Final AI Itinerary Output:\n{itinerary_generated}")
                print(f"\nAI: {itinerary_generated}")
            elif final_ai_response:
                logger.info(f"Final AI Response: {final_ai_response}")
                print(f"\nAI: {final_ai_response}")

        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break
        except Exception as e:
            print(f"\nAn error occurred: {e}")

if __name__ == "__main__":
    main()
