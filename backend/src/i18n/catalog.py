"""Per-language gettext translators, cached by language code."""

import gettext
from functools import lru_cache
from pathlib import Path

_LOCALE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "locales"
_DOMAIN = "messages"
SUPPORTED_LANGUAGES = ("vi", "en")
DEFAULT_LANGUAGE = "vi"


@lru_cache(maxsize=len(SUPPORTED_LANGUAGES))
def _translator(language: str) -> gettext.NullTranslations:
    try:
        return gettext.translation(_DOMAIN, localedir=str(_LOCALE_DIR), languages=[language])
    except FileNotFoundError:
        return gettext.NullTranslations()


def t(key: str, language: str | None, **kwargs: object) -> str:
    lang = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    translated = _translator(lang).gettext(key)
    return translated.format(**kwargs) if kwargs else translated
