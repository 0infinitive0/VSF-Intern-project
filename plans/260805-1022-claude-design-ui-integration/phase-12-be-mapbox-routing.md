---
phase: 12
title: "[BE] Chuyển OSRM → Mapbox Directions"
status: pending
priority: P1
effort: "1-1.5 ngày"
dependencies: [1]
track: backend
---

# Phase 12: [BE] Chuyển OSRM → Mapbox Directions

## Tổng quan

Thay OSRM public demo server bằng Mapbox Directions API v5 trong `routing.py`.

Đây là phase **chạy song song với Phase 2**, không phụ thuộc nhau: Phase 2 chuyển route từ
item sang payload (không quan tâm ai tạo ra route), Phase 12 đổi thứ tạo ra route. Cả hai
chỉ cần xong trước Phase 11.

Lợi ích không phải chỉ là đổi nhà cung cấp — nó **gỡ được hai mục** trong bảng "Phần chưa
làm" mà trước đây tưởng là bất khả:

| Trước (OSRM) | Sau (Mapbox) |
|---|---|
| `duration × 2.5` — hệ số bịa, không nguồn gốc | `driving-traffic` cho thời lượng có traffic thật → **xoá hệ số** |
| Chỉ profile `/driving` hardcode | `driving-traffic` / `walking` / `cycling` → **nhãn phương tiện thật** |
| Demo server, không SLA, `http://` | 300 req/phút, có SLA, `https://` |

## Yêu cầu

**Chức năng**
- `OSRMClient` được thay bằng client Mapbox, giữ nguyên chữ ký hàm public
- Chọn profile theo luật khoảng cách rõ ràng (xem Kiến trúc)
- `route_to_next` mang thêm `profile` — nhãn phương tiện hiển thị phải khớp profile đã gọi
- **Xoá hệ số `× 2.5`** — trả thẳng `duration` của Mapbox
- Token đọc từ env/settings, **chỉ dùng phía server**, không bao giờ lọt vào payload

**Phi chức năng**
- Vẫn **một request mỗi chặng** — không tăng số lời gọi so với hiện tại
- `lru_cache` giữ nguyên nhưng **key phải gồm cả profile**
- Thiếu token → log cảnh báo rõ ràng, trả `None` (frontend vẽ đường thẳng), **không crash**
- Phân biệt được các lỗi 401 / 422 / 429 trong log

## Kiến trúc

### Vì sao migration này nhỏ

Mapbox là tác giả gốc của OSRM, nên Directions v5 gần như tương thích shape với OSRM v5:

```
OSRM:    http://router.project-osrm.org/route/v1/driving/{lon},{lat};{lon},{lat}?overview=full
Mapbox:  https://api.mapbox.com/directions/v5/mapbox/{profile}/{lon},{lat};{lon},{lat}?overview=full&access_token=…
```

- Thứ tự toạ độ **lon,lat** — giống hệt, không cần đổi
- `geometries` mặc định là **polyline precision 5** — giống OSRM, nên hàm `decodePolyline`
  port ở Phase 10 dùng được **nguyên không sửa**
- Response: `code == "Ok"`, `routes[0].distance` (mét), `routes[0].duration` (giây),
  `routes[0].geometry` — **cùng đường parse**

Phần thân hàm `get_route_info` gần như không đổi. Thay đổi thực chất chỉ là URL, token,
profile, và bỏ hệ số 2.5.

### Luật chọn profile

Mapbox không tự biết chặng nào nên đi bộ. Dùng **haversine làm bộ lọc cục bộ miễn phí**
trước khi gọi API, nên vẫn chỉ **một request mỗi chặng**:

```python
WALKING_THRESHOLD_KM = 1.2

def _pick_profile(origin, dest) -> str:
    """Chọn profile theo khoảng cách đường chim bay.

    Ngưỡng 1.2km ~ 15 phút đi bộ — quãng mà người đi du lịch thường đi bộ thay vì
    bắt xe. Đây là luật sản phẩm, không phải dữ liệu: nó quyết định HỎI Mapbox cái gì.
    Nhãn hiển thị luôn khớp profile đã gọi, nên con số trả về vẫn là thật.
    """
    if _haversine_km(origin, dest) < WALKING_THRESHOLD_KM:
        return "walking"
    return "driving-traffic"
```

**Điểm mấu chốt về tính trung thực**: luật này chỉ chọn *hỏi Mapbox câu gì*. Khi đã gọi
profile `walking`, thì `distance_km`/`duration_mins` trả về **là tuyến đi bộ thật với thời
gian đi bộ thật**, và nhãn "đi bộ" là đúng. Không có chỗ nào suy đoán ra con số.

