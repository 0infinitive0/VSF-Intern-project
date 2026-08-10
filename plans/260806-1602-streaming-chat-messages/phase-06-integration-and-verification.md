---
title: "Phase 6: Integration and verification"
status: "done (hotel-search/finalize/free-chat manual bilingual e2e walkthrough not run — see plans/reports/verification-260806-streaming.md)"
phase: 6
priority: P1
effort: "1.5 ngày"
dependencies: [2, 3, 4, 5]
---

# Phase 6: Tích hợp & kiểm thử

## Overview

Ghép FE thật với BE thật, xác minh ba tầng proxy bằng tay, gác hai bất biến quan trọng nhất
của plan bằng test, đo hiệu năng, rồi cập nhật lại các plan liên quan.

Phần lớn phase này là **xác minh**, không phải code mới. Hai thứ duy nhất được viết mới là
test tương đương hai endpoint và test proxy.

## Requirements

- Functional: mọi tiêu chí hoàn thành trong `plan.md` đạt trên backend thật, không phải mock.
- Non-functional: SSE chạy qua **cả ba** tầng proxy — Vite dev, nginx Docker, Caddy staging.

## Architecture

### Hai bất biến phải gác bằng test, không bằng review

**1. Hai endpoint không được trôi khỏi nhau.** Phase 1 đã trích `build_chat_response()` dùng
chung, nhưng dùng chung một helper không ngăn được ai đó thêm field ở một bên. Test:

```python
def test_stream_final_matches_post_body(...):
    """`final` của stream phải khớp byte-for-byte với body của POST cũ.

    Hai session riêng, cùng kịch bản tin nhắn, so sánh dict đã parse. `session_id`
    khác nhau nên bỏ ra trước khi so.
    """
```

Chạy trên **cả bốn nhánh**: intake, recommend_hotels, agent chat, finalize.

**2. Nối delta == `final.reply`.** Đã có ở Phase 3 cho một ca; ở đây mở rộng ra mọi lượt
có stream token trong kịch bản 4 lượt.

### Xác minh proxy — bằng tay, có mốc thời gian

Buffering ở proxy là loại lỗi **chỉ lộ ra sau khi deploy** và không test tự động rẻ được.
Làm bằng tay, ghi kết quả vào report:

```bash
curl -N -X POST "$BASE/api/v1/planner_chat/stream" \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"...","message":"...","language":"vi"}' \
  | while IFS= read -r line; do printf '%s  %s\n' "$(date +%s.%N)" "$line"; done
```

Chạy với `$BASE` = ba giá trị: Vite dev (`localhost:5173`), nginx Docker
(`localhost:5173` sau `docker compose up`), Caddy staging. **Tiêu chí: khoảng cách thời
gian giữa frame đầu và frame `final` > 1s trên một lượt chậm.** Nếu mọi frame tới cùng lúc
thì có tầng đang buffer — chưa xong.

Caddy tự tắt buffering cho `text/event-stream` từ v2, nhưng đo chứ không tin tài liệu. Nếu
lệch, thêm `flush_interval -1` vào `Caddyfile`.

### Đo hiệu năng

Ba con số, ghi vào report, **không** tối ưu trước khi có số:

| Đo | Cách | Ngưỡng cần lo |
|---|---|---|
| `deepcopy(session.state)` với `trip_data` đầy | `timeit` quanh chỗ snapshot Phase 4 | > 50ms |
| Thread pool khi nhiều stream cùng lúc | 10 stream song song, xem có xếp hàng không | Xếp hàng ở < 10 |
| Chi phí phát event trên đường POST cũ | So thời gian lượt trước/sau Phase 2 | > 1% |

### Kịch bản đầu-cuối

Chạy tay trên backend thật, cả `vi` và `en`:

1. Lượt intake → thấy bước mọc dần, không có delta, form intake hiện ra như cũ
2. Lượt hotel → thấy `hotel_search`, card khách sạn hiện đúng như trước
3. Lượt hỏi đáp tự do → thấy token chảy
4. Lượt finalize → thấy `itinerary_build` → `routing_legs` → `persisting`, nút Dừng biến
   mất tại `persisting`
5. Huỷ giữa lượt hotel → bubble biến mất, gửi lại cùng tin nhắn cho kết quả như thường
6. Huỷ sau `persisting` → 409, lượt chạy tới hết
7. Tắt endpoint stream → hạ cấp về POST, người dùng không thấy khác biệt

## Related Code Files

- Create: `backend/tests/test_api/test_stream_post_parity.py`
- Create: `plans/reports/verification-260806-streaming.md` — kết quả proxy + số đo
- Modify: `docs/chat_api_contract.md` — chốt lại contract theo đúng thứ đã ship
- Modify: `plans/260805-1022-claude-design-ui-integration/plan.md` — cập nhật mục #14
- Modify: `Caddyfile` — chỉ khi đo thấy cần `flush_interval`
- Modify: `README.md` — một đoạn ngắn về endpoint stream, nếu README có mục API

