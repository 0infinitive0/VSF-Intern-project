---
phase: 9
title: "Chi tiết / Sửa khách sạn (B3)"
status: done
priority: P1
effort: "2.5d"
dependencies: [8]
---

# Phase 9: Chi tiết / Sửa khách sạn — B3

## Overview

Màn nặng nhất của nhánh Khách sạn và là nơi hai cơ chế then chốt phải hiện rõ:
**ô nào do pipeline quản lý** (sẽ bị ghi đè) và **ô nào ảnh hưởng tìm kiếm của bot**
(phải embedding lại sau khi sửa).

Theo quyết định #7 (R1 phương án iii): khách sạn `Từ pipeline` **vẫn sửa được mọi ô**,
chỉ cảnh báo. Biểu tượng khoá `🔒` trong thiết kế là **cảnh báo, không phải khoá cứng**.

**Thiết kế bám theo:** artboard `B3 · CHI TIẾT / SỬA KHÁCH SẠN — TAB CƠ BẢN
(khách sạn từ pipeline)`, biến thể `B3 · tab Tiện ích`, và
`Sau khi lưu ô ảnh hưởng tìm kiếm`.

## Bám sát thiết kế — checklist đối chiếu 1:1

**Header:** breadcrumb `Quản trị · Khách sạn · Mường Thanh Grand Đà Nẵng` ·
tên khách sạn (tiêu đề) · chip `⟳ Từ pipeline` · chip `✓ Đã embed · 24/08 06:00` ·
switch `Đang bán`.

**Tabs:** `Cơ bản` · `Vị trí` · `Tiện ích` · `Hình ảnh` · `Phòng` (badge `128`) ·
`Lân cận`.

**Banner đầu trang** (chỉ khi `Từ pipeline`, biểu tượng `🔒`, nền `--warn-soft`):
`Khách sạn này do pipeline ETL quản lý. Các ô có biểu tượng khoá sẽ bị ghi đè vào
lần chạy kế tiếp.` (xem L21 — bỏ "06:00 hằng ngày")

**Tab `Cơ bản`:**

| Ô | Khoá 🔒 | Nhãn RAG | Ghi chú |
|---|---|---|---|
| Tên khách sạn | ✓ | ✓ | |
| Loại hình | ✓ | ✓ | |
| Hạng sao | ✓ | — | |
| Mô tả | — | ✓ | có badge `đã sửa` khi thay đổi chưa lưu |
| Điểm nổi bật vị trí | — | ✓ | `location_highlight` |
| Giờ nhận phòng | — | — | |
| Giờ trả phòng | — | — | |

Tooltip trên ô khoá: `Ô này do pipeline cập nhật, sửa tay sẽ bị ghi đè ở lần chạy kế tiếp.`

**Thanh dính đáy màn hình khi có thay đổi chưa lưu:**
- Dòng 1: `Bạn có 2 thay đổi chưa lưu`
- Dòng 2: `Mô tả · Điểm nổi bật vị trí — cả hai đều ảnh hưởng tìm kiếm của bot`
- Nút `Huỷ thay đổi` · `Lưu`

Dòng 2 **liệt kê tên ô cụ thể** và nói rõ ô nào ảnh hưởng RAG — không phải câu chung chung.

**Tab `Tiện ích`:**
- Tiêu đề `Tiện ích khách sạn` + nhãn `ảnh hưởng tìm kiếm của bot` + `Đã chọn 14 / 22`
- Nhóm theo danh mục, mỗi nhóm có tên + đếm `{đã chọn}/{tổng}`
- Chip bật/tắt cao 30px, bo 999px:
  - Bật: `✓ {label}`, nền `--acc-soft`, chữ `--acc`, weight 600, viền `rgba(58,115,222,.28)`
  - Tắt: `{label}`, nền trắng, chữ `--t2`, viền `--stroke`