Ngưỡng 1.2km phải là hằng số có tên, có comment giải thích, để sau này chỉnh được ở một chỗ.

`_haversine_km` cần thiết cho luật này — viết trong `routing.py`, đây là lần đầu backend
cần nó.

### Thay đổi shape của `route_to_next`

```python
{
    "distance_km": 6.4,
    "duration_mins": 14.2,      # thẳng từ Mapbox, KHÔNG nhân hệ số nào
    "polyline": "yseeAo…",
    "profile": "driving-traffic"  # MỚI — frontend dựng nhãn phương tiện từ đây
}
```

`profile` là **mã**, không phải chuỗi hiển thị — frontend dịch qua i18n
(`routeProfile.walking` → "đi bộ", `routeProfile.driving-traffic` → "ô tô"). Cùng nguyên
tắc với `match_reasons` ở Phase 2: backend trả dữ kiện, frontend trả câu chữ.

Trường hợp trùng toạ độ vẫn trả `{0.0, 0.0, "", profile: None}` — **giữ nguyên hành vi**
(`routing.py:84-89`), chỉ thêm khoá `profile`.

### Token

- Biến env `MAPBOX_ACCESS_TOKEN`, đọc qua settings như `supabase_service_key` đang làm
- Đây là **token phía server** — dùng secret token, **không** đặt URL restriction
- **Không bao giờ** đưa token vào bất kỳ payload API nào; nó không được xuất hiện trong
  `route_to_next` hay bất kỳ response nào
- Token cho tile trình duyệt là **token khác** (public + URL restriction) và do Phase 10
  quản lý — hai token, hai vòng đời, đừng dùng chung

Không có token → log cảnh báo **một lần** khi khởi động (không phải mỗi request) và mọi
route trả `None`. Hệ thống vẫn chạy, map vẽ đường thẳng.

### Xử lý lỗi

Hiện tại mọi lỗi đều thành `None` (`routing.py:53-55`), nên không phân biệt được cấu hình
sai với hết quota. Tách log theo mã:

| HTTP | Nghĩa | Log |
|---|---|---|
| 401 | Token sai/thiếu quyền | `error` — đây là lỗi cấu hình, phải sửa |
| 422 | Không tìm được tuyến (toạ độ giữa biển…) | `info` — bình thường, dữ liệu xấu |
| 429 | Vượt 300 req/phút | `warning` — cần xem lại cache hoặc quota |
| khác/timeout | Mạng | `warning` |

Giá trị trả về vẫn là `None` cho mọi trường hợp — chỉ mức log khác nhau. Frontend không cần
biết lý do.

### Rate limit và cache

300 request/phút. `lru_cache(maxsize=1024)` đã có, nhưng **key hiện tại chỉ là cặp toạ độ**
— phải thêm `profile` vào key, nếu không một chặng từng gọi `walking` sẽ trả nhầm kết quả
khi sau này gọi `driving-traffic`.

Một chuyến 4 ngày × 5 điểm ≈ 24 chặng ≈ 24 request. Rất xa ngưỡng 300/phút. Không cần
batching (Mapbox cho tối đa 25 toạ độ/request) — YAGNI, và batching làm mất polyline theo
từng chặng.

## File liên quan

- Sửa: `backend/src/services/routing.py` — thay `OSRMClient` bằng `MapboxDirectionsClient`,
  thêm `_pick_profile` + `_haversine_km`, bỏ hệ số 2.5, thêm `profile` vào kết quả
- Sửa: module settings — `mapbox_access_token`
- Sửa: `backend/.env.example` (nếu có) và tài liệu deploy — biến env mới
- Sửa: `backend/src/models/schemas.py` — thêm `profile` vào `RouteInfoPayload` (Phase 2 tạo)
- Sửa: `docs/chat_api_contract.md` — bổ sung `profile` và bộ giá trị của nó
- Tạo/sửa: test cho `routing.py`
- **Không đổi:** `recalculate_itinerary_routes` — logic gom theo ngày và thứ tự chặng giữ
  nguyên hoàn toàn; chỉ thứ nó gọi bên dưới là đổi

## Các bước thực hiện

1. Tạo tài khoản Mapbox, sinh **secret token** cho server. Ghi vào `.env` local và vào
   tài liệu deploy. **Không commit token.**
