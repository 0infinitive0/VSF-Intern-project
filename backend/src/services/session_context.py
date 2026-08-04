"""Typed, versioned session context shared by the conversational API."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class StayDates(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    duration_days: int | None = Field(default=None, ge=1, le=90)

    @model_validator(mode="after")
    def validate_interval(self) -> StayDates:
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError("start_date and end_date must be provided together")
        if self.start_date and self.end_date:
            duration_days = (self.end_date - self.start_date).days
            if duration_days <= 0:
                raise ValueError("end_date must be after start_date")
            self.duration_days = duration_days
        return self


class Guests(BaseModel):
    adults: int = Field(default=1, ge=1, le=20)
    children: int = Field(default=0, ge=0, le=20)


class PriceRange(BaseModel):
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    currency: Literal["VND", "USD"] = "VND"

    @model_validator(mode="after")
    def validate_bounds(self) -> PriceRange:
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError("min_price must not exceed max_price")
        return self


class SessionContextData(BaseModel):
    destination_id: str | None = None
    destination_name: str | None = None
    dates: StayDates = Field(default_factory=StayDates)
    guests: Guests = Field(default_factory=Guests)
    price_range: PriceRange = Field(default_factory=PriceRange)
    preferences: list[str] = Field(default_factory=list, max_length=30)
    selected_hotel_id: str | None = None
    excluded_hotel_ids: list[str] = Field(default_factory=list, max_length=200)
    active_step: Literal["trip_info", "hotel_selection", "itinerary"] = "trip_info"

    def merge_preferences(
        self,
        *,
        add_preferences: list[str] = (),
        remove_preferences: list[str] = (),
    ) -> SessionContextData:
        remove = {value.strip().casefold() for value in remove_preferences if value.strip()}
        merged = [value for value in self.preferences if value.casefold() not in remove]
        existing = {value.casefold() for value in merged}
        for value in add_preferences:
            cleaned = value.strip()
            if cleaned and cleaned.casefold() not in existing:
                merged.append(cleaned)
                existing.add(cleaned.casefold())
        return self.model_copy(update={"preferences": merged})