- Nhóm trong thiết kế: `Bể bơi & Spa` · `Ăn uống` · `Đưa đón & Di chuyển` ·
  `Tiện ích chung` · `Gia đình & Trẻ em` (xem L33)

**Hộp thoại sau khi lưu ô ảnh hưởng RAG:**
- Tiêu đề `Chạy lại embedding ngay?`
- `Bạn vừa sửa **Mô tả** và **Điểm nổi bật vị trí**. Bot vẫn dùng nội dung cũ cho tới
  khi embedding lại.`
- Hai ô: `Phạm vi — 1 khách sạn (128 phòng)` · `Thời gian ước tính — ≈ 40 giây`
- Dòng phụ: `Chỉ nhúng lại khách sạn này — không ảnh hưởng 63 khách sạn còn lại.`
- Nút `Để sau` · `Chạy ngay`

## Lệch giữa thiết kế và code — phải xử lý

| # | Thiết kế | Thực tế | Xử lý |
|---|---|---|---|
| L33 | 5 nhóm tiện ích tiếng Việt tự đặt | `amenity_catalog.category` có **14 giá trị cố định**: `accessibility, business, connectivity, facility, family, food, general, language, outdoor, policies, room_comfort, safety, transport, wellness` | Định nghĩa **một bảng ánh xạ** category → nhãn nhóm tiếng Việt trong `src/admin/lib/amenity-groups.ts`. Nhóm thiết kế map: `wellness`→Bể bơi & Spa · `food`→Ăn uống · `transport`→Đưa đón & Di chuyển · `family`→Gia đình & Trẻ em · phần còn lại gom `Tiện ích chung`. **Không** bỏ sót category nào — mọi tiện ích phải rơi vào đúng một nhóm |
| L34 | Chip `✓ Đã embed · 24/08 06:00` | `hotels` **không có** cột `embedded_at` | Bỏ mốc thời gian, chỉ hiện `✓ Đã embed` / `◔ Chưa embed` / `⚠ Thiếu phòng`. Thêm cột `embedded_at` là sửa DAG đang chạy — ngoài phạm vi |
| L35 | Biểu tượng 🔒 gợi ý "khoá không sửa được" | Quyết định #7 = vẫn sửa được | Giữ biểu tượng (nó là tín hiệu thị giác tốt) nhưng ô **không** disabled, tooltip nói đúng bản chất: *sẽ bị ghi đè*, không phải *không sửa được*. Cân nhắc đổi 🔒 thành `⟳` cho khỏi hiểu nhầm — quyết định lúc code, miễn tooltip đúng |
| L36 | `Phạm vi — 1 khách sạn (128 phòng)` trong hộp thoại re-embed | Sửa cột của `hotels` chỉ làm `hotels.embedding` cũ, **không** ảnh hưởng `rooms.embedding` | Phạm vi thật = `1 khách sạn`. Chỉ ghi thêm số phòng khi lần lưu đó cũng đụng vào phòng (không xảy ra ở B3). **Sửa copy thành `Phạm vi — 1 khách sạn`** |
| L37 | `Thời gian ước tính ≈ 40 giây` | Không có dữ liệu benchmark | Ước tính từ lịch sử: thời lượng trung bình mỗi bản ghi của các lần chạy DAG gần nhất × số bản ghi. Nếu chưa có lịch sử thì **ẩn ô này**, đừng bịa số |
| L38 | Tab `Hình ảnh`, `Lân cận` | `images TEXT[]`, `nearby_attractions`/`nearby_essentials` JSONB **cấu trúc khác nhau giữa Agoda và Booking** (ghi rõ trong schema) | Phase này làm **tab Cơ bản, Vị trí, Tiện ích**. Tab `Hình ảnh` = danh sách URL đọc/xoá/thêm URL (không upload file — chưa có object storage). Tab `Lân cận` = **chỉ đọc**, render JSON theo nguồn. Ghi rõ giới hạn trên UI |
| L39 | Tab `Phòng` badge `128` | Phase 10 | Ở phase này chỉ render tab + badge số phòng; nội dung do Phase 10 |

