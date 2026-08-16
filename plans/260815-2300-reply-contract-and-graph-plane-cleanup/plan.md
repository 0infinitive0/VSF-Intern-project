---
title: "Reply contract and graph plane cleanup"
description: "Đóng lỗ hổng kiến trúc: không worker nào bị bắt buộc phải phát ngôn, nên một lịch trình build thành công trả về câu ack cứng. Thêm contract emits_reply, dọn plane state chết trong routes.py, mở đường build itinerary from scratch, bỏ LLM call thừa ở supervisor, và thêm lớp polish LLM rewrite-only có eval chặn hallucinate số."
status: completed
priority: P1
effort: "5-6d"
tags: [langgraph, reply-contract, orchestration, tech-debt, nlg]
blockedBy: []
blocks: [260812-0927-langgraph-orchestration-state-patch-and-interrupts]
created: 2026-08-15
updated: 2026-08-15
---

# Reply contract and graph plane cleanup

## Overview

Plan `260812-0927-langgraph-orchestration-state-patch-and-interrupts` đã hoàn thành
16/17 phase và cutover thành công: hôm nay chỉ còn **một** control plane
(`_run_turn_via_graph` → `build_graph`), legacy cascade đã bị xoá. Topology của graph
đó đúng — delegation qua supervisor, completion check bằng edge thuần, contract
enforcement ở biên node, qa_node cô lập bằng schema boundary.

Nhưng khi review lại toàn bộ mặt phẳng graph, có **một lỗ hổng kiến trúc chưa ai đóng**:

> Không có gì bắt buộc một worker phải phát ngôn. `respond` được thiết kế để *nhặt*
> reply từ `task_results`, và khi không ai để lại reply thì nó rơi xuống một hằng số.

Hệ quả cụ thể, đang xảy ra trong production:

```
itinerary_node build xong 5 ngày (status OK)
  → path "All days done" (itinerary_node.py:362-370) trả task_results NGUYÊN XI,
    không append entry nào có "reply"
  → budget_check pass-through (budget_check.py:329, vì budget.trip_total chưa SET)
  → respond: _reply_from_task_results() = None
             _reply_from_messages()     = None
  → fallback _ACK_VI
```

**Người dùng dựng xong lịch trình 5 ngày và nhận được "Đã cập nhật thông tin chuyến đi."**

`_ACK_VI` đáng lẽ là lưới an toàn cuối cùng thì đang là **đường đi chính** của flow build
itinerary. Docstring của `respond.py` tự nhận nó tồn tại "for the pass-through stub workers
(hotel_node/itinerary_node) that have nothing to say yet" — nhưng Phase 8/9 đã implement
hai node đó từ lâu. Comment nói sai về hiện trạng.

Plan này đóng lỗ hổng đó ở tầng contract (không phải patch một dòng), rồi dọn nốt bốn
khoản nợ liên quan phát hiện trong cùng lần review.

## Phân loại hardcode reply — chỉ 1 trong 4 loại là bug

Quan trọng cho người thực thi: **đừng đụng vào 3 loại đầu.**

| Loại | Ví dụ | Phán quyết |
|---|---|---|
| **A. gettext msgid** | `t("Bạn muốn đi đâu?", language)` | **Không phải hardcode.** Tiếng Việt là msgid theo convention gettext; `backend/locales/{vi,en}/LC_MESSAGES/messages.mo` tồn tại thật. Đúng chuẩn, giữ nguyên. |
| **B. Template xác định** | `format_trip_response_from_json`, `_binding_constraint_reply`, `budget_check` replies | **Cố ý và đúng.** Đây là chỗ đọc số thật (giá, số khách sạn, tiện ích bị loại). Cho LLM viết lại = hallucinate số tiền. **Đừng thay bằng LLM.** |
| **C. List gợi ý cứng** | `suggestions.py:31-43` | Pragmatic short-circuit để né LLM call. Ngoài scope plan này. |
| **D. Generic ack** | `respond.py:79` `_ACK_VI` | **Đây là bug.** Phase 1 đóng nó. |

Nguyên tắc rút ra, được ghi thành doc ở Phase 3:
**số liệu → template; ý kiến/giọng văn → LLM.**

## Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Một turn build itinerary thành công không bao giờ trả về câu ack chung chung | P1 |
| 2 | Worker im lặng là lỗi test-time, không phải lỗi UX âm thầm | P1 |
| 3 | Không endpoint nào trả `success` cho dữ liệu rỗng | P1 |
| 4 | Doc mô tả đúng vai trò `respond` (assembler, không phải NLG node) | P2 |
| 5 | Đường build itinerary from scratch tồn tại và hiện rõ trong topology, không ẩn trong lambda | P2 |
| 6 | Không gọi LLM để quyết định thứ tự mà `WORKER_ORDER` đã quy định | P3 |
| 7 | Lớp polish cải thiện giọng văn mà **không** thêm được một con số nào | P3 |

## Phases

| # | Phase | Depends on | Priority | Effort | Status |
|---|-------|-----------|----------|--------|--------|
| 1 | [Reply contract](./phase-01-start.md) | — | P1 | 1d | ✅ done |
| 2 | [Dead plane cleanup](./phase-02-dead-plane-cleanup.md) | — | P1 | 0.5d | ✅ done |
| 3 | [Doc reconciliation](./phase-03-doc-reconciliation.md) | 1, 2 | P2 | 0.5d | ✅ done |
| 4 | [Trip data creation path](./phase-04-trip-data-creation-path.md) | 1 | P2 | 1.5d | ✅ done |
| 5 | [Supervisor fast path](./phase-05-supervisor-fast-path.md) | 4 | P3 | 0.5d | ✅ done |
| 6 | [Polish node](./phase-06-polish-node.md) | 1, 3 | P3 | 1.5d | ↩️ reverted — ship `off`, rồi gỡ hẳn 2026-08-16 |

**Phase 1 và 2 độc lập với nhau — ship được song song, ~1.5 ngày.** Phase 1 đóng bug
người dùng đang thấy; Phase 2 dọn endpoint đọc state chết. Không cái nào chờ cái nào.

**Phase 1 là điều kiện cần của tất cả phần còn lại.** Contract `emits_reply` là cơ chế
mà Phase 4 và 6 đều dựa vào: Phase 4 thêm một đường sinh `trip_data` mới (phải phát ngôn),
Phase 6 thêm một node đọc reply đã có (phải chắc chắn reply đó tồn tại và là template
xác định, không phải `_ACK_VI`).

**Điểm dừng tự nhiên:** sau 1+2 (bug đóng, nợ dọn), sau 3 (doc khớp code), sau 5
(kiến trúc sạch). Phase 6 là polish thuần tuý.

## Ghi chú về Phase 6 — quyết định của người dùng, có ghi nhận phản đối

Khi tư vấn, tôi khuyến nghị **YAGNI** cho lớp polish: reply xác định hiện tại đã đúng và
an toàn, và rủi ro của việc đưa LLM vào đường sinh reply là hallucinate số tiền/ngày —
đúng thứ mà `budget_check` docstring ("never invent missing prices") được viết ra để chặn.

Người dùng đã cân nhắc và quyết định làm. Plan này thực thi đầy đủ với hai điều kiện
kỹ thuật bù rủi ro, không thương lượng:

1. Polish node **chỉ được diễn đạt lại**, prompt cấm thêm fact, và chạy sau `budget_check`
   trên reply đã hoàn chỉnh — không phải sinh reply từ state.
2. Có **eval gate**: mọi con số xuất hiện trong reply sau polish phải khớp tập số trong
   reply trước polish. Lệch một số → fail, trả nguyên bản.

Nếu eval gate không đạt được ngưỡng trong Phase 6, dừng lại và trả nguyên bản vĩnh viễn
(env flag off) thay vì nới ngưỡng.

## Quan hệ với plan khác

`blocks: [260812-0927-langgraph-orchestration-state-patch-and-interrupts]`

Plan đó còn **Phase 16 — "Conversational polish layer for context lines and re-asks"**
(P3, `pending`). Phase 16 đổi cách diễn đạt câu hỏi re-ask trong `ask_slot`; plan này đổi
cơ chế reply của worker. Khác vấn đề, nhưng chạm cùng vùng code và cùng câu hỏi thiết kế
("chỗ nào được LLM-hoá").

