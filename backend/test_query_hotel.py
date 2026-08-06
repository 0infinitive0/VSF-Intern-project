import sys
import os
import uuid
import asyncio

# Setup path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.agents.session import process_chat_turn, create_chat_session

def main():
    session_id = f"test_{uuid.uuid4()}"
    session = create_chat_session(session_id)
    
    # 1. Setup basic trip state and trigger recommend_hotels
    input_text = "Đi Đà Nẵng 3 ngày 2 người"
    print(f"\nUser: {input_text}")
    res = process_chat_turn(session, input_text)
    print(f"Assistant: {res.text}")
    
    input_text = "ngân sách 2 triệu 1 đêm"
    print(f"\nUser: {input_text}")
    res = process_chat_turn(session, input_text)
    print(f"Assistant: {res.text}")
    
    input_text = "từ 15/10 đến 18/10"
    print(f"\nUser: {input_text}")
    res = process_chat_turn(session, input_text)
    print(f"Assistant: {res.text}")
    
    # This should trigger recommend_hotels and we'll see the hotel list
    
    print("\n--- Testing query_hotel tool ---")
    input_text = "Khách sạn số 2 có hồ bơi không em?"
    print(f"\nUser: {input_text}")
    res = process_chat_turn(session, input_text)
    print(f"Assistant: {res.text}")
    
    print("\n--- Testing history compaction ---")
    # Simulate a bunch of messages to trigger compaction
    for i in range(2):
        input_text = "tuyệt vời, cảm ơn em. có thể cho anh biết thêm về khách sạn số 2 không?"
        print(f"\nUser: {input_text}")
        res = process_chat_turn(session, input_text)
        print(f"Assistant: {res.text}")

if __name__ == "__main__":
    main()
