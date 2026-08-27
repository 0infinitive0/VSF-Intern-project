# Admin API & Console

Plan: `260824-1015-admin-dashboard-portal`. Backend: `backend/src/api/admin/`.
Frontend SPA: `frontend/src/admin/`.

The admin surface manages the catalog the planner reads from (hotels, rooms, prices,
destinations, amenities), the orders the booking/payment flow creates, the embedding
index, and the Airflow pipelines. **It does not touch LangGraph state.**

---

## Mounting & auth

`backend/src/api/admin/__init__.py`:

```python
admin_router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
```

Mounted at `/api/v1` in `main.py`, so every path below is `/api/v1/admin/...`.
`require_admin` is **always strict** (ignores `AUTH_REQUIRED`): `401` without a valid
Supabase JWT, `403` unless the token's `app_role` claim is `"admin"`. See
[`authentication.md`](authentication.md).

`GET /api/v1/admin/me` → `AdminMeResponse` — who am I / am I admin (used by the SPA on load).

Writes against live, paying-guest data are recorded to the **`admin_audit_log`** table
(`actor_id`, `action`, `entity_type`, `entity_id`, `before`/`after` JSONB) via the
`audit` helper module.

## Sub-routers & endpoints

Paths relative to `/api/v1/admin`. Response models live in each module + `admin/schemas.py`.

### `overview`
| Method | Path | Purpose |
|---|---|---|
| GET | `/overview` | Dashboard summary (counts, recent activity). |

### `hotels`
| Method | Path | Purpose |
|---|---|---|
| GET | `/hotels` | Paginated/filtered hotel list. |
| POST | `/hotels` | Create a manual hotel (`201`). |
| GET | `/hotels/{hotel_id}` | Full hotel detail. |
| PATCH | `/hotels/{hotel_id}` | Update fields. |
| DELETE | `/hotels/{hotel_id}` | Delete (`204`). |
| PATCH | `/hotels/{hotel_id}/active` | Toggle `hotels.is_active`. |
| POST | `/hotels/bulk-active` | Bulk activate/deactivate. |
| GET | `/hotels/accommodation-types` | Distinct type values (for form selects). |
| POST | `/hotels/{hotel_id}/images/upload` | Upload a hotel image to storage (`201`). |

### `rooms`
| Method | Path | Purpose |
|---|---|---|
| GET | `/hotels/{hotel_id}/rooms` | Rooms of a hotel. |
| POST | `/hotels/{hotel_id}/rooms` | Create a room (`201`). |
| PATCH | `/rooms/{room_id}` | Update a room. |
| DELETE | `/rooms/{room_id}` | Delete (`204`). |
| GET | `/room-facilities` | Facility option list. |
| POST | `/rooms/{room_id}/images/upload` | Upload a room image (`201`). |

### `room_prices`
| Method | Path | Purpose |
|---|---|---|
| GET | `/rooms/{room_id}/prices` | Price rows for a room. |
| PUT | `/rooms/{room_id}/prices` | Set/replace price rows (admin's newer row can close a night). |
| DELETE | `/rooms/{room_id}/prices` | Remove price rows. |

### `destinations`
| Method | Path | Purpose |
|---|---|---|
| GET | `/destinations` | Destination option list. |

### `amenities` / `amenity_catalog`
| Method | Path | Purpose |
|---|---|---|
| GET | `/amenities` | Flat amenity option list. |
| GET | `/amenity-catalog` | Full `amenity_catalog` rows (paginated). |
| GET | `/amenity-catalog/{amenity_id}` | One row. |
| POST | `/amenity-catalog/check-duplicate` | Pre-check before creating. |
| POST | `/amenity-catalog/draft` | Create a draft (`is_approved=false`) entry. |
| PATCH | `/amenity-catalog/{amenity_id}` | Edit labels/category/keywords. |
| POST | `/amenity-catalog/{amenity_id}/approve` · `/bulk-approve` | Approve draft(s). |
| PATCH | `/amenity-catalog/{amenity_id}/retire` · POST `/reactivate` | Retire / bring back. |
| DELETE | `/amenity-catalog/{amenity_id}` | Delete (`204`). |

### `embedding`
| Method | Path | Purpose |
|---|---|---|
| GET | `/embedding/summary` | Coverage: how many hotels/attractions have vectors. |
| GET | `/embedding/missing` | Rows still missing an embedding. |
| POST | `/hotels/reembed` | Re-embed hotels (batch). |

### `orders`
| Method | Path | Purpose |
|---|---|---|
| GET | `/orders` | Orders (`payments`) or unpaid `bookings`, filtered. |
| GET | `/orders/stats` | Aggregate stats. |
| GET | `/orders/{payment_id}` | One order's detail. |
| POST | `/orders/{payment_id}/confirm` · `/cancel` | Manual state moves. |
| POST | `/orders/holds/release-expired` | Sweep expired `RESERVED` holds (manual — there is no cron). |

### `pipelines`
| Method | Path | Purpose |
|---|---|---|
| GET | `/pipelines/health` | Is Airflow reachable (`connected: bool`). |
| GET | `/pipelines` | DAG list + last-run status. |
| POST | `/pipelines/{dag_id}/runs` | Trigger a DAG run (`202`); unpauses it automatically. |

Pipeline calls go through `backend/src/services/airflow_client.py` to the separate
Airflow stack via `AIRFLOW_API_BASE`. If that env var is empty the whole branch is off:
`/pipelines/health` reports `connected: false` and every other call raises
`AirflowUnavailable` before any network request. Portal users have **no Airflow account
of their own** — `AIRFLOW_USERNAME` / `AIRFLOW_PASSWORD` live only in `backend/.env`.

## Granting admin

The `"admin"` value must be set on the user's Supabase `app_metadata.app_role`
(e.g. via the Supabase dashboard → Authentication → Users → the user → `app_metadata`,
or the Admin API). There is no in-app "make admin" endpoint.