Quyết định: **Phase 16 giữ nguyên trạng thái `pending`**, nhận `blockedBy` từ plan này.
Làm Phase 16 sau khi contract ở Phase 1 ổn định và sau khi Phase 6 cho biết lớp polish
LLM-rewrite có thực sự đáng giá hay không. Nếu Phase 6 thất bại ở eval gate, Phase 16
nhiều khả năng nên bị huỷ.

## Bảng triệu chứng → nguyên nhân → phase

| Triệu chứng | Nguyên nhân | Fix ở |
|---|---|---|
| Build xong lịch trình 5 ngày, reply là "Đã cập nhật thông tin chuyến đi." | `itinerary_node.py:362-370` không append `task_results` entry nào có `reply` | **1** |
| Không có cơ chế nào phát hiện worker im lặng | `CONTRACTS` chỉ khai `reads`/`writes`, không khai nghĩa vụ phát ngôn | **1** |
| Reply lộ identifier nội bộ: "lock_days: days_to_lock is empty" | `_err()` dùng chung cho dev-assert và user-facing error | **1** |
| `POST /itineraries/generate` trả `{"status": "success", "trip_plan": null}` | Đọc `session.trip_data`, mà graph ghi vào checkpointer state — hai nguồn sự thật | **2** |
| `POST /hotels/search` đọc `session.intake_state`/`pending_hotel_selection` | Cùng nguyên nhân: state của plane đã bị xoá | **2** |
| `_prepare_turn_inputs` không ai gọi | Sót lại sau cutover Phase 11 | **2** |
| `ARCHITECTURE.md` vẽ `RespondNode[Formatting & Polish Node]` không tồn tại | Doc viết theo thiết kế dự kiến, không cập nhật sau khi `respond` thành assembler | **3** |
| Không có đường build itinerary từ đầu | `_IMPOSSIBLE["itinerary_node"]` đòi `trip_data`, mà chỉ nhánh `selected_hotel_id` của `hotel_node` tạo `trip_data` | **4** |
| Ràng buộc "phải chọn khách sạn trước" ẩn trong một lambda | Không hiện trong graph topology, người đọc không thấy | **4** |
| Gọi LLM để chọn giữa `hotel_node`/`itinerary_node` khi `WORKER_ORDER` đã quy định thứ tự | `supervisor.py:112` chỉ fast-path khi `len(workers) == 1` | **5** |
| Reply đúng nhưng giọng văn máy móc | Không có lớp diễn đạt | **6** |

## Success Criteria

- [x] Turn build itinerary thành công trả reply chứa tên khách sạn và các ngày, không phải `_ACK_VI`
- [x] `enforce_contract` raise khi worker khai `emits_reply=True` mà không để lại reply
- [x] `_ACK_VI` log ERROR kèm `next_worker`/`task_results` mỗi lần bị chạm
- [x] Regression test: `test_respond.py` assert reply sau build != `_ACK_VI`
- [x] Không endpoint nào còn đọc `session.trip_data`/`intake_state`/`pending_hotel_selection`
- [x] `ARCHITECTURE.md` mô tả đúng `respond` là assembler; nguyên tắc "số liệu → template" được ghi
- [x] Tồn tại đường build itinerary không cần chọn khách sạn trước, hoặc ràng buộc đó hiện rõ trong `ask_slot`
- [x] Số LLM call/turn ở supervisor giảm, đo được trước/sau
- [x] Polish node: 100% số liệu trong reply sau polish khớp reply trước polish, trên bộ eval (35/35) — nhưng node vẫn để `off`, xem Phase 6
- [x] Toàn bộ `backend/tests/` xanh — 653 passed; 5 fail có sẵn từ trước, không liên quan

## Đã giải quyết khi lập plan

**`POST /itineraries/generate`, `POST /hotels/search`, `POST /chat/select_place` có client nào gọi không? — Không.**

`frontend/src/api/chat-client.ts` gọi đúng 5 endpoint (dòng 57, 71, 84, 96, 107):
`/chat/session`, `/planner_chat`, `/hotels/select`, `GET /chat/{id}/plan`,
`/hotels/change`. `frontend/src/api/stream-client.ts:134` gọi thêm
`/planner_chat/stream`. Không file nào trong `frontend/src/`, `backend/tests/`, hay
`eval/` gọi ba endpoint kia.

