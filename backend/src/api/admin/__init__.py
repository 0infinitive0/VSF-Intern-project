"""Admin API package. Every route below requires an authenticated admin
caller -- enforced once at the router level (not per-handler) so a future
sub-router can never forget to add the check itself."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.admin.amenities import amenities_router
from src.api.admin.destinations import destinations_router
from src.api.admin.embedding import embedding_router
from src.api.admin.hotels import hotels_router
from src.api.admin.orders import orders_router
from src.api.admin.overview import overview_router
from src.api.admin.pipelines import pipelines_router
from src.api.admin.room_prices import room_prices_router
from src.api.admin.rooms import rooms_router
from src.api.admin.schemas import AdminMeResponse
from src.auth import AdminUser, require_admin

admin_router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
admin_router.include_router(hotels_router)
admin_router.include_router(destinations_router)
admin_router.include_router(amenities_router)
admin_router.include_router(rooms_router)
admin_router.include_router(room_prices_router)
admin_router.include_router(orders_router)
admin_router.include_router(embedding_router)
admin_router.include_router(pipelines_router)
admin_router.include_router(overview_router)


@admin_router.get("/me", response_model=AdminMeResponse)
def get_me(admin: AdminUser = Depends(require_admin)) -> AdminMeResponse:
    return AdminMeResponse(id=admin.id, email=admin.email)
