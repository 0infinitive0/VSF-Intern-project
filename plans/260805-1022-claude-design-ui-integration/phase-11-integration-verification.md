---
phase: 11
title: "Tích hợp & Kiểm thử"
status: pending
priority: P1
effort: "1.5-2 ngày"
dependencies: [2, 3, 4, 6, 7, 8, 9, 10]
track: chung
---

# Phase 11: Tích hợp & Kiểm thử

## Tổng quan

Ghép hai track lại: chạy frontend với backend thật thay vì mock, đối chiếu contract, quét
i18n, kiểm tra responsive và tương phản cả hai theme, rồi đối chiếu kết quả với bảng "Phần
chưa làm".

Đây là lần đầu tiên frontend chạm vào backend thật kể từ Phase 1. Mọi lệch contract sẽ lộ ra
ở đây, nên phase này có ngân sách riêng thay vì gộp vào phase cuối của mỗi track.

## Yêu cầu

**Chức năng**
- Frontend chạy với backend thật, không dùng mock, qua trọn vẹn luồng người dùng
- Mọi payload thật khớp contract Phase 1; lệch nào cũng phải sửa hoặc ghi lại
- Cả hai focus mode chạy trên endpoint thật
- Lịch sử hội thoại list và restore được với session thật
- Map hiển thị đúng toạ độ thật

**Phi chức năng**
- Cả hai catalog i18n đầy đủ, không còn khoá thiếu, không còn chuỗi hardcode
- Responsive ở `sm` / `md` / `lg` / `xl`, không có scroll ngang toàn trang
- Tương phản đạt WCAG AA cho chữ ở cả theme sáng và tối
- `prefers-reduced-motion` và `prefers-reduced-transparency` được tôn trọng

## Kiến trúc

### Đối chiếu contract

Cách kiểm tra rẻ và hiệu quả: chạy cùng một kịch bản hội thoại hai lần — một lần với
`npm run mock`, một lần với backend thật — và so sánh shape response.

Với mỗi endpoint, kiểm ba điều:
1. **Field thiếu** — backend không trả field mà contract hứa → sửa backend hoặc sửa contract
2. **Field thừa** — backend trả field không có trong contract → thêm vào contract nếu hữu ích
3. **Kiểu sai** — ví dụ `star_rating` là chuỗi thay vì số, `coordinates` khác định dạng dự kiến

Điểm 3 là nguy hiểm nhất vì TypeScript không bắt được ở runtime. Chú ý riêng:
- định dạng `coordinates` (cảnh báo đã nêu ở Phase 9 và 10)
- `star_rating` là `numeric(2,1)` trong DB → có thể ra `4.5`, không phải số nguyên; UI vẽ
  sao phải xử lý được nửa sao hoặc làm tròn có chủ đích
- `review_score` thang 0..10, **không phải** 0..5
- `intake.people` là chuỗi đã format, không phải số

### Quét i18n

Ba việc:
1. Đối chiếu khoá giữa `en.json` và `vi.json` — không bên nào được có khoá mà bên kia thiếu
2. Grep tìm chuỗi hardcode còn sót trong `frontend/src/components/**` (chữ có dấu tiếng Việt
   nằm trong JSX là dấu hiệu rõ nhất). Đối chiếu với `trip_planner_components/scripts/
   constants/i18n.js` để bắt chuỗi UI còn thiếu — nhưng **chỉ lấy phần `ui`**, không lấy phần
   kịch bản hội thoại mock (xem `plan.md` §Lấy gì từ bản design prototype)
3. Kiểm tra `matchReason.*` phủ hết mọi mã mà Phase 2 phát ra

Nhớ kiểm tra cả trường hợp text tiếng Anh dài hơn tiếng Việt làm vỡ card/nút — đây là yêu
cầu tường minh trong `Internationalization.md` §Responsive Layout.

### Hành vi phải còn nguyên

Danh sách này là hợp đồng bất biến của plan. Kiểm tay từng mục:

| Hành vi | Cách kiểm |
|---|---|
| Bootstrap session, khôi phục từ sessionStorage | Reload trang giữa hội thoại |
| Server restart → tự tạo session mới im lặng | Restart backend rồi gửi tin |
| Gửi tin, chip gợi ý, form intake | Chạy trọn luồng thu thập thông tin |
| Giá trị wire intake không đổi | So log backend với baseline Phase 6 |
| Chọn khách sạn theo số thứ tự | Ba đường phải ra cùng kết quả: card → nút xác nhận header (luồng hai bước của Phase 8), chip gợi ý, và gõ thẳng số vào composer. Kiểm tra bấm card **không** gửi gì cho tới khi bấm nút xác nhận |
| Reset "Chuyến đi mới" + hộp xác nhận | Bấm nút, huỷ, rồi bấm lại và xác nhận |
| Chuyển ngôn ngữ giữa chừng không mất dữ liệu | Đổi VI↔EN khi đang ở workspace |
| Kéo đổi kích thước panel | Kéo vách ngăn |
| Bong bóng lỗi khi backend lỗi | Tắt backend rồi gửi tin |