→ Phase 2 **xoá**, không port. Lưu ý `docs/chat_api_contract.md` còn tài liệu hoá chúng
(dòng 17, 19, 222, 264, 670-671), nên đây là **breaking change công khai** và phải ghi rõ.

## Open Questions

**Không còn.** Cả hai câu hỏi mở ban đầu đã được trả lời ở Validation Session 1 — xem
`## Validation Log`.

---

## Validation Log

### Session 1 — 2026-08-15
**Trigger:** `/ak:plan validate` ngay sau khi lập plan, trước khi thực thi.
**Questions asked:** 4

#### Verification Results
- **Tier:** Full (6 phases → cả 4 role)
- **Claims checked:** 47
- **Verified:** 42 | **Failed:** 5 | **Unverified:** 0

##### Failures (đã sửa)
1. [Fact Checker] Phase 1 dẫn `contracts.py:26` cho `NodeContract` — thực tế **dòng 25**
2. [Fact Checker] Phase 1 dẫn `contracts.py:112` cho `enforce_contract` — thực tế **dòng 117**
3. [Fact Checker] Phase 2 nói có một `print(f"DEBUG: …")` ở dòng 606 — thực tế **ba**: 602, 606, 609
4. [Contract Verifier] Phase 4 nói `test_legacy_guards.py` assert `is_impossible` "ở dòng ~38" — thực tế **bốn** assert: 37, 159, 166, **172** (172 assert `is False` khi đã có trip)
5. [Fact Checker] `hotels_search` def ở 587 (plan ghi 586-653); `itineraries_generate` def ở 656 (plan ghi 655-674) — lệch một dòng

Finding 4 làm **giảm** rủi ro Phase 4: dòng 172 pin cả chiều dương của
`is_impossible`, nên refactor `_requires_existing_trip` không thể âm thầm biến mọi thứ
thành impossible. Risk "Refactor `_IMPOSSIBLE` vô tình đổi hành vi" hạ từ Trung bình
xuống Thấp.

#### Questions & Answers

1. **[Risks]** Phase 1: khi `enforce_contract` phát hiện worker im lặng ở **production**,
   nên làm gì? (Plan hiện viết `raise ContractViolation` — nghĩa là người dùng nhận
   HTTP 500 thay vì một reply tệ)
   - Options: Raise ở dev/test, log ERROR ở prod (Recommended) | Raise ở mọi nơi | Chỉ log ERROR, không bao giờ raise
   - **Answer:** Raise ở dev/test, log ERROR ở prod
   - **Rationale:** Plan ban đầu bỏ sót đánh đổi này. Raise ở production biến một reply
     tệ thành một turn hỏng hẳn — tệ hơn chính bug đang sửa. Env-gated giữ được tác dụng
     chặn ở CI mà không đẩy rủi ro sang người dùng.

2. **[Scope]** Phase 2: ba endpoint không có caller trong repo nhưng đã tài liệu hoá
   trong `docs/chat_api_contract.md`. Xử lý thế nào?
   - Options: Xoá hẳn (Recommended) | Trả HTTP 410 Gone | Giữ nguyên, chỉ sửa để đọc graph state
   - **Answer:** Xoá hẳn
   - **Rationale:** Dự án thực tập, không có consumer ngoài cần bảo đảm tương thích.
     Phương án 410 giữ lại ở bảng risk như đường lùi nếu bước 1 phát hiện caller ngoài repo.

3. **[Risks]** Phase 6: điều kiện để bật `REPLY_POLISH_MODE=on` ở production?
   - Options: 100% parity + shadow 1 ngày, rồi bật (Recommended) | Shadow-only vĩnh viễn | Bật `on` ngay sau khi eval đạt, bỏ shadow
   - **Answer:** 100% parity + shadow 1 ngày, rồi bật
   - **Rationale:** Giữ nguyên thiết kế gate đã viết. Shadow là bước bắt buộc vì eval
     dùng mẫu tự chọn, không phản ánh phân phối traffic thật — case đảo nghĩa
     ("không tìm thấy" → "có ít lựa chọn") chỉ lộ ra khi đọc log traffic thật.