## Backend — hợp đồng API

```
GET /api/v1/admin/hotels/{id}
→ 200 {
    "id": "uuid",
    "name": "...", "accommodation_type": "...", "description": "...",
    "star_rating": 4,
    "address": "...", "city": "...", "area_name": "...",
    "location_highlight": "...",
    "destination_id": "uuid", "latitude": 16.06, "longitude": 108.24,
    "check_in_time": "14:00", "check_in_until": "...", "check_out_time": "12:00",
    "amenities": ["swimming_pool", "wifi"],
    "amenity_groups": {...},
    "images": ["https://..."], "image_url": "https://...",
    "nearby_attractions": {...}, "nearby_essentials": {...},
    "source_platform": "booking", "is_manual": false,
    "is_active": true,
    "room_count": 128,
    "embedding_state": "embedded",
    "pipeline_managed_fields": ["name","accommodation_type","star_rating","address",
                                "city","area_name","images","review_score","lowest_price"],
    "rag_fields": ["name","accommodation_type","area_name","address",
                   "location_highlight","description","amenities"]
  }
```

Hai mảng cuối do **backend** trả về, frontend chỉ render theo:

- `rag_fields` — copy từ `TABLE_COLUMNS["hotels"]` (Phase 8, `embedding_fields.py`).
  Một nguồn sự thật cho cả nhãn UI lẫn logic re-embed.
- `pipeline_managed_fields` — **rỗng** khi `is_manual`. Với khách sạn ETL: danh sách
  cột mà `hotel_pipeline.normalize_hotel` thật sự ghi. **Đọc `hotel_pipeline.py`
  trước khi viết danh sách này** — đoán sai thì hoặc cảnh báo thừa (admin mất lòng
  tin) hoặc thiếu (admin mất công sửa).

```
PATCH /api/v1/admin/hotels/{id}
  body: chỉ những trường đổi (partial)
→ 200 {
    "id": "uuid",
    "changed_fields": ["description", "location_highlight"],
    "rag_fields_changed": ["description", "location_highlight"],
    "embedding_cleared": true,
    "embedding_state": "missing"
  }
→ 404 | 422
```

Quy tắc ghi:

```python
changed = {k: v for k, v in body.items() if v != current[k]}
rag_changed = set(changed) & RAG_FIELDS_HOTEL
if rag_changed:
    changed["embedding"] = None        # bot sẽ học lại ở lần chạy only_null kế tiếp
```

- **Backend tự so**, không nhận cờ `should_reembed` từ client.
- `source_platform`, `source_hotel_id`, `id`, `embedding` **không** nhận từ body.
- Sửa `amenities`: chỉ nhận id có trong `amenity_catalog` và `is_approved` —
  dùng `resolve_hotel_amenity_ids` / `bind_amenities` đã có trong
  `services/amenity_catalog.py`, **không** viết lại validation.
- Audit: `action='hotel.update'`, `before`/`after` chỉ chứa cột đã đổi.

```
GET /api/v1/admin/amenities?scope=hotel
→ 200 [{"id":"swimming_pool","label_vi":"Hồ bơi","category":"wellness"}]
```

Tái dùng `all_approved_amenities()`. Endpoint `GET /hotel-amenities` công khai đã có
(`routes.py:164`) nhưng nó phục vụ app chat — kiểm xem trả đủ `category` không;
nếu đủ thì **dùng lại, không tạo endpoint mới**.

```
POST /api/v1/admin/hotels/{id}/reembed
→ 202 { "queued": true, "dag_run_id": "...", "scope": "1 khách sạn" }
→ 503 { "detail": "airflow_unavailable" }   // Phase 13 chưa xong / Airflow chết
```