### Đối chiếu thị giác với bản design đang chạy

Bản design **chạy được**, không phải ảnh tĩnh:

```bash
cd data/trip_planner/trip_planner_components && npm run dev   # → http://localhost:5173
```

Server node zero-dependency (`server.js`), không cần cài gì. Chạy song song với app thật ở
cổng khác, rồi đối chiếu **4 breakpoint × 2 theme × 4 stage**.

Ảnh tham chiếu có sẵn: `trip_planner_components/screenshots/` — `sb.png` (intake),
`hotel-focus.png`, `01-focus.png` / `02-focus.png` (workspace + place focus), `dark.png`.

**Không** làm pixel-diff tự động. Dữ liệu thật khác mock của design (tên khách sạn, số ngày,
số điểm đều khác) nên diff pixel sẽ nhiễu tới mức vô dụng và sẽ bị bỏ qua sau lần thứ hai.
Mục tiêu là bắt lệch **cấu trúc**: thiếu panel, thiếu bề mặt glass, sai bố cục cột, sai thang
bậc chữ, mất animation vào.

Cụ thể cần soi:

| Điều dễ trượt | Vì sao |
|---|---|
| Bề mặt glass của panel | Đúng loại lỗi Phase 6 mắc — nội dung đúng, bề mặt không tồn tại |
| Nền `--gradient-page` bị phủ | Một `bg-*` đặc ở container cha là đủ giết cả hệ glass |
| Animation vào (`vPop`/`vFade`/`vIn`/`vRise`) | Không có nó thì UI "đúng" nhưng chết cứng |
| Thang bậc chữ | 12.5 / 13.5 / 14 / 16 / 26px là có chủ đích, không phải làm tròn được |
| Dark theme | Chỗ hardcode hex chỉ lộ ra ở theme tối |

### Đối chiếu bảng "Phần chưa làm"

Đọc lại 12 mục trong `plan.md` và với mỗi mục xác định: (a) vẫn đúng là chưa làm, (b) đã làm
trong quá trình triển khai — cập nhật bảng, hoặc (c) hoá ra **có** dữ liệu nhưng bị bỏ sót —
ghi thành việc tiếp theo.

Đặc biệt kiểm lại mục 1 (phương tiện/thời gian di chuyển) và mục 3 (card Cập nhật/Giữ kết
quả): đây là hai chỗ dễ bị "lỡ tay" thêm vào cho giống design nhất.

## File liên quan

- Sửa: `docs/chat_api_contract.md` — ghi lại mọi lệch phát hiện được
- Sửa: `plans/260805-1022-claude-design-ui-integration/plan.md` — cập nhật bảng "Phần chưa làm"
- Sửa: `frontend/src/i18n/locales/{en,vi}.json` — bổ sung khoá thiếu
- Sửa: các file frontend/backend cần vá sau khi đối chiếu
- Tạo: `plans/reports/integration-260805-claude-design-ui.md` — báo cáo nghiệm thu

## Các bước thực hiện

1. Chạy backend thật + frontend (không mock). Đi trọn luồng: intake → khách sạn → workspace.
2. Ghi lại response thật của cả 8 endpoint; so với contract Phase 1 theo 3 tiêu chí ở trên.
3. Sửa mọi lệch. Lệch nào không sửa được trong phase này thì ghi vào contract kèm lý do.
4. Kiểm cả hai focus mode với id thật; xác nhận mức phủ field khớp báo cáo của Phase 3 bước 7.
5. Kiểm lịch sử: tạo vài hội thoại, restart backend, list, restore, chat tiếp.
6. Kiểm map với toạ độ thật — xác minh bằng mắt marker rơi đúng vị trí địa lý.
7. Quét i18n (3 việc ở trên). Kiểm cả layout với text tiếng Anh dài.
8. Chạy hết bảng "hành vi phải còn nguyên".
9. Kiểm responsive ở 4 breakpoint; kiểm tương phản cả hai theme; kiểm reduced-motion và
   reduced-transparency.
