"""Grounded next-chat suggestion chips for the end of a turn.

Every chip comes from an LLM call grounded in THIS turn's real data (worker
action, hotel cards actually shown, amenity labels actually on those cards,
active filters, trip length, language) -- there is no static/hardcoded list
anywhere in this file. A chip that names a filter value or an amenity must
trace back to something the caller actually put in `SuggestionContext`; the
prompt says so explicitly and `_clean` only dedupes/trims what the LLM
returns, it does not fabricate anything.

LLM failure, timeout, or a malformed/empty response all degrade to `[]` --
"no chip this turn" is a valid, designed state (see
plan 260819-1554-llm-grounded-chat-suggestions), not an error the caller must
handle -- with a `logger.warning` explaining why, never a silent swallow.
"""

from __future__ import annotations

import concurrent.futures
import logging
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from src.services.llm import get_fast_llm as get_llm

logger = logging.getLogger(__name__)

#: A call that hangs no longer costs the user latency (Phase 2 moves this
#: call after the `final` SSE frame), but it would otherwise hold an executor
#: slot and the turn's SSE connection open indefinitely. `get_llm`'s own
#: `timeout=` only reaches the OpenAI branch (its docstring) -- the local
#: Ollama fallback has no request-level timeout of its own, so
#: `generate_next_chat_suggestions` also wraps the call in a wall-clock guard
#: (`concurrent.futures`) that bounds every provider uniformly.
_DEFAULT_TIMEOUT_SECONDS = 12.0

_MAX_CARDS_IN_PROMPT = 5
_MAX_SUGGESTION_WORDS = 12

#: A short, human phrase for what each gated worker just did, spliced into the
#: prompt so the model grounds its suggestions in the right kind of action
#: instead of guessing from the reply text alone. Keys are the worker names
#: gated in `routes.py`'s `_SUGGESTION_WORKERS`.
_ACTION_HINTS: dict[str, str] = {
    "hotel_node": "vừa tìm/lọc danh sách khách sạn -- các thẻ khách sạn dưới đây là kết quả",
    "itinerary_node": "vừa tạo hoặc chỉnh sửa lịch trình chuyến đi",
    "budget_check": "vừa kiểm tra ngân sách so với lựa chọn hiện tại",
    "booking_node": "vừa xử lý yêu cầu đặt hoặc thanh toán",
}


@dataclass(frozen=True)
class SuggestionHotelCard:
    """The subset of one hotel card's fields worth grounding a chip in."""

    name: str
    price: float | None = None
    review_score: float | None = None


@dataclass(frozen=True)
class SuggestionContext:
    """Grounding data for one turn's suggestion chips.

    A thin, dependency-free dataclass on purpose: both `routes.py` (the web
    path) and `terminal_chat.py` (the CLI path, a structurally different
    session type) build one from whatever their own turn data looks like, so
    this is the one shape `generate_next_chat_suggestions` needs to know
    about rather than reaching into either caller's state directly.
    """

    worker: str
    status: str
    reply: str
    language: str
    destination: str | None = None
    hotel_cards: tuple[SuggestionHotelCard, ...] = ()
    hotel_amenity_labels: tuple[str, ...] = ()
    active_filter_labels: tuple[str, ...] = ()
    trip_duration_days: int | None = None


class NextChatSuggestions(BaseModel):
    """Structured-output shape the LLM must fill -- see `supervisor.py`'s
    `SupervisorDecision` for the same `with_structured_output` pattern."""

    suggestions: list[str] = Field(default_factory=list)