2. Thêm `mapbox_access_token` vào settings, đọc từ env như các key hiện có.
3. Viết `_haversine_km` và `_pick_profile` với hằng số `WALKING_THRESHOLD_KM = 1.2` có comment.
4. Thay `OSRMClient` bằng `MapboxDirectionsClient`:
   - BASE_URL mới, thêm `access_token` và `profile`
   - giữ `overview=full`, giữ `geometries` mặc định (polyline precision 5)
   - **xoá `* 2.5`**
   - thêm `"profile": profile` vào dict trả về
   - `lru_cache` key thêm `profile`
   - tách log theo 401/422/429/khác
5. Cảnh báo một lần lúc khởi động khi thiếu token.
6. Test:
   - chặng ngắn (< 1.2km) → gọi profile `walking`, kết quả có `profile: "walking"`
   - chặng dài → `driving-traffic`
   - `duration_mins` **không** bị nhân hệ số (so với `duration` thô của Mapbox)
   - trùng toạ độ → `{0.0, 0.0, ""}` như cũ
   - thiếu token → `None`, không exception
   - 401/422/429 → `None` với mức log tương ứng
   - cache: cùng cặp toạ độ + khác profile → **hai** entry, không đụng nhau
7. Chạy thật một chuyến ở Đà Nẵng, kiểm tra bằng mắt: polyline bám đường, thời lượng hợp lý
   (một quãng 6km trong phố nên ra khoảng 15-20 phút, không phải 40 phút như hệ số 2.5 cũ).
8. **Báo lại cho Dev F**: tỉ lệ chặng có route thật, và phân bố profile (bao nhiêu % walking).
   Số này quyết định Dev F test nhánh nào kỹ.

## Tiêu chí hoàn thành

- [ ] `routing.py` gọi Mapbox Directions v5, không còn tham chiếu `router.project-osrm.org`
- [ ] Hệ số `× 2.5` đã bị xoá; `duration_mins` là giá trị thật từ Mapbox
- [ ] `profile` có trong `route_to_next`, là mã chứ không phải chuỗi hiển thị
- [ ] Chặng < 1.2km dùng `walking`; ngưỡng là hằng số có tên và có comment
- [ ] Vẫn **một** request mỗi chặng; haversine lọc cục bộ trước khi gọi API
- [ ] `lru_cache` key gồm cả profile
- [ ] Token chỉ ở phía server, không xuất hiện trong bất kỳ response nào
- [ ] Thiếu token → cảnh báo một lần + `None`, hệ thống vẫn chạy
- [ ] 401/422/429 phân biệt được trong log
- [ ] `recalculate_itinerary_routes` không bị sửa
- [ ] Trường hợp trùng toạ độ giữ nguyên hành vi cũ
- [ ] Đã báo tỉ lệ route thật + phân bố profile cho Dev F
- [ ] Test suite backend pass

## Đánh giá rủi ro

**Token lọt ra ngoài.** Đây là rủi ro nghiêm trọng nhất. Token server có quyền gọi mọi API
Mapbox và tính tiền vào tài khoản. Bắt buộc: không commit, không đưa vào payload, không log.
Token tile của Phase 10 là token **khác** — public, có URL restriction, chỉ scope đọc style.
Dùng chung một token cho cả hai là sai.

**Chi phí và quota.** Mapbox tính tiền theo request. Một chuyến ≈ 24 request, cộng
`lru_cache` nên chạy lại cùng chuyến gần như miễn phí. Nhưng **cần kiểm tra hạn mức free
tier hiện tại trên trang giá của Mapbox trước khi lên production** — tôi không khẳng định
con số cụ thể vì chính sách giá thay đổi theo thời gian. Bật cảnh báo quota trong dashboard
Mapbox.

**Ngưỡng 1.2km là luật sản phẩm, không phải dữ liệu.** Nó quyết định gọi profile nào. Một
quãng 1.1km dốc núi sẽ được gán "đi bộ" dù thực tế nên đi xe. Chấp nhận được vì con số hiển
thị vẫn là tuyến đi bộ thật, nhưng nếu người dùng phản ánh thì chỉnh hằng số, đừng chuyển
sang suy đoán phức tạp hơn.

**`driving-traffic` phụ thuộc thời điểm gọi.** Route được tính lúc `persist_itinerary_bundle`
chạy, không phải lúc người dùng đi. Thời lượng phản ánh traffic **lúc lập lịch trình**. Với
lịch trình cho chuyến đi tương lai, đây là ước lượng — nên nhãn phía frontend vẫn giữ tiền
tố `~`. Nếu muốn chính xác hơn thì dùng `depart_at` với ngày giờ thật của lịch trình; ghi
lại thành việc tiếp theo, không làm trong phase này.

**Cáp treo vẫn không giải quyết được.** Mapbox không có profile cáp treo. Mục 1 bảng "Phần
chưa làm" thu hẹp lại chứ không biến mất.
