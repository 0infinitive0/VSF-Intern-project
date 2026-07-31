"""Deterministic intake gate: validating the 3 required trip facts, and
recognizing an explicit finalization request. Neither talks to the LLM."""

from __future__ import annotations


def validate_trip_basics(destination: str, duration: str, people: str) -> tuple[str | None, str | None]:
    """Validate the 3 required trip facts and clean the destination string.

    Returns (cleaned_destination, None) on success, or (None, error_message) on failure —
    error_message is a ready-to-return "SYSTEM ERROR: ..." string.
    """
    missing = []
    if not destination or destination.lower() in ["unknown", "chưa rõ", "none"]:
        missing.append("destination")
    if not duration or duration.lower() in ["unknown", "chưa rõ", "none"]:
        missing.append("duration")
    if not people or people.lower() in ["unknown", "chưa rõ", "none"]:
        missing.append("people")
    if missing:
        return None, (
            f"SYSTEM ERROR: You cannot plan the itinerary yet. You are missing: {', '.join(missing)}. "
            "DO NOT guess. Reply to the user in friendly Vietnamese asking for this specific information "
            "without saying 'Xin lỗi'."
        )

    dest_clean = destination.lower()
    for phrase in ["đi 1 mình", "một mình", "1 mình", "đi 1 nguoi", "1 người", "với vợ", "đi với vợ", "ễới màn", "ễới"]:
        dest_clean = dest_clean.replace(phrase, "")
    dest_clean = dest_clean.strip(" .-,_")

    if not dest_clean or len(dest_clean) < 2:
        return None, "SYSTEM ERROR: Điểm đến không hợp lệ. Hãy cung cấp tên thành phố hoặc tỉnh cụ thể."

    return dest_clean.title(), None


def is_finalization_request(message: str) -> bool:
    normalized = message.casefold().strip()
    return any(
        phrase in normalized
        for phrase in ("finalize", "confirm trip", "chốt lịch trình", "chot lich trinh", "xác nhận lịch")
    )
