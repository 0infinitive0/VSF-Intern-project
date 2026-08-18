"""Spike: đo reasoning summary thật của OpenAI reasoning models.

Plan 260818-0924-deepdive-thinking-loader Phase 1. KHÔNG import vào đường chạy
sản phẩm — script này chỉ tồn tại để trả lời 5 câu hỏi bằng số đo, trước khi
Phase 2 đụng vào `services/llm.py`:

1. `reasoning={"summary": "auto"}` có trả về block reasoning thật không?
2. Summary ra ngôn ngữ gì với input tiếng Việt? Prompt có ép được sang tiếng Việt?
3. Tốn thêm bao nhiêu giây so với đường cơ sở (Chat Completions)?
4. Khi streaming qua Responses API, `chunk.content` là `str` hay list block?
   Đây là câu quyết định `routes.py:548` (`isinstance(content, str)`) có vỡ không.
5. Model bật Responses API còn gọi được tool không? (ReAct trong `qa_node`)

Chạy:
    python backend/scripts/spike_reasoning_summary.py            # toàn bộ ma trận
    python backend/scripts/spike_reasoning_summary.py --quick    # 1 model, 1 effort
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Prompt tiếng Việt thật — ngôn ngữ input ảnh hưởng ngôn ngữ summary, nên không
# dùng câu test tiếng Anh cho tiện.
VI_SYSTEM = (
    "Bạn là trợ lý lập kế hoạch du lịch. Trả lời ngắn gọn bằng tiếng Việt, "
    "chỉ dựa trên điều bạn thực sự biết."
)
VI_SYSTEM_FORCE_VI = VI_SYSTEM + (
    "\n\nQUAN TRỌNG: toàn bộ quá trình suy luận nội bộ của bạn phải viết bằng "
    "tiếng Việt, không dùng tiếng Anh."
)
VI_USER = (
    "Tôi muốn đi Đà Nẵng 3 ngày 2 đêm với ngân sách 8 triệu cho 2 người. "
    "Nên sắp xếp lịch trình thế nào cho hợp lý?"
)


@dataclass
class Measurement:
    model: str
    effort: str | None
    reasoning_on: bool
    forced_vi: bool = False
    reasoning_blocks: int = 0
    reasoning_chars: int = 0
    text_chars: int = 0
    ttft_s: float = 0.0
    total_s: float = 0.0
    content_shapes: set[str] = field(default_factory=set)
    block_types: set[str] = field(default_factory=set)
    sample: str = ""
    error: str = ""


def _build(model: str, effort: str | None, reasoning_on: bool) -> ChatOpenAI:
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": os.environ["OPENAI_API_KEY"],
    }
    if reasoning_on:
        # Truyền `reasoning` → langchain-openai tự route sang Responses API.
        # Loại trừ lẫn nhau với `reasoning_effort`, không được truyền cả hai.
        kwargs["reasoning"] = {"effort": effort, "summary": "auto"}
    elif effort:
        kwargs["reasoning_effort"] = effort  # đường hiện tại của services/llm.py
    return ChatOpenAI(**kwargs)


def measure(model: str, effort: str | None, reasoning_on: bool, forced_vi: bool = False) -> Measurement:
    m = Measurement(model=model, effort=effort, reasoning_on=reasoning_on, forced_vi=forced_vi)
    system = VI_SYSTEM_FORCE_VI if forced_vi else VI_SYSTEM
    messages = [("system", system), ("human", VI_USER)]

    started = time.monotonic()
    first_token_at: float | None = None
    reasoning_parts: list[str] = []

    try:
        for chunk in _build(model, effort, reasoning_on).stream(messages):
            if first_token_at is None:
                first_token_at = time.monotonic()

            content = getattr(chunk, "content", "")
            m.content_shapes.add(type(content).__name__)

            if isinstance(content, str):
                m.text_chars += len(content)
                continue

            # Responses API: `.content` thô mang hình dạng OpenAI
            # (`{"type":"reasoning","summary":[{"text": ...}]}`), còn
            # `.content_blocks` chuẩn hoá sang `{"type":"reasoning","reasoning": ...}`.
            # Đo trên bản chuẩn hoá — đó là API Phase 3 sẽ dùng.
            for block in getattr(chunk, "content_blocks", None) or ():
                if not isinstance(block, dict):
                    m.block_types.add(f"non-dict:{type(block).__name__}")
                    continue
                btype = block.get("type", "?")
                m.block_types.add(btype)
                if btype == "reasoning":
                    part = block.get("reasoning") or ""
                    if part:
                        reasoning_parts.append(part)
                        m.reasoning_chars += len(part)
                elif btype == "text":
                    m.text_chars += len(block.get("text") or "")
    except Exception as exc:  # noqa: BLE001 — spike phải báo lỗi, không nuốt
        m.error = f"{type(exc).__name__}: {exc}"

    m.total_s = time.monotonic() - started
    m.ttft_s = (first_token_at - started) if first_token_at else 0.0
    m.reasoning_blocks = len(reasoning_parts)
    m.sample = "".join(reasoning_parts)[:400]
    return m


def probe_tool_calling(model: str, effort: str) -> str:
    """Câu hỏi 5: model bật Responses API còn bind/gọi được tool không?"""

    @tool
    def recommend_hotels(city: str, budget_vnd: int) -> str:
        """Gợi ý khách sạn theo thành phố và ngân sách."""
        return f"3 khách sạn ở {city} dưới {budget_vnd} VND"

    try:
        bound = _build(model, effort, reasoning_on=True).bind_tools([recommend_hotels])
        res = bound.invoke(
            [
                ("system", "Bạn là trợ lý du lịch. Dùng tool khi người dùng hỏi về khách sạn."),
                ("human", "Tìm giúp tôi khách sạn ở Đà Nẵng dưới 2 triệu một đêm."),
            ]
        )
        calls = getattr(res, "tool_calls", []) or []
        if calls:
            return f"OK — gọi {len(calls)} tool: {[c.get('name') for c in calls]}"
        return f"KHÔNG gọi tool. content={str(getattr(res, 'content', ''))[:200]!r}"
    except Exception as exc:  # noqa: BLE001
        return f"LỖI — {type(exc).__name__}: {exc}"


def _row(m: Measurement) -> str:
    mode = "reasoning" if m.reasoning_on else "baseline"
    if m.forced_vi:
        mode += "+forceVI"
    if m.error:
        return f"| {m.model} | {m.effort} | {mode} | LỖI | | | | {m.error[:60]} |"
    return (
        f"| {m.model} | {m.effort} | {mode} | {m.reasoning_blocks} | {m.reasoning_chars} "
        f"| {m.text_chars} | {m.ttft_s:.1f}s | {m.total_s:.1f}s |"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="1 model, 1 effort")
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("Thiếu OPENAI_API_KEY trong backend/.env", file=sys.stderr)
        return 1

    reasoning_model = os.environ.get("LLM_MODEL", "gpt-5.1-2025-11-13")
    fast_model = os.environ.get("LLM_FAST_MODEL", "gpt-5-mini-2025-08-07")

    models = [fast_model] if args.quick else [fast_model, reasoning_model]
    efforts = ["low"] if args.quick else ["low", "medium", "high"]

    results: list[Measurement] = []
    for model in models:
        for effort in efforts:
            print(f"→ {model} / {effort} / baseline …", file=sys.stderr)
            results.append(measure(model, effort, reasoning_on=False))
            print(f"→ {model} / {effort} / reasoning …", file=sys.stderr)
            results.append(measure(model, effort, reasoning_on=True))

    # Ép tiếng Việt: chỉ đo ở mức effort giữa, đủ để trả lời câu hỏi ngôn ngữ.
    force_effort = "low" if args.quick else "medium"
    for model in models:
        print(f"→ {model} / {force_effort} / reasoning+forceVI …", file=sys.stderr)
        results.append(measure(model, force_effort, reasoning_on=True, forced_vi=True))

    print("\n| model | effort | mode | blocks | reasoning ký tự | text ký tự | TTFT | tổng |")
    print("|---|---|---|---|---|---|---|---|")
    for m in results:
        print(_row(m))

    print("\n## Hình dạng content")
    for m in results:
        if m.reasoning_on and not m.error:
            print(f"- {m.model}/{m.effort}: content={sorted(m.content_shapes)} blocks={sorted(m.block_types)}")

    print("\n## Mẫu reasoning (400 ký tự đầu)")
    for m in results:
        if m.sample:
            tag = "forceVI" if m.forced_vi else "auto"
            print(f"\n### {m.model} / {m.effort} / {tag}\n{m.sample}")

    print("\n## Tool-calling qua Responses API")
    for model in models:
        print(f"- {model}: {probe_tool_calling(model, force_effort)}")

    if args.json_out:
        args.json_out.write_text(
            json.dumps(
                [{**vars(m), "content_shapes": sorted(m.content_shapes), "block_types": sorted(m.block_types)} for m in results],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
