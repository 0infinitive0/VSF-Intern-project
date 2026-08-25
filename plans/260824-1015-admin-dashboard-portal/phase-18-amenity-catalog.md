---
phase: 18
title: "Danh mục tiện ích & tiện nghi (Amenity Catalog)"
status: pending
priority: P2
effort: "3d"
dependencies: [9, 10]
---

# Phase 18: Danh mục tiện ích & tiện nghi — view + insert

## Overview

Phase 9 (tab `Tiện ích` của B3) và Phase 10 (tab `Phòng` của B5) chỉ cho admin **chọn
từ** danh mục `amenity_catalog` đã duyệt — chip bật/tắt trên một khách sạn/phòng cụ
thể. Không màn nào cho xem **cả danh mục**, thêm một loại tiện ích/tiện nghi mới bằng
tay, hay duyệt các đề xuất do pipeline/chat tự phát hiện.

Phase này thêm **một** màn quản trị danh mục dùng chung cho cả hai phạm vi
(`scope='hotel'`/`'room'`/`'both'`): xem toàn bộ (Đã duyệt / Chờ duyệt / Đã ngừng
dùng), thêm tiện ích mới bằng **một ô nhập tự do** (AI xử lý toàn bộ phần còn lại),
duyệt/từ chối đề xuất, và ngừng dùng một mục **không còn khách sạn/phòng nào tham
chiếu**.

**Phát hiện quan trọng khi scout (2026-08-25):** `amenity_catalog` đã có sẵn 2 cột
`needs_review` và `retired_at` từ migration
`20260821_hotel_preference_catalog_redesign.sql`. `retired_at` là hạ tầng đúng cho
"Ngừng dùng" (xem G8/G11). `needs_review` (11 dòng đang `true` trên Supabase sống) là
một cờ rà soát riêng, **ngoài phạm vi phase này** theo quyết định 2026-08-25 — xem
quyết định #5. Cột vẫn tồn tại, được dọn về `false` một lần (không xây UI xử lý nó ở
đây), để lại nguyên vẹn cho một phase sau nếu cần.

**Không có artboard.** Đây là màn mới, không nằm trong 15 màn của 3 nguồn đầu vào gốc.
Dựng bằng primitive bộ `Z` (Phase 3) + tái dùng đúng mẫu bảng của B1 (Phase 7), chip
tiện ích của B3 (Phase 9) và mẫu hộp thoại xác nhận có "HẬU QUẢ" của D3 (Phase 6).

**Bản dựng hình tham khảo** (Claude Design canvas): xem link đã gửi trong hội thoại lập
kế hoạch — không phải nguồn sự thật kỹ thuật, chỉ minh hoạ luồng.

## Phát hiện khi scout

