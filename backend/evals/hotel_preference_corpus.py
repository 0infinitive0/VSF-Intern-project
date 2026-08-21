"""Deterministic 210-case hotel-preference binder corpus.

The matcher portion deliberately needs neither Supabase nor an LLM. These
families cover Vietnamese/English aliases and all three polarities; production
messages can be appended without changing the harness contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.services.amenity_catalog import AmenityCatalogEntry, resolve_hotel_amenity


@dataclass(frozen=True)
class CorpusCase:
    message: str
    phrase: str
    expected_id: str
    polarity: str


_FAMILIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("parking", "Bãi đỗ xe", ("bãi đỗ xe", "chỗ đậu xe", "parking", "car park", "đỗ ô tô", "nơi gửi xe", "bãi xe")),
    ("wifi", "Wi-Fi", ("wifi", "wi-fi", "wifi miễn phí", "free wifi", "mạng không dây", "internet không dây", "wireless internet")),
    ("swimming_pool", "Hồ bơi", ("hồ bơi", "bể bơi", "pool", "swimming pool", "hồ bơi ngoài trời", "chỗ bơi", "bể bơi khách sạn")),
    ("gym", "Phòng gym", ("gym", "phòng gym", "phòng tập", "fitness center", "fitness", "tập thể dục", "phòng thể hình")),
    ("spa", "Spa", ("spa", "dịch vụ spa", "spa hotel", "wellness spa", "khu spa", "chăm sóc spa", "spa tại chỗ")),
    ("breakfast", "Bữa sáng", ("bữa sáng", "ăn sáng", "breakfast", "có buffet sáng", "bao gồm bữa sáng", "đồ ăn sáng", "phục vụ sáng")),
    ("sea_view", "View biển", ("view biển", "nhìn ra biển", "sea view", "ocean view", "hướng biển", "cảnh biển", "phòng ngắm biển")),
    ("private_beach", "Bãi biển riêng", ("bãi biển riêng", "private beach", "biển riêng", "bãi tắm riêng", "lối ra biển riêng", "private seaside", "bờ biển riêng")),
    ("airport_shuttle", "Đưa đón sân bay", ("đưa đón sân bay", "airport shuttle", "xe sân bay", "shuttle sân bay", "đón ở sân bay", "airport transfer", "chở ra sân bay")),
    ("beauty_service", "Dịch vụ làm đẹp", ("dịch vụ làm đẹp", "beauty service", "chăm sóc sắc đẹp", "làm đẹp", "beauty treatment", "beauty care", "thẩm mỹ")),
)

_TEMPLATES = {
    "require": "Khách sạn phải có {phrase}",
    "prefer": "Tôi ưu tiên khách sạn có {phrase}",
    "exclude": "Tôi không muốn khách sạn có {phrase}",
}


CATALOG_SNAPSHOT = tuple(
    AmenityCatalogEntry(
        id=amenity_id,
        label=label,
        label_en=phrases[2],
        scope="hotel",
        category="general",
        match_keywords=phrases,
    )
    for amenity_id, label, phrases in _FAMILIES
)

CASES = tuple(
    CorpusCase(template.format(phrase=phrase), phrase, amenity_id, polarity)
    for amenity_id, _label, phrases in _FAMILIES
    for phrase in phrases
    for polarity, template in _TEMPLATES.items()
)


def evaluate_matcher() -> dict[str, float]:
    coverage = {entry.id: 1 for entry in CATALOG_SNAPSHOT}
    correct = resolved = silent_drops = 0
    for case in CASES:
        result = resolve_hotel_amenity(case.phrase, entries=CATALOG_SNAPSHOT, coverage=coverage)
        if result.status == "resolved" and result.candidate is not None:
            resolved += 1
            correct += result.candidate.id == case.expected_id
        elif result.status == "resolved":
            silent_drops += 1
    total = len(CASES)
    return {
        "bind_precision": correct / resolved if resolved else 0.0,
        "bind_recall": correct / total,
        "silent_drop_rate": silent_drops / total,
        "unresolved_rate": (total - resolved) / total,
    }
