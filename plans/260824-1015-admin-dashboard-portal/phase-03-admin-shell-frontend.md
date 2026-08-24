---
phase: 3
title: "Frontend: entry admin.html, shell, đăng nhập"
status: pending
priority: P1
effort: "1.5d"
dependencies: [2]
---

# Phase 3: Frontend — entry riêng, shell, đăng nhập

**Màn: A1 (Đăng nhập) · A2 (Shell + 3 trạng thái) · Z (Bộ thành phần dùng chung)**

## Overview

Dựng toàn bộ nền frontend admin trong một bundle **tách hẳn** khỏi app chat
(quyết định #8), cùng bộ primitive UI mà 12 màn sau dùng lại. Sau phase này, ba
nhánh Đơn hàng / Khách sạn / Pipeline làm song song được.

Bản thiết kế: `plans/reports/VSF Trip Planner Admin Dashboard/VSF Admin Portal.dc.html`
artboard **A1**, **A2**, **Z**; sidebar ở `Sidebar.dc.html`.

## Requirements

- Functional
  - `/admin` là một trang riêng, có router nội bộ cho các route con.
  - Đăng nhập bằng Supabase (dùng lại client đã có), gọi `GET /admin/me`.
  - Tài khoản không phải admin → màn "Tài khoản này không có quyền truy cập trang
    quản trị" + nút quay lại, **không** vào được shell.
  - Shell: sidebar 240px + header (breadcrumb, tiêu đề, nút hành động chính).
  - Ba trạng thái dùng lại toàn hệ thống: skeleton bảng · rỗng · lỗi tải.
  - Bộ primitive: nút (chính/phụ/nguy hiểm/mờ), input, select, chip trạng thái,
    hàng bảng, phân trang, tab, switch, banner cảnh báo, khung rỗng, skeleton.
- Non-functional
  - Chỉ light mode (quyết định #12).
  - Desktop-first 1440px, không làm mobile.
  - Toàn bộ chữ tiếng Việt, **không** dùng i18next (app chat có i18n; portal nội bộ
    một ngôn ngữ — thêm i18n là chi phí không đổi lại gì).
  - Tiền: `1.500.000 ₫`. Ngày: `24/08/2026`.
  - Không sửa file nào của app chat.

## Architecture

### Vite multi-page

`frontend/vite.config.ts`:

```ts
build: {
  rollupOptions: {
    input: {
      main:  resolve(__dirname, 'index.html'),
      admin: resolve(__dirname, 'admin.html'),
    },
  },
},
```

Kèm `frontend/admin.html` (copy `index.html`, đổi `<title>` và trỏ
`/src/admin/main.tsx`). Dev: `http://localhost:5173/admin.html`.

Prod: `Caddyfile` cần rewrite `/admin` và `/admin/*` → `/admin.html` để router nội
bộ (history API) hoạt động. **Đọc `Caddyfile` hiện tại trước khi sửa.**

### Router nội bộ

Không thêm `react-router-dom`. Portal có ~10 route phẳng, không cần nested route,
không cần loader/action. Một hook nhỏ là đủ:

```
src/admin/router.tsx
  useAdminRoute(): { path: string; navigate(to: string): void }
```

Dựa trên `history.pushState` + `popstate`, base `/admin`. Route:

| Route | Màn | Phase |
|---|---|---|
| `/admin` | Tổng quan | 17 |
| `/admin/hotels` | B1 | 7 |
| `/admin/hotels/new` | B2 | 8 |
| `/admin/hotels/:id` (+tab) | B3 / B5 / B6 | 9, 10, 11 |
| `/admin/embedding` | B7 Trạng thái embedding | 12 |
| `/admin/pipelines` | C1 | 14 |
| `/admin/pipelines/do-phu-embedding` | C4 Độ phủ embedding | 12 |
| `/admin/pipelines/runs/:id` | C3 | 16 |
| `/admin/orders` | D1 | 4 |
| `/admin/orders/:id` | D2 | 5 |

Phase này chỉ dựng router + route rỗng; mỗi phase sau gắn màn của mình vào.

### Cấu trúc thư mục

```
frontend/admin.html
frontend/src/admin/
  main.tsx              entry, mount AdminApp
  admin-app.tsx         gate đăng nhập/phân quyền → shell
  router.tsx
  api/
    client.ts           fetch wrapper cho /api/v1/admin (dùng lại authHeaders)
    admin-me.ts
  auth/
    admin-login.tsx     A1
    forbidden.tsx       A1 trạng thái lỗi phân quyền
  layout/
    admin-shell.tsx     A2
    sidebar.tsx
    page-header.tsx
  ui/                   Z — bộ primitive
    button.tsx  input.tsx  select.tsx  status-chip.tsx
    data-table.tsx  pagination.tsx  tabs.tsx  switch.tsx
    banner.tsx  empty-state.tsx  skeleton-table.tsx  error-state.tsx
    drawer.tsx  modal.tsx  money.tsx  date-text.tsx
  styles/admin.css      design token
```

`api/client.ts` tái dùng `../../api/auth-headers` (đã có, đọc token từ Supabase SDK).
Đây là file duy nhất của app chat mà admin **đọc** — không sửa.

### Design token

Copy nguyên khối `:root` từ `VSF Admin Portal.dc.html` vào `admin.css`. Điều chỉnh
cho môi trường admin, đúng như prompt thiết kế:
- Vùng bảng nền đặc `--g3`, không kính mờ.
- Kính chỉ ở sidebar, header dính, drawer/panel nổi.
- Dòng bảng cao 44–48px, chữ 13–14px, tiền `tabular-nums` canh phải.
- Bo góc: card 16px, input/nút 10px, chip 999px.
- Font `Be Vietnam Pro` (Google Fonts, như file thiết kế).

Repo có `frontend/scripts/check-design-tokens.mjs` — kiểm xem script này có quét
`src/admin/` không; nếu có thì `admin.css` phải khai báo token theo đúng format nó
mong đợi, hoặc loại trừ thư mục.

### Bảng màu trạng thái (dùng nhất quán ở MỌI màn)

| Trạng thái | Nền | Chữ |
|---|---|---|
| PENDING / chờ | `--warn-soft` | `--warn-ink` |
| RESERVED / đang giữ | `--acc-soft` | `--acc` |
| CONFIRMED / PAID | `--ok-soft` | `--ok-ink` |
| CANCELLED / FAILED / EXPIRED | `--fill` | `--t3` |

`StatusChip` **luôn** kèm nhãn chữ, không bao giờ chỉ dựa vào màu.

### Luồng gate

```
main.tsx
 └ AuthProvider (dùng lại của app chat)
    └ AdminApp
       ├ chưa đăng nhập      → <AdminLogin/>          (A1)
       ├ đã đăng nhập, đang gọi /admin/me → splash
       ├ /admin/me trả 403   → <Forbidden/>           (A1 lỗi phân quyền)
       └ /admin/me trả 200   → <AdminShell/> + router
```

Gate 403 là **UX**, không phải bảo mật — mọi endpoint đã có `require_admin`.

## Related Code Files

- Create: `frontend/admin.html`
- Create: toàn bộ `frontend/src/admin/**` (danh sách ở Architecture)
- Modify: `frontend/vite.config.ts` (thêm `build.rollupOptions.input`)
- Modify: `Caddyfile` (rewrite `/admin*` → `/admin.html`)
- Reference (đọc, không sửa): `frontend/src/api/auth-headers.ts`, `frontend/src/lib/supabase-client.ts`, `frontend/src/auth/auth-context.tsx`, `frontend/src/lib/format-currency.ts`
- Reference (thiết kế): `plans/reports/VSF Trip Planner Admin Dashboard/VSF Admin Portal.dc.html` artboard A1/A2/Z, `Sidebar.dc.html`

## Sở hữu file

Phase này sở hữu `frontend/src/admin/ui/`, `layout/`, `auth/`, `router.tsx`.
Các phase sau **chỉ thêm** file vào `src/admin/pages/` và `src/admin/api/`, không
sửa `ui/` trừ khi thiếu primitive (khi đó thêm file mới, không sửa file cũ).

## Implementation Steps

1. Đọc `Caddyfile`, `vite.config.ts`, `scripts/check-design-tokens.mjs`.
2. Thêm `admin.html` + input thứ hai vào vite config. Xác nhận `npm run build` sinh
   **hai** HTML và bundle chat không đổi kích thước.
3. `admin.css` + token.
4. Bộ `ui/` (Z) — làm trước, vì mọi màn sau dùng.
5. `router.tsx`.
6. `AdminShell` + `Sidebar` + `PageHeader` (A2), nav đúng 4 mục ở plan.md.
7. `AdminLogin` + `Forbidden` (A1).
8. `AdminApp` nối gate.
9. Rewrite Caddy, kiểm F5 giữa chừng ở `/admin/orders` không ra 404.

## Success Criteria

- [ ] `npm run build` sinh `dist/index.html` **và** `dist/admin.html`; kích thước bundle chat không đổi
- [ ] Vào `/admin` chưa đăng nhập → màn A1
- [ ] Đăng nhập bằng tài khoản thường → màn lỗi phân quyền, **không** thấy sidebar
- [ ] Đăng nhập bằng tài khoản có `app_metadata.role='admin'` → vào shell
- [ ] Sidebar đúng 4 mục theo plan.md (không có Đối soát / Nhật ký / Lịch phòng)
- [ ] F5 tại `/admin/orders` không ra 404 (dev và prod)
- [ ] Ba trạng thái skeleton/rỗng/lỗi render được trên một trang mẫu
- [ ] `npm run lint` + `npm run typecheck` sạch
- [ ] App chat ở `/` chạy nguyên trạng; `npm test` xanh

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Caddy chưa rewrite → F5 giữa chừng ra 404 | Cao | Có mục riêng trong Success Criteria, test cả dev lẫn prod |
| Tự viết router thiếu tính năng, sau phải đổi sang react-router | Trung bình | Đặc tả trước đúng 10 route phẳng ở trên. Nếu phát sinh nested route/loader thì dừng và đổi — chi phí thấp vì router bị cô lập trong 1 file |
| `check-design-tokens.mjs` fail vì thư mục mới | Thấp | Đọc script ở bước 1 |
| Bundle admin vô tình kéo theo `mapbox-gl`, `i18next` của app chat | Trung bình | Không import gì từ `src/components/`; soi kích thước chunk sau build |
| `AuthProvider` của chat giả định luôn có anonymous session | Trung bình | Đọc `auth-context.tsx` ở bước 1; nếu nó tự tạo anonymous session thì portal phải bỏ qua hành vi đó (anonymous luôn 403) |