4. **[Architecture]** Open Question 1 — `booking_node` có để `_IMPOSSIBLE = True`
   vĩnh viễn không?
   - Options: Chưa biết — giữ nguyên, ghi nợ (Recommended) | Vĩnh viễn — gỡ khỏi WORKER_ORDER và Literal | Sẽ mở — giữ nguyên, không đụng
   - **Answer:** Sẽ mở — giữ nguyên, không đụng
   - **Rationale:** Đề xuất gỡ `booking_node` khỏi `WORKER_ORDER`/`Literal` bị **rút**.
     Phase 5 bước 7 chuyển từ "quyết định rồi gỡ" thành "không đụng".

#### Confirmed Decisions
- **Contract enforcement**: env-gated `strict`|`log`, mặc định `strict` — CI chặn, prod không vỡ turn
- **Dead endpoints**: xoá hẳn, không giữ route 410
- **Polish gate**: eval 100% parity → shadow ≥1 ngày → mới bật `on`
- **booking_node**: giữ nguyên trong `WORKER_ORDER` và `Literal`; sản phẩm sẽ mở booking

#### Action Items
- [x] Sửa 5 line-reference sai từ verification pass
- [x] Phase 1: thêm `contract_enforcement_mode` vào config, Architecture, steps, criteria, risks
- [x] Phase 2: sửa thành ba `print` (602, 606, 609); ghi quyết định xoá hẳn
- [x] Phase 4: bảng 4 assert của `test_legacy_guards.py`; hạ mức risk refactor
- [x] Phase 5: rút đề xuất gỡ `booking_node`; sửa bước 7, criteria, risk
- [x] Phase 6: sửa `scope_guard.py:44`→`:48`, thêm `config.py:100`; liệt kê 3 assert của test topology

#### Impact on Phases
- **Phase 1**: +1 bước (2b), +1 file sửa (`config.py`), +2 test case, +2 risk row. Effort giữ 1d.
- **Phase 2**: nội dung chính xác hơn, phạm vi không đổi.
- **Phase 4**: risk giảm, không đổi phạm vi.
- **Phase 5**: bước 7 **thu hẹp** — không còn thay đổi `WORKER_ORDER`/`Literal`.
- **Phase 6**: chi tiết test topology rõ hơn, phạm vi không đổi.

### Whole-Plan Consistency Sweep
- Files reread: `plan.md`, `phase-01-start.md`, `phase-02-dead-plane-cleanup.md`,
  `phase-03-doc-reconciliation.md`, `phase-04-trip-data-creation-path.md`,
  `phase-05-supervisor-fast-path.md`, `phase-06-polish-node.md`
- Decision deltas checked: 4
- Reconciled stale references: 6
- **Unresolved contradictions: 0**

<!-- slug: reply-contract-and-graph-plane-cleanup -->

---

## Execution Log

### 2026-08-15 — Phases 1 and 2 shipped together

Both P1 phases done in one pass, as the plan anticipated (independent of each
other, ~1.5d combined). Phases 3-6 untouched and still `pending`.

The user-visible bug is closed: a finished itinerary build now replies with the
hotel name and each day, built by `format_trip_response_from_json` from the trip
that was actually created — no LLM in that path, so no number in it can be
invented. `_ACK_VI` is back to being the safety net, and it now logs at ERROR
with routing context every time it is reached.

Test suite: **618 passed, 5 failed**. The 5 failures pre-date this work and are
unrelated (missing migration `.sql` files; a test patching a private helper
`trip_planner._search_attraction_candidates` that no longer exists). Baseline
before these phases was 600 passed / the same 5 failed.

Two acceptance items in the phase files are recorded as **not done**: the manual
end-to-end turn (Phase 1 step 10) and the manual five-endpoint smoke test (Phase 2
step 9). Both need a running backend + frontend + live LLM/Supabase, unavailable
in that session. Everything reachable without a live stack was verified.

Success criteria still open below belong to Phases 3-6.

### 2026-08-15 — Phases 3, 4 and 5

Plan order followed (3 → 4 → 5). Phase 6 deliberately not started.

**Phase 3** found more drift than it described: besides the ghost
`RespondNode[Formatting & Polish Node]`, the whole "AI Agent" section, its control-flow
diagram, and Data Flow steps 3-6 still documented `process_chat_turn` and
`src/services/chat_session.py` — a module that no longer exists. All rewritten from
`graph.py` as ground truth, and both remaining criteria of Goal 4 now hold.

