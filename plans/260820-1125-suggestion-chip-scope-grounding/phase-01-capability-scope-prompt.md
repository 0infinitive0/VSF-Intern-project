# Phase 1 — Capability scope in the suggestion prompt

**Status:** done
**Files:** `backend/src/services/suggestions.py`, `backend/tests/test_suggestions.py`

## Context

`_build_prompt` grounds chips in this turn's data but never says what the assistant is able
to do, so "Đặt phòng Khách sạn B" satisfies every current rule. Nothing downstream rejects
it (`plan.md` §Established facts). Fix is one prompt section plus tests that pin it.

## Requirements

Add a capability block to `_build_prompt`, above the existing `Ràng buộc bắt buộc` list:

- **Allowed**, mirroring the workers that actually exist (`prompts.py:20-24`):
  1. tìm / lọc / sắp xếp / chọn khách sạn (`hotel_node`)
  2. hỏi đáp read-only về khách sạn & phòng ĐANG hiển thị (`qa_node`)
  3. tạo / sửa lịch trình theo ngày, tìm địa điểm nổi bật gần khách sạn (`itinerary_node`)
  4. kiểm tra ngân sách so với lựa chọn hiện tại (`budget_check`)
- **Forbidden**, each one a real dead end today: đặt phòng / thanh toán
  (`booking_node` always declines, and is unroutable), vé máy bay / tàu / xe, thời tiết,
  ảnh / video, đánh giá hay giá từ nguồn ngoài (Booking/Agoda/...), visa, bảo hiểm, và bất
  cứ yêu cầu nào cần dữ liệu ngoài dữ liệu đã cho ở trên.
- Written in Vietnamese like the rest of the prompt; the existing `language_instruction`
  already controls the *output* language independently, so an `en` turn still gets English
  chips from a Vietnamese instruction (same as today — do not duplicate the block per
  language).
- Keep it a fixed instruction block. It is not a suggestion source, so it does not violate
  the module's "no static/hardcoded suggestion list" charter (module docstring, lines 1-15) —
  make that distinction explicit in a short comment so a later reader does not "fix" it.

Update the module docstring's opening paragraph: chips are grounded in this turn's data
**and bounded to what the graph can actually serve**.

## Steps

1. Extract the two lists to module constants next to `_ACTION_HINTS` (`_ALLOWED_SCOPE`,
   `_FORBIDDEN_SCOPE`) so the tests assert against the constants rather than re-typing
   prompt prose.
2. Splice both into the f-string in `_build_prompt`.
3. Extend the docstrings (module + `_build_prompt` if it gains one).

## Validation

Add to `tests/test_suggestions.py`, extending the existing
`test_prompt_states_the_no_fabrication_and_grounded_number_constraints` pattern
(`_CapturingLLM`, no real model anywhere in this file):

- `test_prompt_states_the_capability_whitelist` — every line of `_ALLOWED_SCOPE` appears in
  the built prompt.
- `test_prompt_forbids_out_of_scope_requests` — every line of `_FORBIDDEN_SCOPE` appears,
  and the prompt mentions đặt phòng and vé máy bay specifically (the two most likely drifts).
- `test_scope_block_is_present_for_every_gated_worker` — loop the four keys of
  `_ACTION_HINTS`, assert the block is in each built prompt (a worker-specific prompt branch
  added later cannot silently drop it).

Run: `pytest tests/test_suggestions.py -q`.

## Risk / rollback

Low. Prompt-only; `[]` remains a valid outcome on any LLM failure, so the worst case of a
badly worded block is fewer chips, never a broken turn. Rollback = revert the one file.

Residual risk accepted by decision #1: prompt instructions are not a hard guarantee, so an
occasional out-of-scope chip is still possible. That is a chip that produces a weak answer,
not an error.
