import sys
import os
import json
from dotenv import load_dotenv

load_dotenv(".env")

from src.services.supabase_search import search_hotels_with_rooms
from src.services.hotel_selection import rank_hotel_candidates
from src.services.trip_scheduler import PlaceCandidate

def run_test():
    print("Testing Hotel Search & Ranking...")
    query = "khách sạn có hồ bơi và chỗ đỗ xe"
    target_price = None
    amenity_prefs = []
    
    # 1. Search semantic matches
    # Use 2026-07-01 to 2026-07-02 which we know has availability
    hotels = search_hotels_with_rooms(
        query=query,
        match_threshold=0.2,
        match_count=10,
        start_date="2026-07-01",
        end_date="2026-07-02"
    )
    print(f"Found {len(hotels)} semantic matches.")
    
    # 2. Format as required by rank_hotel_candidates
    options = []
    for h in hotels:
        candidate = PlaceCandidate(id=str(h["id"]), name=h["name"], similarity=h["similarity"])
        options.append((h, candidate))
        
    # 3. Rank and score them
    ranked = rank_hotel_candidates(
        options,
        target_price=target_price,
        amenity_prefs=amenity_prefs
    )
    
    # 4. Print the top 5
    for rank, (data, cand) in enumerate(ranked[:5], start=1):
        name = data.get("name")
        price = data.get("lowest_price")
        score = data.get("match_score")
        sim = data.get("similarity")
        reasons = data.get("match_reasons")
        print(f"\nRank {rank}: {name}")
        print(f" - Price: {price}")
        print(f" - Raw Semantic Similarity: {sim:.4f}")
        print(f" - Final MATCH SCORE: {score * 100:.1f}%")
        print(f" - Reasons: {reasons}")

if __name__ == "__main__":
    run_test()