def _clean(items: list[str], limit: int) -> list[str]:
    """strip -> drop a leading ordinal prefix -> dedupe (case-insensitive) ->
    drop empties -> `[:max(1, limit)]`."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in items:
        text = re.sub(r"^\d+[.)]\s*", "", str(raw).strip()).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned[: max(1, limit)]


def _format_cards(cards: tuple[SuggestionHotelCard, ...]) -> str:
    if not cards:
        return "(không có khách sạn nào đang hiển thị)"
    lines = []
    for card in cards[:_MAX_CARDS_IN_PROMPT]:
        price = f"{card.price:,.0f}đ/đêm" if card.price is not None else "chưa rõ"
        score = f"{card.review_score:.1f}" if card.review_score is not None else "chưa rõ"
        lines.append(f"- {card.name}: giá {price}, điểm đánh giá {score}")
    return "\n".join(lines)


def _build_prompt(context: SuggestionContext, limit: int) -> str:
    language_instruction = (
        "Viết TOÀN BỘ gợi ý bằng tiếng Anh."
        if context.language == "en"
        else "Viết TOÀN BỘ gợi ý bằng tiếng Việt."
    )
    amenities = ", ".join(context.hotel_amenity_labels) or "(không có)"
    filters = ", ".join(context.active_filter_labels) or "(không có)"
    action_hint = _ACTION_HINTS.get(context.worker, context.worker)
    duration = (
        f"{context.trip_duration_days} ngày"
        if context.trip_duration_days is not None
        else "(chưa có lịch trình)"
    )
    return f"""Bạn là trợ lý du lịch. Dựa trên dữ liệu THẬT của lượt hội thoại vừa rồi, hãy đưa ra tối đa {limit} gợi ý câu tiếp theo mà người dùng có thể gửi thẳng vào khung chat.

{language_instruction}

Điểm đến: {context.destination or "(chưa rõ)"}
Số ngày lịch trình: {duration}
Khách sạn đang hiển thị:
{_format_cards(context.hotel_cards)}
Tiện ích có thật trên các thẻ khách sạn: {amenities}
Bộ lọc đang bật: {filters}
Hành động vừa thực hiện: {action_hint}
Trả lời gần nhất của trợ lý: {context.reply[:800]}

Ràng buộc bắt buộc:
- Chỉ dùng dữ liệu đã cho ở trên, không bịa thêm khách sạn, tiện ích, hay số liệu.
- Nếu gợi ý là một yêu cầu lọc, PHẢI kèm số cụ thể lấy từ dữ liệu trên (ví dụ điểm đánh giá, mức giá).
- Không nhắc tới bất kỳ tiện ích nào ngoài danh sách tiện ích có thật ở trên.
- Mỗi gợi ý là một câu lệnh hoàn chỉnh, gửi thẳng vào chat được, dưới {_MAX_SUGGESTION_WORDS} từ.
- Không giải thích gì thêm ngoài danh sách gợi ý."""


def generate_next_chat_suggestions(context: SuggestionContext, limit: int = 3) -> list[str]:
    """Grounded next-chat suggestion chips for one turn, or `[]`.

    Never raises. See module docstring for the "no static fallback, `[]` is
    a valid state" contract.
    """
    prompt = _build_prompt(context, limit)
    try:
        llm = get_llm(temperature=0.7, timeout=_DEFAULT_TIMEOUT_SECONDS)
        structured = llm.with_structured_output(NextChatSuggestions)
        # A dedicated one-shot pool rather than a call-site `run_in_executor`:
        # this function is itself already called from inside a worker thread
        # (`routes.py`'s `planner_chat_stream`), so this is the boundary that
        # can actually enforce a deadline uniformly across providers (see the
        # module-level `_DEFAULT_TIMEOUT_SECONDS` docstring). `shutdown(wait=
        # False)` on timeout is deliberate: Python cannot forcibly kill a
        # running thread, so a hung Ollama call keeps running in the
        # background either way -- the goal here is only to stop THIS
        # function from blocking on it, never to guarantee the call itself
        # stops.
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            result = pool.submit(structured.invoke, [HumanMessage(content=prompt)]).result(
                timeout=_DEFAULT_TIMEOUT_SECONDS
            )
        finally:
            pool.shutdown(wait=False)
        if not isinstance(result, NextChatSuggestions):
            logger.warning(
                "generate_next_chat_suggestions: structured output returned %s, not NextChatSuggestions",
                type(result).__name__,
            )
            return []
        cleaned = _clean(result.suggestions, limit)
        if not cleaned:
            logger.warning("generate_next_chat_suggestions: LLM returned no usable suggestions")
        return cleaned
    except concurrent.futures.TimeoutError:
        logger.warning(
            "generate_next_chat_suggestions timed out after %ss", _DEFAULT_TIMEOUT_SECONDS
        )
        return []
    except Exception as exc:
        logger.warning("generate_next_chat_suggestions failed: %s", exc)
        return []
