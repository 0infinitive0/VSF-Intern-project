---
title: "Phase 5: Ops, chi phí, và quyết định"
status: todo
priority: P1
effort: "0.5-1d"
dependencies: [3, 4]
---

# Phase 5: Ops, chi phí, và quyết định

## Overview

Chuyển số đo thành quyết định. Phase này chia làm hai phần chạy ở hai thời điểm
khác nhau:

- **5.1 — đăng ký trước.** Chạy **sau Phase 2, trước Phase 3**. Chốt trọng số và
  ngưỡng quyết định khi chưa có bất kỳ số đo nào. Commit riêng, có timestamp.
- **5.2-5.5 — chấm điểm và kết luận.** Chạy sau Phase 4.

Tách như vậy không phải nghi thức thừa. Không có nó thì trọng số sẽ vô thức
trượt về phía đáp án mình thích, và cả plan biến thành hợp lý hóa cho một quyết
định đã có sẵn.

## Requirements

**Functional**
- [ ] 5.1 chốt trọng số + ngưỡng, commit trước Phase 3
- [ ] Đo RAM footprint thật của Qdrant trên t3.micro
- [ ] Đánh giá free tier limit, backup/restore, lock-in
- [ ] Đánh giá khoảng cách chức năng: join hotels↔rooms
- [ ] Chấm ma trận quyết định theo đúng trọng số đã đăng ký
- [ ] Khuyến nghị kèm điều kiện lật ngược
- [ ] `report.md` + biểu đồ

**Non-functional**
- [ ] Mọi điểm số truy ngược được về raw JSONL hoặc bằng chứng định tính có ghi nguồn
- [ ] Đổi trọng số sau 5.1 phải ghi vào changelog kèm lý do

## Architecture

### 5.1 — Ngưỡng đăng ký trước

Cây quyết định, chốt **trước khi** thấy số:

```
Nếu S-sql đạt filtered recall ≥ 0.95 ở mọi tầng:
    → GIỮ SUPABASE, bỏ Qdrant khỏi kiến trúc.
      Lý do: một RPC sửa được thắng một hệ thống phải nuôi.
      Đúng kể cả khi Q-native nhanh hơn, vì latency chỉ 10% trọng số
      và đo từ laptop không đủ cơ sở.

Ngược lại nếu Q-native hơn S-sql ≥ 0.10 filtered recall ở ≥ 2 tầng:
    → CÂN NHẮC QDRANT. Nhưng phải trừ đi chi phí ops:
      mất khả năng join hotels↔rooms, thêm ~200MB RAM trên box 908Mi,
      thêm một đường sync phải giữ đồng bộ.
      Chỉ chọn Qdrant nếu tổng điểm ma trận hơn ≥ 10%.

Ngược lại (chênh lệch < 0.10):
    → GIỮ SUPABASE. Chênh lệch không đủ trả cho chi phí vận hành hệ thống thứ hai.
```

Ngưỡng này nghiêng về Supabase, và điều đó là **có chủ ý, được nêu ra trước**:
Supabase đang phục vụ production, đang chứa dữ liệu quan hệ, và box t3.micro
đang phải dùng swap. Rào cản cho việc thêm một hệ thống phải cao hơn rào cản cho
việc sửa một câu SQL. Nếu không đồng ý với độ nghiêng này thì phải phản đối
**bây giờ**, ở 5.1, không phải sau khi thấy kết quả.

### 5.2 — Đo ops thật

| Hạng mục | Cách đo |
|---|---|
| RAM Qdrant | `docker stats` trên EC2 với đủ 3 collection, đo lúc rảnh và lúc chạy bench |
| Headroom t3.micro | So với 908Mi tổng, ~630Mi đang dùng + 1.4Gi swap (memory `ec2-deployment`) |
| Free tier limit | Đọc trang giá Qdrant Cloud hiện hành, ghi giới hạn RAM/disk/cluster và điều kiện đình chỉ |
| Backup/restore | Supabase: PITR sẵn có. Qdrant free: snapshot thủ công? Thử thật một lần |
| Lock-in | Cả hai đều khóa 1024-dim bge-m3 (memory `ec2-deployment`); đổi model là re-index toàn bộ ở cả hai — **hòa**, không phải điểm phân biệt |
| Số hệ thống | Supabase-only = 1; Qdrant = 2 (vẫn cần Postgres cho dữ liệu quan hệ) |

