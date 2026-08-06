import sys
import json
import asyncio
sys.path.insert(0, "/app")
from src.services.trip_intake import _llm_extract_intake_facts, DestinationOption

async def main():
    msg = (
        "Khách sạn số 2 có cho huỷ phòng miễn phí trước 24h không em? Nếu có thì chọn luôn khách sạn số 2 cho anh. "
        "Tiện thể bỏ cái lọc bể bơi đi nhé vì con anh bị ốm không bơi được nữa, thay bằng spa với phòng gym. "
        "Với lại lọc lại giúp anh chỗ nào thật yên tĩnh để cày deadline, tránh xa mấy khu nhộn nhạo, "
        "ngân sách đẩy lên tối đa 2.5 triệu/đêm cho 3 người lớn đi cuối tuần sau từ 15/10/2026 đến 18/10/2026 nhé."
    )
    known = {
        "destination": "Hồ Chí Minh",
        "duration": "2 ngày",
        "start_date": "2026-07-01",
        "people": "2 người"
    }
    destinations = [
        DestinationOption("Hồ Chí Minh", ("HCM", "Sài Gòn"))
    ]
    res = _llm_extract_intake_facts(msg, known, destinations)
    print(json.dumps(res, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