Endpoint này **cần Phase 13** (Airflow client). Trước đó: `SET embedding = NULL` vẫn
chạy được (đó là phần quan trọng), phần trigger DAG trả `503` và hộp thoại hiện
`Đã đánh dấu cần nhúng lại. Chạy pipeline embedding ở mục Dữ liệu bot để bot học ngay.`
— **hộp thoại vẫn có ích khi Airflow chưa nối**, không chặn Phase 9.

## Frontend — màn hình B3

```
src/admin/pages/hotels/
  hotel-detail-page.tsx          header + tabs + thanh dính đáy
  hotel-tab-basic.tsx            dùng lại hotel-basic-fields (Phase 8)
  hotel-tab-location.tsx         dùng lại hotel-location-fields
  hotel-tab-amenities.tsx
  hotel-tab-images.tsx           L38
  hotel-tab-nearby.tsx           L38, chỉ đọc
  unsaved-bar.tsx                thanh dính đáy
  reembed-dialog.tsx
  pipeline-field-badge.tsx       🔒 + tooltip
src/admin/lib/amenity-groups.ts  L33
```

- Theo dõi thay đổi bằng cách so form state với dữ liệu gốc, **không** dùng cờ dirty
  của từng input — cần biết chính xác **tên ô nào** đã đổi để hiện ở thanh dính đáy.
- Badge `đã sửa` gắn trên nhãn ô đã thay đổi.
- Rời tab khi có thay đổi chưa lưu: giữ nguyên state (tab là view, không phải form
  riêng); rời **trang** thì chặn.
- Hộp thoại re-embed chỉ mở khi `rag_fields_changed` không rỗng, và câu
  `Bạn vừa sửa X và Y` nội suy đúng tên ô đã đổi.
- Chip nguồn / chấm embedding tái dùng component của Phase 7.

## Related Code Files

- Modify: `backend/src/api/admin/hotels.py`, `backend/src/api/admin/embedding_fields.py`
- Modify: `backend/tests/test_api/test_admin_hotels.py`
- Create: `frontend/src/admin/pages/hotels/hotel-detail-page.tsx` + 8 file con
- Create: `frontend/src/admin/lib/amenity-groups.ts`
- Modify: `frontend/src/admin/api/hotels-client.ts`, `router.tsx`
- Reference: `backend/src/services/amenity_catalog.py`, `backend/src/airflow/dags/data_pipeline/hotel_pipeline.py` (danh sách cột ETL ghi), `backend/src/airflow/dags/data_pipeline/embed_supabase_dag.py`, `frontend/src/hooks/use-hotel-amenity-catalog.ts`

## Implementation Steps

1. Đọc `hotel_pipeline.py` → liệt kê chính xác cột mà ETL ghi vào `hotels`.
   Đây là dữ liệu đầu vào cho `pipeline_managed_fields`.
2. Đọc `amenity_catalog.py` + endpoint `GET /hotel-amenities` → quyết định tái dùng
   hay thêm endpoint admin.
3. `GET`/`PATCH` + logic so cột RAG + clear embedding.
4. Test (xem dưới).
5. `amenity-groups.ts`: ánh xạ 14 category → nhóm hiển thị, có test đảm bảo không sót.
6. Dựng 3 tab chính + thanh dính đáy + hộp thoại re-embed.
7. Tab Hình ảnh, Lân cận theo giới hạn L38.

## Success Criteria

