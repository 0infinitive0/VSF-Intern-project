"""Pydantic models shared across the admin API package."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class AdminMeResponse(BaseModel):
    id: str
    email: str | None


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