### 5.3 — Khoảng cách chức năng: join

<!-- Updated: Validation Session 1 - giá theo cửa sổ ngày làm khoảng cách này nặng hơn nhiều -->

Đây là mục nặng hơn hẳn so với đánh giá ban đầu, sau khi Phase 1 xác minh cấu
trúc giá thật.

`match_hotels_with_rooms` lấy `lowest_price` trong một round-trip
(`supabase_search.py:211`). Nhưng giá **không** ở `rooms` — nó ở
`room_prices.price` (`database_schema.sql:92-95`), qua **hai** cấp join, và mỗi
dòng gắn với một cửa sổ `check_in_date` / `check_out_date` cùng cờ `sold_out`.

Nghĩa là: "giá thấp nhất của khách sạn X" **không phải một giá trị**. Nó là hàm
của (khách sạn, ngày đến, ngày đi, tình trạng còn phòng). Một hệ thống trip
planner tất nhiên phải hỏi theo ngày.

Hệ quả cho Qdrant:

| Cách | Chi phí thật |
|---|---|
| Denormalize giá vào payload | **Không khả thi đúng nghĩa.** Payload lưu được một giá, còn giá là ma trận theo ngày. Muốn đúng thì phải một point cho mỗi (hotel × cửa sổ ngày) — nhân bản corpus lên nhiều lần, và re-sync sau mỗi lần crawl |
| Join phía ứng dụng | Thêm một round-trip Postgres mỗi truy vấn. Có thể xóa sạch lợi thế latency của Qdrant, và filter giá lại quay về post-filter — đúng cái vấn đề benchmark đang tìm cách bỏ |
| Query `rooms_vector` riêng | Đổi ngữ nghĩa tìm kiếm, không tương đương |

Không cách nào miễn phí, và cách rẻ nhất về mặt kỹ thuật (denormalize) lại là
cách sai nhất về mặt dữ liệu.

**Điều chỉnh thẳng thắn cho số của Phase 3-4:** benchmark dùng snapshot giá đóng
băng — một ưu đãi Qdrant không có ở production. Nếu Qdrant thắng recall trong
điều kiện đóng băng nhưng thực tế phải thêm round-trip Postgres để hydrate giá
theo ngày, thì lợi thế đo được **không phản ánh hệ thống sau migrate**. Chấm
điểm mục "khả năng join" phải phản ánh điều này, không được để nó thành ghi chú
bên lề.

### 5.4 — Bảng chấm điểm

Mỗi tiêu chí chấm 0-5, nhân trọng số ở `plan.md`. Neo thang điểm để hai người
chấm ra cùng số:

| Điểm | Nghĩa |
|---|---|
| 5 | Tốt nhất có thể; không có nhược điểm đáng kể |
| 4 | Tốt; nhược điểm nhỏ, khắc phục được |
| 3 | Chấp nhận được; có đánh đổi thật |
| 2 | Yếu; cần giải pháp vòng tránh |
| 1 | Kém; ảnh hưởng người dùng thật |
| 0 | Không hỗ trợ |

Ba cột: `S-current`, `S-sql`, `Q-native`. Cột `S-current` cho thấy hiện trạng —
nó cũng là câu trả lời cho câu hỏi "nếu không làm gì thì sao?".

### 5.5 — Kết luận

Report phải trả lời đúng bốn câu, không lan man:

1. Chọn gì?
2. Con số nào dẫn tới lựa chọn đó? (trích số cụ thể, không nói chung chung)
3. Điều gì sẽ lật ngược kết luận? (ví dụ: corpus vượt 100K vector, hoặc cần
   filter geo-radius mà pgvector không làm tốt)
4. Việc gì phải làm ngay bất kể chọn gì? Ba thứ đã biết trước, Phase 4 sẽ định
   lượng mức nghiêm trọng:
   - **Fallback im lặng** (`supabase_search.py:226-228`, `:287-288`) — trả kết
     quả vi phạm ràng buộc người dùng nêu, không cảnh báo
   - **Truncation nửa sao** (`supabase_search.py:218`) — `int(star)` biến query
     "từ 4.5 sao" thành "từ 4 sao"
   - **Định nghĩa RPC không có trong version control** — Phase 1 bước 0 đã kéo
     về; giữ nó ở đó