| # | Phát hiện | Hệ quả |
|---|-----------|--------|
| G1 | `bind_amenity_rows` **không bao giờ** ghi một id `is_approved=false` mới phát hiện vào `hotels.amenities`/`rooms.room_facilities` — đề xuất mới chỉ vào `proposals`, không vào `ids` được ghi | Một dòng `is_approved=false` **luôn** chưa được tham chiếu ở đâu cả → **Từ chối = xoá cứng an toàn tuyệt đối**, không cần đếm usage |
| G2 | `mcp__gitnexus__impact` trên `query_approved_amenities`/`all_approved_amenities`: **risk CRITICAL**, 7 caller trực tiếp (bot tìm kiếm + Phase 9/10 picker/update) | Bất kỳ đường ghi nào có thể làm một mục **đã duyệt và đang dùng** biến mất khỏi kết quả truy vấn đều có phạm vi ảnh hưởng lớn nhất nhánh Khách sạn |
| G3 | `id` là khoá chính **và** chính là chuỗi lưu thẳng trong `hotels.amenities`/`rooms.room_facilities` (mảng `TEXT[]`, không có FK) | `id` **bất biến** sau khi tạo, PATCH không nhận `id`. Áp dụng cả cho tạo hàng loạt — xem "Sinh id duy nhất trong một lô" bên dưới |
| G4 | `parent_id` có FK + CHECK chống tự tham chiếu, nhưng **không** chống vòng lặp nhiều cấp (A→B→C→A) ở tầng DB | Endpoint tạo/sửa phải tự đi ngược chuỗi `parent_id` (tối đa ~20 bước) để chặn vòng lặp trước khi ghi |
| G5 | `icon_key` được lưu nhưng **không** component frontend nào render nó thành icon | AI tự điền khi tạo, UI không dựng icon picker/preview |
| G6 | Không có bảng ánh xạ tiếng Việt cho **14 category thật** — `amenity-groups.ts` chỉ có 5 nhóm hiển thị đã gộp cho tab B3 | Thêm map mới `amenity-categories.ts` (14 nhãn), tách biệt với `amenity-groups.ts` |
| G7 | `GET /api/v1/admin/amenities?scope=hotel` (Phase 9) và `GET /api/v1/admin/rooms/room-facilities` (Phase 10) đọc thẳng `query_approved_amenities()` mỗi lần gọi (cache TTL 60s) | Duyệt/kích hoạt lại một tiện ích ở màn này **tự động** xuất hiện làm lựa chọn ở B3/B5 trong vòng 60 giây |
| G8 | `is_approved` **không** kiểm soát việc thẻ khách sạn ở app chat có hiện tiện ích hay không. `hotels.amenities` không bị dọn khi `is_approved` đổi; `displayAmenityLabels` (frontend) không bỏ ID thiếu nhãn — nó hiện **ID thô** (`swimming_pool`) thay vì tên đẹp | Không được lật `is_approved: true→false` cho một mục **đang có usage > 0** — ranh giới cứng cho mọi đường ghi trong phase này, kể cả retire (G11) |
| G9 | Chuyển `is_approved: false → true` (Duyệt) là hợp lệ; `true → false` qua `is_approved` thì **không** — thay vào đó dùng `retired_at`, và chỉ khi usage = 0 | Hai cơ chế cho hai câu hỏi khác nhau: *"có dùng được không"* (`is_approved`) và *"có đang được đề xuất giữ lại không"* (`retired_at`) |
| G10 | `bind_amenity_rows` đã có sẵn đúng "phễu" cho việc nhập nhiều tên cùng lúc: dedupe → khớp catalog đã duyệt (`_match_catalog_entry`, ngưỡng 0.85) → LLM classification theo lô cho phần còn lại | Luồng "+ Thêm tiện ích" **tái dùng** đúng phễu này thay vì viết lại |
| G11 | **`needs_review`/`retired_at` đã tồn tại trên `amenity_catalog`** (migration `20260821_hotel_preference_catalog_redesign.sql`; xác nhận sống trên Supabase `V_OTA`: 453 dòng, 11 đang `needs_review=true`, 0 đang `retired_at` khác null, 0 đang `is_approved=false`). Unique index `on (scope, lower(btrim(label_vi))) where is_approved and retired_at is null` xác nhận `retired_at` được thiết kế để **giải phóng nhãn cho một mục thay thế**, không phải xoá. **`_query_approved_amenities`/`all_approved_amenities` hiện không lọc theo `retired_at` ở đâu cả** | Set `retired_at` hôm nay **chưa có tác dụng gì** tới bot/picker — phase này **bắt buộc** sửa `_query_approved_amenities` lọc thêm `retired_at IS NULL`, nếu không nút "Ngừng dùng" là giả |
| G12 | Guard "Ngừng dùng" (G3/G8/G9) chỉ tính usage qua `admin_amenity_usage` (`hotels.amenities`/`rooms.room_facilities`) — **không tính con của chính nó trong `amenity_catalog`**. `_coverage_with_descendants`/`expand_amenity_descendants` (`amenity_catalog.py`) cho một tiện ích cha "thừa hưởng" độ phủ từ các con — `parking` có thể `hotel_count=0` **trực tiếp** trong khi `free_parking`/`on_site_parking`/`paid_parking`... (con thật, seed sẵn ở migration Aug 21) thì có | Ngừng dùng một tiện ích cha đang có con **đã duyệt, chưa ngừng dùng** trỏ `parent_id` vào nó sẽ để lại tham chiếu treo lơ lửng — con vẫn sống nhưng cha biến mất khỏi `all_approved_amenities()` sau khi sửa filter `retired_at` (G11). Guard "Ngừng dùng" phải đếm **cả** usage trực tiếp **lẫn** số con còn sống (`is_approved=true AND retired_at IS NULL AND parent_id = id`), chặn khi 1 trong 2 > 0 |

## Quyết định thiết kế

