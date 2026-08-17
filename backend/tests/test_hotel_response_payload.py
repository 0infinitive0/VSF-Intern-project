import src.models.schemas as schemas
from src.services.amenity_catalog import AmenityCatalogEntry


def test_hotel_amenities_are_joined_once_after_hotel_options_without_legacy_preferences(monkeypatch):
    calls = []

    def query(ids):
        calls.append(ids)
        return [
            AmenityCatalogEntry(
                id="wifi",
                label="Wi-Fi",
                label_en="Wi-Fi",
                scope="both",
                category="connectivity",
                icon_key="wifi",
                match_keywords=("wifi",),
            ),
            AmenityCatalogEntry(
                id="swimming_pool",
                label="Hồ bơi",
                label_en="Swimming pool",
                scope="both",
                category="wellness",
                icon_key="pool",
                match_keywords=("hồ bơi", "pool"),
            ),
        ]

    monkeypatch.setattr(
        schemas,
        "query_all_approved_amenities_by_ids",
        query,
    )

    payload = schemas.to_hotel_options_payload(
        {
            "active_preferences": [{"id": "swimming_pool", "label": "Hồ bơi"}],
            "options": [
                {
                    "id": "hotel-1",
                    "name": "Hotel One",
                    "amenities": ["wifi", "swimming_pool"],
                }
            ],
        }
    )

    hotel = payload[0].model_dump()
    assert hotel["amenities"] == ["wifi", "swimming_pool"]
    assert hotel["display_amenities"] == ["swimming_pool", "wifi"]
    assert "amenity_details" not in hotel
    assert schemas.hotel_amenities_from_hotel_options(payload) == [
        schemas.AmenityCatalogPayload(id="wifi", label_vi="Wi-Fi", label_en="Wi-Fi", category="connectivity", icon_key="wifi"),
        schemas.AmenityCatalogPayload(id="swimming_pool", label_vi="Hồ bơi", label_en="Swimming pool", category="wellness", icon_key="pool"),
    ]
    assert calls == [["wifi", "swimming_pool"]]
    assert [item.model_dump() for item in schemas.hotel_amenities_from_hotel_options([])] == []
    assert "preferences" not in hotel


def test_hotel_amenity_catalog_also_covers_ids_displayed_on_cards(monkeypatch):
    monkeypatch.setattr(
        schemas,
        "query_all_approved_amenities_by_ids",
        lambda ids: [
            AmenityCatalogEntry(
                id="swimming_pool",
                label="Hồ bơi",
                label_en="Swimming pool",
                scope="both",
                category="wellness",
                icon_key="pool",
                match_keywords=("pool",),
            )
        ],
    )

    details = schemas.hotel_amenities_from_hotel_options(
        [{"amenities": [], "display_amenities": ["swimming_pool"]}]
    )

    assert [detail.id for detail in details] == ["swimming_pool"]