**Phase 4** kept Option A. The plan's loop mitigation turned out to be insufficient and
was strengthened: because `all_tasks_done` is `not pending_tasks` and `hotel_node`
removes only itself, the `needs_trip_first` redirect has to *hand over* the pending slot
rather than add to it, or the turn loops until the iteration cap. Pinned by test.

**Phase 5** measured the LLM budget before and after: a multi-worker first delegation
went from **1 supervisor LLM call to 0**; single-worker and recovery turns unchanged.
One test went red — exactly the predicted one — and was relocated to the recovery branch
where its assertion is still true, not deleted.

Suite after all five phases: **628 passed, 5 failed**, the same 5 pre-existing unrelated
failures present before any of this work.

**A finding outside the plan's scope, recorded not fixed:** `src/cli/terminal_chat.py`
raises `ImportError` on import — it still imports `process_chat_turn` from
`src.agents.session`. It is a cutover leftover of the same family as Phase 2's dead
endpoints, but deleting versus porting the CLI is a product decision. Recorded in
`ARCHITECTURE.md`'s Known debt table.

Manual/live-stack verification remains outstanding across Phases 1, 2, 4, and 5 — each
phase file names exactly which step.

### 2026-08-16 — Phase 6, và kết thúc plan

Cả 6 phase đã xong. Suite: **653 passed**, vẫn đúng 5 fail có sẵn từ trước plan này.

**Phase 6 kết thúc bằng "không bật", và đó là một kết quả hợp lệ đã được dự liệu.**

Hàng rào số hoạt động đúng: eval 35 mẫu đạt **100% number parity**, kể cả itinerary 7 ngày
(31 dòng vào, 31 dòng ra, đủ khối ngày). Không con số nào bị thêm, bớt, hay đổi định dạng.

Nhưng đọc output thì thấy **2 ca đổi nghĩa mà parity không thể thấy**: một ca biến "filter
loại bỏ 7 khách sạn" thành "có 7 khách sạn" (nghĩa ngược lại), một ca biến "sau khi tìm
khách sạn rẻ hơn" thành "đã tìm được khách sạn rẻ hơn" (thêm fact). Đúng risk row
"LLM giữ đúng số nhưng đổi ngữ nghĩa" của chính Phase 6.

Theo bước 13, kết luận là **`REPLY_POLISH_MODE=off` vĩnh viễn cho tới khi có bằng chứng
mới**. Code đã ship đầy đủ và có test; ở mode `off` node return `{}` ngay, không LLM call,
hành vi y hệt trước phase.

**Cập nhật 2026-08-16 — node đã gỡ hẳn.** "Off vĩnh viễn" và "giữ code sau flag" là hai
chuyện khác nhau: một đường rewrite đang tắt vẫn nằm trong graph, trong state, trong
config, và vẫn là lời mời bật lên bởi người không đọc phần kết luận này. Đã xoá
`nodes/polish.py`, `polished_reply` khỏi state, 3 setting `REPLY_POLISH_*`,
`build_polish_prompt`, và `eval/polish_number_parity.py` + kết quả eval; `budget_check`
nối thẳng `respond` trở lại. Bằng chứng và lý do giữ ở `ARCHITECTURE.md`
§"Reply generation rule" để lần sau ai đề xuất lại thì phải mang lập luận mới.

Đánh giá lại lời khuyên YAGNI ban đầu: chi phí đã bounded đúng như plan viết, và phase này
**trả về một câu trả lời có giá trị** — nó chứng minh bằng số liệu rằng lớp LLM-rewrite
không an toàn cho reply mang dữ liệu của dự án này, thay vì để câu hỏi đó mở mãi.

**Hệ quả:** Phase 16 của plan `260812-0927-…` nhiều khả năng nên huỷ — cùng model, trên
text ngắn hơn và đơn giản hơn, đã đổi nghĩa 2 lần trong 35 mẫu; câu re-ask của `ask_slot`
còn nhạy cảm hơn. Quyết định cuối thuộc về người dùng.

**Việc còn lại cần môi trường chạy thật** (không phase nào block): manual E2E của Phase 1
bước 10, smoke test Phase 2 bước 9, manual test Phase 4 bước 10, đo latency Phase 5 bước 8.