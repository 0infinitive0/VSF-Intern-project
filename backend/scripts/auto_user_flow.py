import sys
import time
import concurrent.futures
from fastapi.testclient import TestClient
from src.main import app

def request_with_timeout(client, method, path, payload=None, timeout=60.0):
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        if method.upper() == 'POST':
            future = executor.submit(client.post, path, json=payload)
        else:
            future = executor.submit(client.get, path)
            
        try:
            resp = future.result(timeout=timeout)
            elapsed = time.time() - start
            return resp, elapsed
        except concurrent.futures.TimeoutError:
            print(f"\n[ERROR] Request to {path} timed out after {timeout} seconds!")
            sys.exit(1)
        except Exception as e:
            print(f"\n[ERROR] Request to {path} failed: {e}")
            sys.exit(1)

def print_response(resp, elapsed):
    print(f"Response (took {elapsed:.2f}s) [Status: {resp.status_code}]:")
    try:
        data = resp.json()
        print(f"  Stage: {data.get('stage')}")
        print(f"  Reply: {data.get('reply')}")
        hotel_options = data.get("hotel_options", [])
        if hotel_options:
            print(f"  Hotel Options ({len(hotel_options)}):")
            for h in hotel_options[:3]:
                print(f"    - {h.get('name')} ({h.get('price_per_night', 'N/A')} VND)")
            if len(hotel_options) > 3:
                print("    - ...")
        return data
    except Exception as e:
        print(f"  Failed to parse JSON: {resp.text}")
        return None

def run_flow():
    client = TestClient(app)
    
    # 1. Create Session
    print("\n=== 1. Creating Session ===")
    resp, elapsed = request_with_timeout(client, 'POST', "/api/v1/chat/session", timeout=10.0)
    if resp.status_code != 200:
        print("Failed to create session")
        sys.exit(1)
    session_id = resp.json()["session_id"]
    print(f"Session created: {session_id} (took {elapsed:.2f}s)")
    
    # 2. First message
    print("\n=== 2. Sending Initial Message ===")
    print("User: 'tôi muốn đi chơi hcm'")
    payload = {"session_id": session_id, "message": "tôi muốn đi chơi hcm"}
    resp, elapsed = request_with_timeout(client, 'POST', "/api/v1/chat", payload, timeout=120.0)
    data = print_response(resp, elapsed)
    assert data.get("stage") == "intake", f"Expected stage 'intake', got {data.get('stage')}"
    
    # 3. Fulfill Missing Info (Text)
    print("\n=== 3a. Providing Missing Info (Text) ===")
    print("User: 'tôi đi 2 người'")
    payload = {
        "session_id": session_id, 
        "message": "tôi đi 2 người",
    }
    resp, elapsed = request_with_timeout(client, 'POST', "/api/v1/chat", payload, timeout=120.0)
    data = print_response(resp, elapsed)

    # 3b. Fulfill Missing Info (Dates from DatePicker)
    print("\n=== 3b. Providing Missing Info (Dates) ===")
    print("User changes UI datepicker")
    payload = {
        "session_id": session_id,
        "stay_dates": {"start_date": "2026-07-01", "end_date": "2026-07-03"}
    }
    resp, elapsed = request_with_timeout(client, 'POST', "/api/v1/chat", payload, timeout=120.0)
    data = print_response(resp, elapsed)
    
    # 4. Add Budget Preferences (Simulating Frontend)
    print("\n=== 4. Adding Budget Preferences (Simulate Frontend) ===")
    print("User changes UI filters: min=500000, max=2000000 (no chat message)")
    payload = {"session_id": session_id, "min_price": 500000, "max_price": 2000000}
    resp, elapsed = request_with_timeout(client, 'POST', "/api/v1/chat", payload, timeout=120.0)
    data = print_response(resp, elapsed)
    assert data.get("stage") == "hotel_options", f"Expected stage 'hotel_options', got {data.get('stage')}"
    
    # 5. Refine Preferences with Message
    print("\n=== 5. Refining Preferences ===")
    print("User: 'tìm khách sạn khác gần trung tâm hơn'")
    payload = {"session_id": session_id, "message": "tìm khách sạn khác gần trung tâm hơn"}
    resp, elapsed = request_with_timeout(client, 'POST', "/api/v1/chat", payload, timeout=120.0)
    data = print_response(resp, elapsed)
    assert data.get("stage") == "hotel_options", f"Expected stage 'hotel_options', got {data.get('stage')}"
    
    # 6. Remove Preferences
    print("\n=== 6. Removing Preferences ===")
    print("User: 'bỏ yêu cầu gần trung tâm đi'")
    payload = {"session_id": session_id, "message": "bỏ yêu cầu gần trung tâm đi"}
    resp, elapsed = request_with_timeout(client, 'POST', "/api/v1/chat", payload, timeout=120.0)
    data = print_response(resp, elapsed)
    assert data.get("stage") == "hotel_options", f"Expected stage 'hotel_options', got {data.get('stage')}"

    # 7. Multi-intention testing
    print("\n=== 7. Multi-intention Testing ===")
    print("User: 'khách sạn 1 có wifi không, nếu không tìm khách sạn khác cho tôi'")
    payload = {"session_id": session_id, "message": "khách sạn 1 có wifi không, nếu không tìm khách sạn khác cho tôi"}
    resp, elapsed = request_with_timeout(client, 'POST', "/api/v1/chat", payload, timeout=120.0)
    data = print_response(resp, elapsed)
    assert data.get("stage") == "hotel_options", f"Expected stage 'hotel_options', got {data.get('stage')}"

    print("\n=== Flow completed successfully! ===")

if __name__ == "__main__":
    run_flow()