- [x] Sửa `description` → `hotels.embedding` thành NULL, `embedding_state='missing'`, hộp thoại re-embed bật lên
- [x] Sửa `star_rating` → `embedding` **giữ nguyên**, **không** có hộp thoại re-embed
- [x] Sửa `check_in_time` + `description` cùng lúc → chỉ `description` nằm trong `rag_fields_changed`
- [x] Gửi `"source_platform": "manual"` trong PATCH của khách sạn ETL → bị bỏ qua
- [x] Gửi amenity id không có trong catalog → 422, `amenities` không đổi
- [x] Khách sạn `manual` → `pipeline_managed_fields` rỗng, **không** có banner khoá, **không** có 🔒
- [x] Khách sạn ETL → banner khoá hiện, các ô có 🔒 vẫn **sửa được** (không disabled)
- [x] Thanh dính đáy liệt kê đúng tên ô đã đổi, đánh dấu ô nào ảnh hưởng RAG (đánh dấu `*` từng ô, không phải câu chung chung cho cả dòng)
- [x] Mọi tiện ích trong `amenity_catalog` rơi vào đúng một nhóm ở tab Tiện ích (test tự động — khẳng định tường minh cả 14 category, không chỉ "nằm trong danh sách nhóm")
- [x] Chip embedding **không** hiện mốc thời gian (L34)
- [x] `admin_audit_log` ghi `before`/`after` chỉ chứa cột đã đổi
- [x] Airflow chưa nối → `POST /reembed` trả 503, nhưng `embedding` vẫn đã NULL và UI hướng dẫn đúng

## Bổ sung ngoài phạm vi gốc: tải ảnh lên trực tiếp (Supabase Storage)

Sau khi Phase 9 xong, user yêu cầu bổ sung upload file thật cho tab Hình ảnh (thay vì chỉ dán URL — giới hạn L38 gốc). Đã làm:

- Bucket `hotel-images` (public, giới hạn 5MB, chỉ `image/jpeg|png|webp`) —
  `scripts/migrations/20260824_add_hotel_images_storage_bucket.sql`, đã apply lên project sống.
- `POST /api/v1/admin/hotels/{id}/images/upload` (multipart, `require_admin`) — dùng service-role client
  upload lên bucket, trả về public URL. Không tự ghi vào `hotels.images` — frontend thêm URL vào mảng cục bộ
  rồi lưu qua `PATCH /{id}` như thường (amenities-style write path, một chỗ ghi cho cả URL dán tay lẫn URL upload).
- Không cần Storage RLS: writer duy nhất là backend service-role (bypass RLS), giống mọi bảng khác trong schema.
- Frontend: `hotel-tab-images.tsx` có nút "Tải ảnh lên" (input file ẩn) cạnh ô dán URL; cả hai đường đều
  validate http(s)-only + cap 50 ảnh trước khi thêm vào mảng.
- Verify thật: upload/get_public_url/remove chạy qua Supabase Python client sống, `curl` xác nhận URL public
  trả 200 không cần auth, và một request multipart thật qua `httpx.ASGITransport` (không mock) chạy hết đường
  từ `UploadFile` → Storage → public URL.

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Quên clear `embedding` khi sửa cột RAG → bot trả kết quả cũ **âm thầm** | **Cao** | Backend tự so với `RAG_FIELDS_HOTEL`; test cho từng cột trong danh sách 7 cột |
| Clear `embedding` quá tay (mọi lần PATCH) → chạy lại DAG tốn tiền API vô ích | Cao | Chỉ clear khi giao với `RAG_FIELDS_HOTEL`; có test cho `star_rating` |
| `pipeline_managed_fields` đoán sai | Trung bình | Bước 1 đọc `hotel_pipeline.py`; nếu không chắc thì để rỗng còn hơn cảnh báo sai |
| Ánh xạ 14 category sót một cái → tiện ích biến mất khỏi UI | Trung bình | Test tự động: mọi entry trong catalog phải có nhóm |
| `amenity_groups` JSONB (cấu trúc khác nhau 2 nguồn) bị ghi đè bằng cấu trúc mới | Trung bình | Phase này **không** ghi `amenity_groups`, chỉ ghi mảng `amenities`. Ghi rõ trong code |
| Admin sửa khách sạn ETL rồi mất trắng ở lần chạy pipeline | Trung bình | Đây là hệ quả **đã chấp nhận** của quyết định #7. Banner + 🔒 + tooltip là biện pháp; audit log giữ lại giá trị đã nhập |