10. Kiểm bàn phím và screen reader trên các luồng chính.
11. Chạy `npm run typecheck`, `npm run lint`, `npm run check:tokens`, test suite backend.
11b. **Đối chiếu thị giác**: chạy bản design (`npm run dev` trong `trip_planner_components`)
    song song app thật; soi 4 breakpoint × 2 theme × 4 stage theo bảng "điều dễ trượt" ở trên.
    Ghi lệch vào báo cáo nghiệm thu kèm ảnh, phân loại sửa-ngay / chấp-nhận / ghi-việc-sau.
11c. Rà lại `design-fidelity-checklist.md`: mọi dòng của phase 5-10 phải hoặc đã tick, hoặc
    bỏ tick **kèm lý do**. Dòng bỏ trống không lý do là chưa xong, không phải đã bỏ qua.
12. Đối chiếu bảng "Phần chưa làm", cập nhật `plan.md`.
13. Viết báo cáo nghiệm thu: file đã thêm, file đã sửa, component tái dùng, component tạo
    mới, việc còn phải làm tay.

## Tiêu chí hoàn thành

- [ ] Frontend chạy trọn luồng với backend thật, không dùng mock
- [ ] Mọi lệch contract đã sửa hoặc đã ghi lại kèm lý do
- [ ] Định dạng `coordinates`, thang `review_score`, kiểu `star_rating` đã xác minh trên dữ liệu thật
- [ ] Hai focus mode chạy trên endpoint thật với mức phủ field đã biết
- [ ] Lịch sử hội thoại list + restore được sau khi restart backend
- [ ] Marker trên map rơi đúng vị trí địa lý thật
- [ ] Hai catalog i18n đối xứng; không còn chuỗi hardcode
- [ ] Text tiếng Anh dài không làm vỡ card, nút hay timeline
- [ ] Toàn bộ bảng "hành vi phải còn nguyên" pass
- [ ] Responsive ở 4 breakpoint, không scroll ngang toàn trang
- [ ] Tương phản WCAG AA ở cả hai theme
- [ ] `prefers-reduced-motion` và `prefers-reduced-transparency` được tôn trọng
- [ ] `npm run typecheck`, `npm run lint`, `npm run check:tokens`, test suite backend đều pass
- [ ] Đã đối chiếu ảnh cạnh nhau với bản design đang chạy ở 4 breakpoint × 2 theme × 4 stage
- [ ] Mọi bề mặt glass tồn tại thật; không container nào phủ màu đặc lên `--gradient-page`
- [ ] Animation vào (`vPop`/`vFade`/`vIn`/`vRise`) có mặt ở đúng chỗ design quy định
- [ ] `design-fidelity-checklist.md` không còn dòng bỏ trống mà không có lý do
- [ ] Bảng "Phần chưa làm" đã đối chiếu và cập nhật
- [ ] Báo cáo nghiệm thu đã viết

## Đánh giá rủi ro

**Lệch contract phát hiện muộn.** Đây là lý do phase này tồn tại như một phase riêng có ngân
sách. Nếu lệch nhiều, ưu tiên sửa phía backend (frontend đã được viết để mọi field mới đều
optional, nên nó chịu được field thiếu; ngược lại thì không).

**Sai kiểu âm thầm.** TypeScript không kiểm tra runtime, nên `star_rating: "4.5"` thay vì
`4.5` sẽ trượt qua compile và hỏng ở chỗ render. Bước 2 phải xem giá trị thật, không chỉ đọc
tên field.

**`mock-data.js` của bản design nằm sẵn ngay cạnh thứ được phép lấy.** 86 dòng hotels/days/
landmarks/convos giả, trông hoàn toàn thật. Nếu một section render rỗng vì DB thưa dữ liệu,
đây là thứ dễ với tay nhất để lấp — và lấp xong thì **mọi tiêu chí "giống design" đều pass**
trong khi nguyên tắc số một của plan bị vi phạm, không ai phát hiện cho tới lúc demo. Bước 12
và bảng "Phần chưa làm" tồn tại để chống lại đúng điều này. Grep `frontend/src` tìm dấu vết
tên khách sạn/địa điểm của mock design trước khi nghiệm thu.

**Cám dỗ "làm nốt cho giống design" ở phút chót.** Đến phase này, phần chưa làm sẽ rất dễ
thấy và rất dễ lấp bằng dữ liệu bịa. Bước 12 tồn tại chính để chống lại điều đó — đối chiếu
là để **xác nhận** phần chưa làm vẫn chưa làm, không phải để đi lấp cho đầy.