| # | Vấn đề | Quyết định | Lý do |
|---|--------|-----------|-------|
| 1 | Một màn hay hai màn (hotel/room riêng)? | **Một** màn, hai tab theo `scope` | Cùng một bảng, cùng thao tác |
| 2 | Mục `scope='both'` hiện ở đâu? | Ở **cả hai tab**, kèm badge `Dùng chung` | Đúng ngữ nghĩa cột `scope` |
| 3 | **"Ngừng dùng" có tồn tại không, và nó làm gì?** | **Có**, nhưng **chỉ bật được khi `hotel_count + room_count = 0` VÀ `child_count = 0`** (G12 — không còn tiện ích con nào đang sống trỏ `parent_id` vào nó). Ghi `retired_at = now()`, **không đụng `is_approved`**. Đảo ngược được ("Bật lại" → `retired_at = null`) | Hạ tầng `retired_at` đã có sẵn cho đúng use-case hẹp này; an toàn vì G8 không áp dụng được khi usage=0. `child_count` là điều kiện thứ hai bắt buộc — bỏ qua nó sẽ để con trỏ vào một cha đã "biến mất" |
| 4 | Xoá cứng khi nào? | **Chỉ** khi `is_approved=false` — xem G1 | Một dòng chưa duyệt chưa từng được tham chiếu |
| 5 | **`needs_review` có làm gì trong phase này không?** | **Không.** Ngoài phạm vi (quyết định 2026-08-25). Cột **giữ nguyên trong schema**, nhưng phase này **dọn một lần** toàn bộ 11 dòng đang `true` về `false` (một câu `UPDATE`, không phải tính năng), và **không** hiện nó ở đâu trên UI. Không có filter "Cần rà soát", không có nút "Bỏ đánh dấu" | Thu hẹp phạm vi có chủ đích — cờ rà soát catalog là một quyết định vận hành riêng (giữ hay xoá một tiện ích long-tail), khác với vòng đời duyệt/ngừng dùng mà phase này giải quyết. Để cột ở trạng thái `false` sạch sẽ, không để nợ "11 dòng treo lơ lửng, không ai thấy" tiếp tục âm thầm tồn tại |
| 6 | Admin nhập gì để tạo tiện ích mới? | **Một ô nhập tự do duy nhất.** Gõ tên tiếng Việt hoặc tiếng Anh, một hoặc nhiều tên cùng lúc (cách nhau bằng dấu phẩy/xuống dòng) | Admin không cần biết 14 category hay cách phân `scope` |
| 7 | Backend xử lý danh sách tên đó thế nào? | Tách tên rời rạc → chấm điểm giống catalog đã duyệt theo 3 mức (`_catalog_match_score`, G10): ≥0.85 "đã có sẵn" (luôn bỏ qua) · 0.55–0.85 "nghi trùng" (admin **tự chọn từng tên** — xem quyết định #8) · <0.55 "mới" (AI classification) | Tái dùng ngưỡng đã có; AI classification chỉ chạy cho tên thật sự mới hoặc tên admin xác nhận muốn tạo dù nghi trùng |
| 8 | **Tên bị nghi trùng thì hỏi admin như thế nào?** | **Chọn từng tên (pick-and-choose), không phải một quyết định chung cho cả lô.** Mỗi tên nghi trùng hiện kèm mục gần giống nhất, có công tắc riêng "Tạo mới" / "Bỏ qua (giữ mục đã có)", mặc định **Bỏ qua**. Không có 409 chặn — mọi tên đã có quyết định rõ ràng trước khi gửi | Nhập 5 tên mà 2 tên nghi trùng không nên buộc admin xử lý cả 2 giống hệt nhau — "Xông hơi khô" và "Xông hơi ướt" cùng nghi trùng "Xông hơi" nhưng admin có thể muốn giữ một, tạo mới một |
| 9 | Tạo mới có duyệt luôn không? | **Không.** Ghi `is_approved=false` ngay, AI điền `scope`/`category`/`icon_key`/`match_keywords`/`parent_id`, admin xem/sửa rồi Duyệt hoặc Từ chối — **cùng một hàng đợi** với đề xuất chat/pipeline | Không có luồng ẩn riêng cho admin |
| 10 | Category có 14 hay 5 lựa chọn? | **14** — đúng enum thật ở DB | Sửa nhầm thành 1 trong 5 nhãn gộp sẽ ghi sai dữ liệu |
| 11 | Click "Từ chối" thì điều gì xảy ra? | **Xoá cứng ngay, không xác nhận, không hoàn tác** | G1 — một dòng chưa duyệt chưa từng được tham chiếu ở đâu |

## Ba trạng thái thật

Bảng chính lọc/hiển thị theo đúng 3 giá trị suy ra từ 2 cột thật (`needs_review` không
tham gia — quyết định #5), **loại trừ lẫn nhau**:

```
is_approved=false                        → "Chờ duyệt"      (badge sidebar)
is_approved=true, retired_at IS NOT NULL → "Đã ngừng dùng"
is_approved=true, retired_at IS NULL     → "Đã duyệt"        (trạng thái bình thường)
```

## Sinh id duy nhất trong một lô

`_unique_canonical_id(label_en, used_ids)` đã nhận sẵn tham số `used_ids` — khi tạo
nhiều tên cùng lúc, `used_ids` phải được **cộng dồn qua cả catalog hiện có lẫn từng id
vừa sinh trong cùng lô**, không chỉ kiểm tra DB sau mỗi lần ghi riêng lẻ. Ví dụ: "Xông
hơi khô" và "Xông hơi ướt" trong cùng một lần submit đều rút gọn về gốc `xong_hoi` —
nếu không cộng dồn `used_ids` trong bộ nhớ, cả hai request `INSERT` sẽ cùng nhắm tới
`xong_hoi`, một cái thắng, một cái vi phạm khoá chính. Xử lý tuần tự trong một transaction,
cập nhật `used_ids` ngay sau mỗi id được chọn — **trước khi** xử lý tên tiếp theo trong
lô, kể cả khi ghi DB theo lô ở cuối.

## Luồng "+ Thêm tiện ích" (3 bước, hỗ trợ nhiều tên một lượt)

```
Bước 1 — Một ô nhập
  "Nhập tên tiện ích — tiếng Việt hoặc tiếng Anh, một hoặc nhiều,
   cách nhau bằng dấu phẩy hoặc xuống dòng"
  → [Tiếp tục] (disabled nếu rỗng)

Bước 1.5 — Chọn từng tên nghi trùng (chỉ hiện khi có tên rơi vào mức 0.55–0.85)
  "Phòng gym 24/7" — giống "Phòng gym" (~78%)     [•Bỏ qua] [ Tạo mới ]
  "Xông hơi ướt"   — giống "Xông hơi" (~68%)       [ Bỏ qua] [•Tạo mới]
  → [Tiếp tục]  — gửi tên "Bỏ qua" trong `skip`, tên "Tạo mới" trong `acknowledge`

Bước 2 — Danh sách bản nháp AI đã điền, admin duyệt
  [Duyệt tất cả (N)]
  ▸ mỗi thẻ: tên/nhóm/phạm vi tóm tắt + [Sửa các trường] [Từ chối] [Duyệt]
```

Mọi dòng nháp được **ghi ngay** khi qua AI classification — đóng trình duyệt giữa
chừng thì vẫn nằm trong "Chờ duyệt" ở bảng chính.

## Backend — tầng dữ liệu

```sql
CREATE VIEW admin_amenity_usage AS
SELECT amenity_id,
       count(*) FILTER (WHERE src = 'hotel') AS hotel_count,
       count(*) FILTER (WHERE src = 'room')  AS room_count
FROM (
  SELECT unnest(amenities)       AS amenity_id, 'hotel' AS src FROM hotels
  UNION ALL
  SELECT unnest(room_facilities) AS amenity_id, 'room'  AS src FROM rooms
) u
GROUP BY amenity_id;

REVOKE ALL ON admin_amenity_usage FROM anon, authenticated, PUBLIC;
GRANT  SELECT ON admin_amenity_usage TO service_role;

-- One-time cleanup — needs_review is out of scope for this phase (decision #5);
-- leave the column in place but don't let stale flags from the 2026-08-21 backfill
-- sit unactioned indefinitely with no UI to see or clear them.
UPDATE amenity_catalog SET needs_review = false WHERE needs_review;
```

**Bắt buộc sửa `backend/src/services/amenity_catalog.py`** (code, không phải
migration): `_query_approved_amenities` thêm `.is_("retired_at", "null")` cạnh
`.eq("is_approved", True)` — nếu không làm bước này, `retired_at` vẫn chỉ là cột chết,
nút "Ngừng dùng" không đổi hành vi bot thật (G11). Sửa cả hai nhánh field-set
(`_CATALOG_FIELDS` và `_LEGACY_CATALOG_FIELDS`) — đây là thay đổi **chung** cho mọi
caller của `all_approved_amenities()`/`query_approved_amenities()` (bot search, Phase
9/10 picker), không phải riêng Phase 18.

## Backend — hợp đồng API

File mới `backend/src/api/admin/amenity_catalog.py`, prefix `/amenity-catalog`.

```
GET /api/v1/admin/amenity-catalog
  ?scope=hotel|room|all&status=approved|pending|retired|all
  &category=<1 trong 14>|all&q=...&page=1&page_size=25
→ 200 {
    "items": [{ "id":"swimming_pool","label_vi":"Hồ bơi","label_en":"Swimming pool",
      "scope":"hotel","category":"wellness","icon_key":"pool","match_keywords":[...],
      "parent_id":null,"is_approved":true,"retired_at":null,
      "hotel_count":812,"room_count":0,"child_count":0,"updated_at":"..." }],
    "total": 191, "page": 1, "page_size": 25,
    "pending_count": 0
  }
```

`status` map thẳng theo "Ba trạng thái thật" ở trên — tính ở backend, một quy tắc duy
nhất. `needs_review` **không** xuất hiện trong response — ngoài phạm vi (quyết định #5).

**Kiểm trùng & sinh nháp theo lô, chọn từng tên:**

```
POST /api/v1/admin/amenity-catalog/check-duplicate
  body: { "text": "Xông hơi khô, Xông hơi ướt, Phòng gym 24/7", "scope": "hotel" }
→ 200 {
    "parsed": [...],
    "exact": [],
    "flagged": [
      { "name": "Xông hơi khô", "closest": {"id":"sauna","label_vi":"Xông hơi"}, "score": 0.71 },
      { "name": "Xông hơi ướt", "closest": {"id":"sauna","label_vi":"Xông hơi"}, "score": 0.68 },
      { "name": "Phòng gym 24/7", "closest": {"id":"gym","label_vi":"Phòng gym"}, "score": 0.78 }
    ],
    "clear": []
  }
```

```
POST /api/v1/admin/amenity-catalog/draft
  body: {
    "names": ["Xông hơi khô", "Xông hơi ướt", "Phòng gym 24/7"],
    "scope": "hotel",
    "acknowledge": ["Xông hơi ướt"]     // tên trong `flagged` mà admin chọn "Tạo mới"
  }
→ 201 {
    "items": [ {...,"is_approved":false} ],      // chỉ "Xông hơi ướt" ở ví dụ này
    "skipped_exact": [],
    "skipped_duplicate": ["Xông hơi khô", "Phòng gym 24/7"]   // flagged nhưng không có trong acknowledge — bỏ qua êm, không lỗi
  }
```

- Server **tự chấm điểm lại** theo đúng logic `check-duplicate` (không tin `acknowledge`
  từ client là danh sách đúng) — tên nào rơi vào `exact` luôn bị loại dù có mặt trong
  `acknowledge` hay không.
- **Không còn 409** cho luồng này — mọi tên nghi trùng đã có quyết định rõ ràng
  (`acknowledge` hoặc mặc định bỏ qua) trước khi gọi endpoint, nên không có gì để chặn;
  `skipped_duplicate`/`skipped_exact` báo lại minh bạch tên nào không được tạo và vì sao.
- Tên qua được (mới hoàn toàn, hoặc trong `flagged` mà có `acknowledge`): gọi
  `_approved_discovery_rows`-style theo lô (mở rộng thêm `parent_id` ở JSON schema đầu
  ra — response-only, không đổi input schema hiện có của discovery chat/pipeline).
  Model nhận tên tiếng Việt hoặc tiếng Anh, luôn trả về cả hai ngôn ngữ.
- `id` mỗi dòng sinh theo `_unique_canonical_id`, `used_ids` cộng dồn trong lô (xem mục
  "Sinh id duy nhất trong một lô").

**Sửa, duyệt hàng loạt, từ chối, ngừng dùng:**

```
PATCH /api/v1/admin/amenity-catalog/{id}
  body: chỉ trường đổi trong {label_vi, label_en, category, icon_key, match_keywords, parent_id, scope}
→ 200 { ...dòng sau sửa..., "changed_fields": [...] }

POST /api/v1/admin/amenity-catalog/{id}/approve      → 200 { "id":"...", "is_approved": true }
POST /api/v1/admin/amenity-catalog/bulk-approve
  body: { "ids": [...] } → 200 { "approved": N }

DELETE /api/v1/admin/amenity-catalog/{id}
→ 204
→ 409 { "detail": "amenity_approved_use_retire_instead" }   khi is_approved = true

PATCH /api/v1/admin/amenity-catalog/{id}/retire
→ 200 { "id": "...", "retired_at": "2026-08-25T10:00:00Z" }
→ 409 { "detail": "amenity_in_use", "hotel_count": 3, "room_count": 1, "child_count": 0 }
→ 409 { "detail": "amenity_has_active_children", "hotel_count": 0, "room_count": 0, "child_count": 4,
        "children": [{"id":"free_parking","label_vi":"Bãi đỗ xe miễn phí"}, ...] }   // tối đa 5, xem G12

POST /api/v1/admin/amenity-catalog/{id}/reactivate
→ 200 { "id": "...", "retired_at": null }
```

`id`, `is_approved`, `retired_at` **không** nhận qua `PATCH` thường — chỉ đổi qua
endpoint hành động riêng. `retire` chặn khi `hotel_count > 0 || room_count > 0`
**hoặc** `child_count > 0` — hai lý do chặn riêng biệt, trả `detail` khác nhau để UI
hiện đúng lý do (G12: usage trực tiếp vs còn tiện ích con sống). Truy vấn `child_count`:
`SELECT id, label_vi FROM amenity_catalog WHERE parent_id = :id AND is_approved AND retired_at IS NULL LIMIT 5`
(cùng transaction với check usage, không phải hai request riêng). `reactivate` không
cần điều kiện (không có usage/con để mất — đã 0 lúc retire, và retire không cascade
xuống con nên con không thể bị ảnh hưởng bởi việc cha `reactivate` lại).

Mọi endpoint ghi gọi `clear_all_approved_amenities_cache()`. Audit:
`action='amenity.draft'|'amenity.update'|'amenity.approve'|'amenity.delete'|'amenity.retire'|'amenity.reactivate'`.

## Frontend — màn hình

```
src/admin/pages/amenities/
  amenity-catalog-page.tsx     header + 2 tab (Khách sạn/Phòng) + toolbar + bảng
  amenity-toolbar.tsx          tìm · lọc category (14) · lọc trạng thái (3 + Tất cả)
  amenity-table.tsx            cột: Tên · Nhóm · Phạm vi · Dùng ở · Trạng thái · Thao tác
                                — dựng trên `DataTable` (`src/admin/ui/data-table.tsx`),
                                đúng component B1's `hotels-table.tsx` đã dùng — resize
                                và sort có sẵn trong primitive, không viết lại. Chỉ cột
                                `Thao tác` bỏ `sortValue` (không có ý nghĩa để sắp xếp)
  add-amenity-textbox.tsx      Bước 1 — 1 ô nhập nhiều tên
  duplicate-pick-list.tsx      Bước 1.5 — công tắc Bỏ qua/Tạo mới cho từng tên nghi trùng
  amenity-draft-review-list.tsx Bước 2 — danh sách thẻ nháp + Duyệt tất cả
  amenity-draft-card.tsx       1 thẻ nháp, mở rộng ra form đầy đủ
  retire-blocked-dialog.tsx    409 khi bấm Ngừng dùng nhưng usage vừa >0 (race an toàn)
  amenity-pending-badge.tsx    badge chờ duyệt — sidebar
src/admin/lib/amenity-categories.ts   14 nhãn tiếng Việt, có test coverage
src/admin/api/amenity-catalog-client.ts
```

- Bảng: mỗi cột resize được (kéo viền phải) và sort được (click tiêu đề) — có sẵn từ
  `DataTable`, chỉ cần khai đúng `sortValue` mỗi cột: Tên → `label_vi`, Nhóm → nhãn
  category đã dịch, Phạm vi → `scope`, Dùng ở → `hotel_count + room_count`, Trạng thái →
  thứ tự ưu tiên cố định (Chờ duyệt trước Đã duyệt trước Đã ngừng dùng). Cột Thao tác
  không có `sortValue` (không có ý nghĩa để sắp xếp).
- Sidebar: mục `Danh mục tiện ích` trong nhóm `KHÁCH SẠN`, badge = `pending_count`.
- Cột Thao tác theo đúng "Ba trạng thái thật":
  - **Chờ duyệt**: `Duyệt` · `Từ chối`
  - **Đã duyệt**: `Sửa` · `Ngừng dùng` (disabled + tooltip khi usage>0 — đa số trường hợp thật)
  - **Đã ngừng dùng**: `Bật lại`
- Nút `Ngừng dùng` disable **trước khi gọi API** dựa theo `hotel_count`/`room_count`
  **và** `child_count` đã có trong response `GET` — 409 vẫn giữ làm lớp bảo vệ thứ hai
  cho race condition. Tooltip phân biệt lý do: "Đang dùng ở N khách sạn/phòng" khi
  usage>0, "Còn N tiện ích con" khi chỉ `child_count`>0 (G12) — không gộp thành một câu
  chung chung, admin cần biết phải xử lý cái nào trước.
- Bước 1.5: mỗi tên nghi trùng có công tắc hai trạng thái riêng, mặc định **Bỏ qua**
  (an toàn hơn — không tạo trùng nếu admin không chủ động chọn). Nút `Tiếp tục` luôn
  bật (không có gì phải xác nhận thêm ở cấp lô).
- `match_keywords`: chip, thêm bằng Enter, giới hạn 8 từ khoá/≤80 ký tự.

## Related Code Files

- Create: `backend/scripts/migrations/20260825_add_admin_amenity_usage_view.sql` (kèm
  `UPDATE amenity_catalog SET needs_review = false WHERE needs_review`)
- Create: `backend/src/api/admin/amenity_catalog.py`
- Create: `backend/tests/test_api/test_admin_amenity_catalog.py`
- Create: `frontend/src/admin/pages/amenities/**`, `frontend/src/admin/api/amenity-catalog-client.ts`
- Reuse as-is (already implemented, matches this phase's needs exactly — do not duplicate):
  `frontend/src/admin/lib/amenity-categories.ts` (`AMENITY_CATEGORY_LABELS`, `AMENITY_CATEGORY_ORDER`,
  `categoryLabel`) — `amenity-groups.ts`'s 5-group collapse has since been fully retired repo-wide
  (Phase 9's B3 tab now also shows all 14 real categories directly), so G6 is already resolved
- Modify: `backend/src/api/admin/__init__.py` (mount router)
- **Modify (bắt buộc):** `backend/src/services/amenity_catalog.py` — (1)
  `_query_approved_amenities` lọc thêm `retired_at IS NULL` (cả 2 nhánh field-set), (2)
  mở rộng `_approved_discovery_rows`'s JSON schema/prompt sinh thêm `parent_id`, (3)
  `_unique_canonical_id` batch call site cộng dồn `used_ids` trong lô
- Modify: `backend/tests/test_amenity_catalog.py` — test hồi quy cho filter `retired_at`
- Modify: `frontend/src/admin/router.tsx`, `frontend/src/admin/layout/sidebar.tsx`
- Modify: `frontend/src/types/wire.generated.ts` (regenerate via `npm run openapi:check`)
- Reference: `backend/src/services/amenity_catalog.py` (`_unique_canonical_id`,
  `_catalog_match_score`, `_approved_discovery_rows`, `bind_amenity_rows`,
  `clear_all_approved_amenities_cache`, `AMENITY_CATEGORIES`),
  `backend/scripts/migrations/20260821_hotel_preference_catalog_redesign.sql` (nguồn
  của `needs_review`/`retired_at`/unique index), `plans/.../phase-06-order-actions.md`
  (mẫu hộp thoại "HẬU QUẢ"), `frontend/src/admin/ui/data-table.tsx` +
  `frontend/src/admin/pages/hotels/hotels-table.tsx` (mẫu `DataTable` resize/sort đã
  dùng ở B1 — tái dùng nguyên component, không viết bảng riêng)

## Sở hữu file

Nhánh mới, độc lập với "Khách sạn"/"Đơn hàng"/"Pipeline": sở hữu
`backend/src/api/admin/amenity_catalog.py`, `frontend/src/admin/pages/amenities/**`,
`frontend/src/admin/api/amenity-catalog-client.ts`. **Sửa chung** một hàm trong
`backend/src/services/amenity_catalog.py` dùng bởi chat — báo trước, chạy
`pytest backend/tests/test_amenity_catalog.py backend/tests/test_respond.py` trước khi
merge để chắc không hồi quy chat.

## Implementation Steps

1. Migration `admin_amenity_usage` view + dọn `needs_review` về `false` một lần.
2. **Sửa `_query_approved_amenities` lọc `retired_at IS NULL` trước tiên** — chạy toàn
   bộ `pytest backend/tests` ngay sau bước này.
3. `amenity_catalog.py` (API): `GET` list + 3-trạng-thái filter + `pending_count`.
4. `check-duplicate` — tách tên, chấm điểm 3 mức.
5. `draft` — nhận `names`/`acknowledge`; test `acknowledge` một phần của `flagged` chỉ
   tạo đúng tên đó, tên còn lại vào `skipped_duplicate`; mở rộng `_approved_discovery_rows`
   thêm `parent_id`; test `used_ids` cộng dồn trong lô không sinh trùng id (2 tên cùng
   gốc slug trong 1 request).
6. `PATCH`/`approve`/`bulk-approve`/`delete`/`retire`/`reactivate` — test 409 của
   `retire` khi usage>0 (`amenity_in_use`) **và** khi `child_count>0` (`amenity_has_active_children`,
   G12 — cha usage=0 nhưng có con sống), test `delete` một mục đã duyệt luôn 409.
7. Xác nhận mọi endpoint ghi gọi `clear_all_approved_amenities_cache()`.
8. `amenity-categories.ts` — 14 nhãn, test coverage.
9. Dựng màn: 2 tab, bảng 3-trạng-thái, toolbar, Bước 1 → 1.5 (chọn từng tên) → 2 (thẻ
   nháp + duyệt hàng loạt), badge chờ duyệt.
10. `npm run openapi:check`.

## Success Criteria

- [ ] `UPDATE ... SET needs_review = false` chạy xong → `SELECT count(*) FROM amenity_catalog WHERE needs_review` = 0
- [ ] Sau khi sửa filter: một tiện ích có `retired_at` khác null **không còn** xuất
      hiện trong `all_approved_amenities()` — test gọi thẳng hàm, không qua API
- [ ] Ngừng dùng một mục `hotel_count=0, room_count=0` → 200, `retired_at` được set,
      biến mất khỏi picker B3/B5 trong lượt gọi tiếp theo
- [ ] Ngừng dùng một mục có `hotel_count=3` → 409 `amenity_in_use`, `retired_at` **vẫn null**
- [ ] Ngừng dùng một mục `hotel_count=0, room_count=0` nhưng có 1 con `is_approved=true, retired_at=null` trỏ `parent_id` vào nó → 409 `amenity_has_active_children` (G12), `retired_at` **vẫn null**
- [ ] Ngừng dùng con đó trước (usage=0, không có con riêng) → 200; sau đó ngừng dùng lại cha → 200 (child_count giờ = 0)
- [ ] Bật lại một mục đã ngừng dùng → `retired_at=null`, xuất hiện lại ở picker
- [ ] Nhập 2 tên cùng gốc slug (vd. "Xông hơi khô"/"Xông hơi ướt" → cùng rút gọn
      `xong_hoi`) trong 1 lần `/draft` → 2 `id` khác nhau (`xong_hoi`, `xong_hoi_2`),
      không lỗi khoá trùng
- [ ] `check-duplicate` trả 2 tên cùng nghi trùng 1 mục gốc; `/draft` với `acknowledge`
      chỉ chứa 1 trong 2 tên → chỉ tên đó được tạo, tên kia nằm trong `skipped_duplicate`,
      **không lỗi, không 409**
- [ ] Bấm "Từ chối" trên thẻ nháp → xoá cứng ngay, không hộp thoại xác nhận
- [ ] Gửi `id`/`is_approved`/`retired_at` trong body `PATCH` thường → tất cả bị bỏ qua
- [ ] `DELETE` một mục `is_approved=true` → luôn 409
- [ ] `parent_id` tạo vòng lặp → 422, không ghi
- [ ] `amenity-categories.ts` có đủ 14 category, test tự động khẳng định tường minh
- [ ] `admin_audit_log` có dòng riêng cho mỗi thao tác (draft/update/approve/delete/retire/reactivate)
- [ ] `pytest backend/tests/test_amenity_catalog.py backend/tests/test_respond.py` xanh
      sau khi sửa filter `retired_at` — không hồi quy chat

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| **Sửa `_query_approved_amenities` thêm filter `retired_at` nhưng quên 1 trong 2 nhánh field-set → "Ngừng dùng" trông như hoạt động ở UI nhưng bot vẫn phục vụ mục đã ngừng dùng** | **Cao nhất** — lỗi im lặng | Test gọi thẳng `all_approved_amenities()`/`query_approved_amenities()`, không chỉ qua HTTP; sửa cả 2 nhánh cùng lúc |
| Ngừng dùng một mục đang dùng (usage>0) → G8's raw-ID-leak nếu guard bị bỏ qua | Cao (2 lớp chặn) | Disable nút phía client theo response `GET`; 409 phía server theo `admin_amenity_usage` |
| Ngừng dùng một tiện ích cha đang có con sống trỏ `parent_id` vào nó (G12) — guard chỉ nhìn `admin_amenity_usage` sẽ bỏ lọt vì cha có thể `hotel_count=0` trực tiếp | Trung bình–Cao | `retire` đếm thêm `child_count` (self-join `amenity_catalog`) trong cùng lượt kiểm tra, không phải bước riêng dễ quên; test riêng cho trường hợp cha `hotel_count=0` nhưng có con |
| Hai tên khác nhau trong cùng 1 lô rút gọn về cùng slug → lỗi khoá trùng hoặc mất một tên âm thầm | Trung bình–Cao | `used_ids` cộng dồn trong bộ nhớ suốt vòng lặp xử lý lô, không kiểm tra rời rạc từng tên |
| Mở rộng `_approved_discovery_rows` thêm `parent_id` làm hỏng đường discovery của chat/pipeline | Cao nếu không cẩn thận | Field mới chỉ ở JSON **response**, không đổi input; test hồi quy `bind_amenity_rows` phải xanh nguyên |
| Bỏ `needs_review` khỏi phạm vi làm 11 dòng "biến mất" khỏi tầm nhìn admin lần nữa (khác với "được dọn") | Thấp — chấp nhận có chủ đích (quyết định #5) | Dọn về `false` là xoá nợ dữ liệu cũ, không phải che giấu; cột vẫn còn, một phase sau có thể xây lại tính năng rà soát nếu cần, không mất thông tin cấu trúc (chỉ mất 11 giá trị cờ cụ thể) |
| Tách `text` nhiều tên bằng dấu phẩy/xuống dòng cắt sai một tên tự nhiên có dấu phẩy | Thấp–Trung bình | Bước 2 luôn cho xem/sửa trước khi duyệt |
| `parent_id` tạo vòng lặp nhiều cấp | Trung bình | Endpoint tự đi ngược chuỗi cha trước khi ghi |
| Đổi `id` sau khi tạo làm mồ côi tham chiếu | Cao | `id` không nhận qua PATCH |