## Implementation Notes (post-review)

Triển khai xong + review bởi `code-reviewer` subagent (2 lượt), đã sửa các phát hiện quan trọng:

- **`destination_id` bị null ngầm khi sửa `city`**: trước đây mọi lần sửa `city` không khớp tên destination nào sẽ set `destination_id = null`, âm thầm loại khách sạn khỏi mọi tìm kiếm theo điểm đến (`match_hotels_with_rooms` lọc theo `destination_id`, không phải `city`). Giờ chỉ gửi `destination_id` khi khớp được — không bao giờ null ngầm một liên kết đang có.
- **Tiện ích so sánh theo list thay vì set**: toggle bật-rồi-tắt một chip trước đây vẫn báo "đã đổi" và clear `embedding` (tốn tiền re-embed vô ích — đúng rủi ro Cao ở bảng trên). Giờ so theo tập hợp (set), và `hotel-tab-amenities.tsx` chỉ thêm/bớt đúng 1 id khi toggle thay vì dựng lại toàn mảng theo thứ tự catalog — tránh làm rớt id cũ không còn nằm trong catalog hiện tại (196/1104 khách sạn có >100 tiện ích, id hợp lệ nhưng có thể đã đổi scope).
- **`_invalid_amenity_ids` bị cắt ở 100 id**: `query_approved_amenities` giới hạn 100 id/lần — 196 khách sạn trong DB thật có >100 tiện ích, mọi id thứ 101 trở đi bị báo "không hợp lệ" một cách sai. Đổi sang `query_all_approved_amenities_by_ids` (không giới hạn) và chỉ validate id **mới thêm**, không validate lại toàn bộ mảng mỗi lần lưu.
- **Toạ độ**: thêm validator "cả hai hoặc không cái nào" cho `UpdateHotelRequest` khi cả `latitude`/`longitude` cùng có trong body — trước đó gửi một cái `null` một cái có giá trị sẽ xoá sạch cột `coordinates`.
- **Thanh dính đáy gắn nhãn RAG sai chỗ**: trước đây thêm "— ảnh hưởng tìm kiếm của bot" vào cuối cả dòng bất cứ khi nào có ít nhất 1 ô RAG đổi, dù các ô khác cùng đổi không phải RAG. Giờ đánh dấu `*` đúng từng ô RAG-relevant.
- **State `hotel` cũ sau khi lưu**: trước đây chỉ ghi đè `embedding_state` vào state cũ, tên/mô tả mới lưu không hiện lại ở header cho tới khi tải lại trang. Giờ gọi lại `GET` sau khi lưu thành công, giữ nguyên `is_active` hiện tại (tránh việc gọi lại ghi đè một thao tác bật/tắt "Đang bán" đang chạy song song).
- **`updated_at` không tự cập nhật**: PATCH giờ set `updated_at` tường minh (không có trigger DB) để khách sạn vừa sửa không kẹt cuối danh sách B1 (sắp theo `updated_at desc`).
- **URL ảnh không kiểm định dạng**: thêm validator http(s)-only + giới hạn độ dài cho `images`, cả hai phía backend và `hotel-tab-images.tsx`.
- **Test tautology**: `EMBEDDING_FIELDS`/`PIPELINE_MANAGED_FIELDS_HOTEL` giờ có test đối chiếu trực tiếp với source thật (`embed_supabase_dag.py`, `hotel_pipeline.py`) bằng regex-parse (không import được `airflow` từ venv backend), thay vì chỉ so với chính nó. `amenity-groups.test.ts` giờ khẳng định tường minh cả 14 category thay vì chỉ kiểm tra "nằm trong danh sách nhóm" (vốn luôn đúng nhờ fallback).
- Thêm `lookupError` cho 3 API lookup phụ (destinations/accommodation-types/amenities) — trước đó lỗi tải bị nuốt im lặng.
