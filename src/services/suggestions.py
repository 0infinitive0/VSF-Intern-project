"""Service for generating contextual follow-up next-chat suggestions for AI turns."""

from __future__ import annotations

import json
import logging
from typing import Any, List

from src.services.llm import get_llm

logger = logging.getLogger(__name__)


def generate_next_chat_suggestions(
    context_text: str = "",
    last_action: str = "general",
    limit: int = 3,
) -> List[str]:
    """Generate contextual follow-up prompt suggestions for the user's next chat turn.

    Args:
        context_text: Summary or text response of the current turn.
        last_action: Identifier of the action ('recommend_hotels', 'hotel_selected', 'itinerary_generated', 'finalized').
        limit: Maximum number of suggestions to return.

    Returns:
        List of suggested follow-up prompts string in Vietnamese.
    """
    action_lower = last_action.lower()

    if "hotel_recommend" in action_lower or "pending_hotel" in action_lower:
        return [
            "Chọn khách sạn số 1 và lập lịch trình",
            "Tìm thêm khách sạn gần biển hơn",
            "Lọc khách sạn có bể bơi và bao gồm ăn sáng",
        ][:limit]

    if "finalized" in action_lower or "finalize" in action_lower:
        return [
            "Tóm tắt chi phí và lưu ý chuyến đi",
            "Gợi ý danh sách đồ cần chuẩn bị",
            "Tạo một chuyến đi mới",
        ][:limit]

    prompt = f"""Dựa trên phản hồi lịch trình chuyến đi dưới đây, hãy đưa ra {limit} gợi ý câu hỏi/yêu cầu tiếp theo ngắn gọn, tự nhiên mà người dùng có thể muốn hỏi AI.

Phản hồi hiện tại:
{context_text[:800]}

Yêu cầu:
- Trả về đúng JSON mảng chuỗi tiếng Việt: ["gợi ý 1", "gợi ý 2", "gợi ý 3"]
- Không giải thích, không kèm markdown code block khác ngoài JSON mảng.
- Mỗi gợi ý dưới 12 từ."""

    try:
        llm = get_llm(temperature=0.7)
        from langchain_core.messages import HumanMessage

        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(content)
        if isinstance(data, list) and all(isinstance(item, str) for item in data):
            cleaned = [str(item).strip() for item in data if str(item).strip()]
            if cleaned:
                return cleaned[:limit]
    except Exception as exc:
        logger.warning("Could not generate LLM next chat suggestions: %s", exc)

    return [
        "Thêm điểm tham quan lịch sử/văn hóa vào lịch trình",
        "Thay đổi khách sạn hoặc vị trí lưu trú",
        "Hoàn tất và chốt lịch trình chuyến đi",
    ][:limit]