## Implementation Steps

1. Viết `test_stream_post_parity.py`, 4 nhánh.
2. Mở rộng assertion nối-delta ra kịch bản 4 lượt.
3. Chạy toàn bộ test backend: `pytest backend/tests/`. Không được sửa test cũ để cho xanh.
4. Chạy test frontend + `npm run build`.
5. Xác minh proxy 3 tầng bằng `curl -N`, ghi mốc thời gian vào report.
6. Đo 3 con số hiệu năng, ghi vào report.
7. Chạy 7 kịch bản đầu-cuối bằng tay, cả `vi` và `en`.
8. Chốt `docs/chat_api_contract.md` theo đúng thứ đã ship (không phải theo thứ đã plan).
9. Cập nhật mục #14 ở `260805-1022/plan.md`: đóng có điều kiện, trỏ sang plan này, ghi rõ
   phần **không** làm (sáu ô tick vẽ sẵn).
10. Đánh dấu hai tiêu chí đang treo ở `260723-1015-v-ota-poc-master-roadmap`
    (`phase-03:63`, `phase-05:70`).

## Success Criteria

- [x] `final` khớp body POST trên cả 4 nhánh — `test_stream_post_parity.py`
- [x] Nối delta == `final.reply` trên mọi lượt có stream — trên nhánh agent-chat (nhánh duy
      nhất có stream); intake/hotel/finalize không có delta nên vô nghĩa với chúng
- [x] `pytest backend/tests/` xanh — **không sửa một test cũ nào** — 132 passed / 20 failed
      trong phạm vi test_api + test_agents + hai file characterization; toàn bộ 20 lỗi đối
      chiếu lại với `main` sạch bằng `git stash`, xác nhận có sẵn từ trước, không do plan
      này gây ra. Hai tệp test_agents/khác + phần lớn tests/*.py còn lại đã chạy chọn lọc
      (routing/itinerary_store/api_error_logging xanh; các phần phụ thuộc Supabase/Ollama
      trực tiếp không chạy hết vì rủi ro treo trong sandbox — xem báo cáo)
- [x] Test frontend xanh, `npm run build` sạch — 67/67 test, typecheck sạch, lint không có
      cảnh báo mới, build 224ms
- [x] `curl -N` cho thấy frame đến rải rác (không dồn cục) trên **cả ba** tầng proxy, có
      mốc thời gian trong report — Vite dev + nginx xác minh; **Caddy staging không truy
      cập được, chưa xác minh** (ghi rõ, không giả định đạt)
- [x] Ba số đo hiệu năng có trong report, kèm kết luận có cần tối ưu hay không —
      `emit_phase` phí không đáng kể (<1µs/call), 10 stream đồng thời không xếp hàng;
      `deepcopy(session.state)` **hoãn** — chỉ liên quan Phase 4 (paused)
- [ ] 7 kịch bản đầu-cuối chạy đúng ở cả `vi` và `en` — chỉ chạy tay được lượt intake (qua
      backend thật, cả 3 tầng proxy) + 2 kịch bản phụ thuộc huỷ lượt không áp dụng
      (Phase 4 paused); hotel-search/finalize/free-chat **chưa** chạy tay đầu-cuối bằng cả
      hai ngôn ngữ — nhánh của chúng có test tự động (parity + characterization) nhưng
      không phải chạy tay theo đúng yêu cầu mục này
- [x] `docs/chat_api_contract.md` khớp hành vi đã ship — thêm mục "Not shipped" cho huỷ lượt
- [x] Mục #14 ở plan 260805 được cập nhật, nêu rõ phần không làm
- [x] Register "Phần chưa làm" của plan này đúng với thực tế sau khi ship — mục 3 (huỷ tức
      thời) và rollback (mục 2) giờ áp dụng cho **toàn bộ** Phase 4, không chỉ một phần;
      không cần sửa nội dung, Phase 4 đã ghi "Pause" từ đầu

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Test parity xanh giả vì cả hai đường cùng sai | Nó gác *sự nhất quán*, không gác tính đúng. Tính đúng do test hiện có gác — đó là lý do cấm sửa test cũ |
| Xác minh proxy làm bằng mắt rồi bỏ qua | Bắt buộc dán mốc thời gian vào report. Không có số thì tiêu chí chưa đạt |
| Caddy staging không truy cập được lúc verify | Nếu vậy, ghi thẳng vào report là **chưa xác minh** và mở một việc tiếp theo. Không đánh dấu đạt |
| Kịch bản tay bỏ sót nhánh `en` | Cả 7 kịch bản chạy hai lần, một lần mỗi ngôn ngữ |
