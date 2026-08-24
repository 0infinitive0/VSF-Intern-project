---
phase: 2
title: "Backend: role admin, require_admin, khung router"
status: done
priority: P1
effort: "6h"
dependencies: [1]
---

# Phase 2: Backend — role admin, require_admin, khung router

## Overview

Dựng tầng phân quyền và khung package cho toàn bộ API admin. Không có màn hình.
Mọi phase backend sau chỉ việc thêm router con vào khung này.

## Requirements

- Functional
  - Đọc claim role từ Supabase JWT.
  - `require_admin()` — dependency mới, **độc lập** với `get_current_user`.
  - `GET /api/v1/admin/me` để frontend biết mình có quyền hay không.
  - Hàm `write_audit(...)` dùng chung.
- Non-functional
  - `require_admin` **luôn** 401/403 khi thiếu quyền, kể cả `AUTH_REQUIRED=false`.
    Đây là điểm dễ sai nhất: `get_current_user` trả `None` thay vì raise khi cờ tắt.
  - Không đụng `backend/src/api/routes.py`.

## Architecture

### Role claim

Supabase đặt `app_metadata` vào JWT. Set thủ công một lần cho tài khoản vận hành
(quyết định #6 — 1 role duy nhất, không có màn quản lý tài khoản):

```sql
-- chạy trong Supabase SQL editor
UPDATE auth.users
SET raw_app_meta_data = raw_app_meta_data || '{"role":"admin"}'::jsonb
WHERE email = 'admin@vsftrip.vn';
```

> Phải là `app_metadata`, **không phải** `user_metadata`: `user_metadata` do chính
> người dùng ghi được qua `supabase.auth.updateUser()` → ai cũng tự phong admin được.

`SupabaseClaims` thêm trường:

```python
@dataclass(frozen=True)
class SupabaseClaims:
    user_id: str
    email: str | None
    is_anonymous: bool
    app_role: str | None      # payload["app_metadata"]["role"]
```

`verify_access_token` đọc `payload.get("app_metadata", {}).get("role")`, ép về `str`
hoặc `None`. Không đổi gì khác trong `jwt_verifier.py` — mọi call site hiện tại
không quan tâm trường mới.

### `require_admin`

`backend/src/auth/admin.py` (file mới, không nhét vào `dependencies.py` để ranh giới
"permissive rollout" vs "luôn chặt" rõ ràng):

```python
ADMIN_ROLE = "admin"

@dataclass(frozen=True)
class AdminUser:
    id: str
    email: str | None

def require_admin(authorization: str | None = Header(default=None)) -> AdminUser:
    token = _extract_bearer_token(authorization)      # dùng lại từ dependencies.py
    if not token:
        raise HTTPException(401, "Chưa đăng nhập.")
    try:
        claims = verify_access_token(token)
    except TokenVerificationError:
        raise HTTPException(401, "Phiên đăng nhập không hợp lệ.") from None
    if claims.is_anonymous or claims.app_role != ADMIN_ROLE:
        raise HTTPException(403, "Tài khoản này không có quyền truy cập trang quản trị.")
    return AdminUser(id=claims.user_id, email=claims.email)
```

Cố ý **không** đọc `get_settings().auth_required` ở đây.

### Khung router

```
backend/src/api/admin/
  __init__.py          # admin_router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
  schemas.py           # Pydantic model dùng chung (Page[T], AuditEntry, ...)
  audit.py             # write_audit()
  orders.py            # phase 4-6
  hotels.py            # phase 7-9
  rooms.py             # phase 10-11
  embedding.py         # phase 12
  pipelines.py         # phase 14-16
  overview.py          # phase 17
```

`Depends(require_admin)` đặt ở **APIRouter cấp package**, không rải trên từng
handler — quên một handler là thủng.

`main.py`: `app.include_router(admin_router, prefix="/api/v1")`.

Handler viết `def` thường (không `async def`), đúng quy ước ở `routes.py`: gọi
Supabase là blocking, FastAPI đẩy sang thread pool.

### Phân trang dùng chung

```python
class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int          # 1-based
    page_size: int
```

Supabase REST trả tối đa 1000 dòng/request và cần `count="exact"` để có `total`.

### `write_audit`

```python
def write_audit(actor: AdminUser, *, action: str, entity_type: str,
                entity_id: str, before: dict | None = None,
                after: dict | None = None) -> None:
```

Nuốt lỗi và `logger.exception` — audit hỏng **không được** làm hỏng thao tác nghiệp
vụ đã thành công.

## Related Code Files

- Create: `backend/src/api/admin/__init__.py`, `schemas.py`, `audit.py`
- Create: `backend/src/auth/admin.py`
- Create: `backend/tests/test_api/test_admin_auth.py`
- Modify: `backend/src/auth/jwt_verifier.py` (thêm `app_role` vào `SupabaseClaims`)
- Modify: `backend/src/auth/__init__.py` (export `require_admin`, `AdminUser`)
- Modify: `backend/src/main.py` (một dòng `include_router`)
- Modify: `frontend/src/types/wire.generated.ts` (sinh lại, không sửa tay)

## Hợp đồng API

```
GET /api/v1/admin/me
→ 200 { "id": "uuid", "email": "admin@vsftrip.vn" }
→ 401 { "detail": "Chưa đăng nhập." }
→ 403 { "detail": "Tài khoản này không có quyền truy cập trang quản trị." }
```

Frontend gọi endpoint này ngay sau đăng nhập để quyết định vào portal hay hiện màn
lỗi phân quyền (Phase 3).

## Implementation Steps

1. Thêm `app_role` vào `SupabaseClaims` + `verify_access_token`.
2. Viết `backend/src/auth/admin.py`. Tách `_extract_bearer_token` thành hàm dùng
   chung được (hiện là private trong `dependencies.py`).
3. Tạo package `backend/src/api/admin/` với `admin_router` + `GET /admin/me`.
4. Viết `audit.py`, `schemas.py`.
5. Nối vào `main.py`.
6. Test (xem dưới).
7. `npm run openapi:check` trong `frontend/`.

## Test bắt buộc

`backend/tests/test_api/test_admin_auth.py`:

- Không có header → 401, **cả khi** `AUTH_REQUIRED=false` (đây là bug class nguy hiểm nhất)
- Token hợp lệ nhưng không có `app_metadata.role` → 403
- Token có `user_metadata.role = 'admin'` nhưng `app_metadata` trống → **403** (chống tự phong quyền)
- Token có `app_metadata.role = 'admin'` → 200, trả đúng id/email
- Token anonymous kèm role admin → 403

Dùng fixture kiểu `auth_override` sẵn có ở `backend/tests/test_api/conftest.py`,
nhưng override `require_admin` thay vì `get_current_user`.

## Success Criteria

- [x] 5 test trên xanh (mở rộng thêm 8 test: 401-vs-403 phân biệt rõ, cả `AUTH_REQUIRED` true/false, cạnh biên `app_role`, và một test khẳng định mọi route `/api/v1/admin/*` đều bị `require_admin` chặn)
- [x] `curl /api/v1/admin/me` không kèm token → 403/401, kể cả khi `.env` có `AUTH_REQUIRED=false` (xác nhận bằng test, không cần curl thủ công)
- [x] `backend/src/api/routes.py` không thay đổi một dòng nào (`git diff --stat` rỗng)
- [x] `npm run openapi:check` — đã chạy `dump`+`gen`; diff chỉ gồm `/api/v1/admin/me` + `AdminMeResponse` (cộng một lệch pha `ValidationError` có sẵn từ trước, không liên quan phase này). Exit code khác 0 chỉ vì chưa commit gì — bản chất "sạch" (idempotent khi chạy lại) đã xác nhận
- [x] `pytest backend/tests` xanh (1292 passed; 16 fail đã xác nhận có sẵn trên `origin/main` sạch, không liên quan tới phase này — xem Verification)

## Verification

Code review (subagent độc lập) xác nhận cả 8 tiêu chí chấp nhận đều đạt, kể cả kiểm
tra runtime: sub-router thêm sau vẫn kế thừa `Depends(require_admin)` từ router cha;
`write_audit` nuốt lỗi đúng cách (thử cả lỗi khởi tạo client lẫn lỗi `.table()`);
đúng 1 lần gọi `verify_access_token` mỗi request (FastAPI cache theo dependency).
Sau review, đã bổ sung: test khẳng định router-guard bằng cách duyệt
`app.routes`/dependency graph thay vì chỉ dựa vào quy ước; test riêng cho
`app_role` đọc từ `app_metadata` thiếu/không phải object; test 401 (không phải 403)
cho token hỏng; parametrize test AUTH_REQUIRED qua cả true/false thay vì dựa vào
default của conftest.

**Còn lại (cần quyền truy cập Supabase thật, không làm được từ môi trường này):**
- 4 migration ở Phase 1 (`is_active`, sequences thủ công, `admin_audit_log`,
  fix `match_hotels_with_rooms`) **chưa** được áp dụng lên project Supabase thật —
  đã thử qua `supabase db query --linked` (Management API) nhưng bị chặn: bước
  khởi tạo temp role của CLI vẫn cần kết nối trực tiếp tới cổng Postgres của
  pooler, và IP của môi trường này không nằm trong allowlist của project. Người
  dùng sẽ tự chạy 4 file trong `backend/scripts/migrations/20260824_*.sql` (đúng
  thứ tự tên file) qua Supabase Studio SQL editor. `write_audit()` sẽ ghi log lỗi
  (không crash) cho tới khi bảng tồn tại — không chặn Phase 2, nhưng **chặn** bất
  kỳ call site nào gọi `write_audit()` ở Phase 4 trở đi tới khi áp dụng xong.
- Chưa decode thử một access token thật để xác nhận `app_metadata` sống sót qua
  JWKS của project thật (rủi ro Trung bình ở bảng dưới), và chưa xác nhận
  `admin@vsftrip.vn` đã có `raw_app_meta_data.role = "admin"` chưa. Người dùng sẽ
  tự kiểm tra khi có phiên đăng nhập thật (khớp với Phase 3 — màn đăng nhập admin).

## Risk Assessment

| Rủi ro | Mức | Giảm thiểu |
|--------|-----|-----------|
| Lẫn `user_metadata` và `app_metadata` → ai cũng tự phong admin | **Cao** | Có test riêng cho đúng case này; comment trong code |
| Quên `Depends(require_admin)` ở một router con thêm sau | Cao | Đặt ở APIRouter cấp package, không ở handler. Ghi vào "Ranh giới không được vượt" của plan. `test_every_admin_route_requires_admin` (test_admin_auth.py) khẳng định bằng cách duyệt `app.routes` + dependency graph — không chỉ dựa vào quy ước |
| `AUTH_REQUIRED=false` rò sang route admin | **Cao** | `require_admin` không đọc setting đó; test khẳng định |
| JWKS không trả về `app_metadata` (tuỳ cấu hình Supabase) | Trung bình | Bước 1 của Implementation: decode thử một token thật, in payload, xác nhận trước khi viết tiếp |
| Thu hồi quyền admin có độ trễ tới hết hạn token (mặc định Supabase ~1h) — xem trade-off đã chấp nhận trong `jwt_verifier.py`'s module docstring. Chiều ngược lại cũng đúng: `UPDATE auth.users` cấp quyền admin chỉ có hiệu lực ở lần đăng nhập **sau**, không phải ngay lập tức — tài khoản phải đăng xuất/đăng nhập lại | Trung bình | Chấp nhận (đã có trade-off tương tự cho toàn app); ghi rõ ở đây để Phase 3 không debug nhầm "tôi vừa cấp quyền mà vẫn 403" |
