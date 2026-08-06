"""Backend i18n surface — the only import point for other modules.

`t(key, language, **kwargs)` returns the `vi` catalog value when given
`"vi"` (or an unrecognized language) and the `en` value for `"en"`,
mirroring the frontend's `fallbackLng: "vi"`. The Vietnamese source text is
the msgid (gettext convention), so a missing English translation degrades to
showing the Vietnamese source rather than leaking a symbolic key to the UI.
"""
from src.i18n.catalog import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, t

__all__ = ["t", "SUPPORTED_LANGUAGES", "DEFAULT_LANGUAGE"]