## Related Code Files

- Create: `eval/results/vector_bench/decision-matrix.md` (5.1, commit trước Phase 3)
- Create: `eval/results/vector_bench/report.md`
- Create: `eval/results/vector_bench/charts/*.png`
- Create: `eval/vector_bench/report.py`
- Modify: `eval/results/report.md` — link sang báo cáo này ở mục Metrics

## Implementation Steps

**5.1 — chạy sau Phase 2, trước Phase 3**
1. Viết `decision-matrix.md`: 12 tiêu chí, trọng số, thang neo, cây quyết định.
2. Trình bày cây quyết định (kể cả độ nghiêng về Supabase) cho người ra quyết định
   duyệt. Phản đối phải nêu **ở đây**.
3. Commit riêng: `chore(eval): pre-register vector store decision matrix`.

**5.2-5.5 — chạy sau Phase 4**
4. Deploy Qdrant đủ 3 collection lên EC2, đo `docker stats` lúc rảnh và lúc tải.
5. Đọc trang giá Qdrant Cloud, ghi giới hạn free tier kèm ngày truy cập và URL.
6. Thử snapshot + restore Qdrant free tier một lần thật.
7. Chấm ma trận, ba cột, có ghi chú lý do từng điểm.
8. Viết `report.py` sinh biểu đồ: recall-vs-selectivity (chính), latency wall vs
   server, shortfall theo tầng.
9. Viết `report.md` trả lời bốn câu ở 5.5.
10. Đối chiếu điểm cuối với cây quyết định 5.1. Nếu lệch → điều tra tại sao,
    ghi lại; **không** sửa trọng số cho khớp mong muốn.

## Todo

- [ ] `decision-matrix.md` + duyệt + commit riêng (trước Phase 3)
- [ ] Đo RAM Qdrant trên EC2
- [ ] Ghi giới hạn free tier kèm nguồn + ngày
- [ ] Thử snapshot/restore thật
- [ ] Chấm ma trận 3 cột
- [ ] `report.py` + 3 biểu đồ
- [ ] `report.md` trả lời 4 câu
- [ ] Cập nhật `eval/results/report.md` trỏ sang
- [ ] Đối chiếu với ngưỡng 5.1

## Success Criteria

- [ ] `decision-matrix.md` commit **trước** commit đầu tiên của Phase 3 (kiểm bằng `git log`)
- [ ] Có số RAM thật của Qdrant trên t3.micro, kèm headroom còn lại
- [ ] Giới hạn free tier ghi kèm URL + ngày truy cập
- [ ] Snapshot/restore đã thử thật, không phải đọc doc rồi suy
- [ ] Ma trận đủ 12 tiêu chí × 3 cột, mỗi ô có lý do
- [ ] Tổng điểm tính đúng theo trọng số đã đăng ký
- [ ] `report.md` trả lời tách bạch cả 4 câu
- [ ] Nêu rõ điều kiện lật ngược kết luận
- [ ] Mọi lệch khỏi trọng số ban đầu đều có mục changelog kèm lý do

## Risk Assessment

| Rủi ro | Giảm thiểu |
|---|---|
| Kết quả ra "hòa", không quyết được | Cây 5.1 đã có nhánh hòa: giữ Supabase. Hòa **là** một quyết định |
| Số liệu ủng hộ Qdrant nhưng ops thì không | Chính là mục đích ma trận có trọng số; trình bày cả hai và để nguyên căng thẳng đó, đừng làm mượt |
| Sức ép chọn Qdrant vì "hiện đại hơn" | Ngưỡng đăng ký trước; mọi lệch phải ghi changelog |
| Chi phí migrate bị đánh giá thấp | 5.3 bắt buộc định lượng khoảng cách join, không được ghi "TBD" |
| Bug fallback im lặng bị chìm trong tranh luận chọn store | 5.5 câu 4 tách riêng nó ra như việc phải làm bất kể chọn gì |
| Free tier bị đình chỉ giữa lúc đo | Ghi lại nếu xảy ra — bản thân đó là dữ liệu về độ tin cậy của free tier |
