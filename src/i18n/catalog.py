"""Per-language gettext translators, cached by language code.

Not gettext.install() — that mutates a process-global translator, which is
wrong for a server handling concurrent requests in different languages.
Each call to t() looks up (or lazily builds) a NullTranslations-falling-back
translator bound to one language.
"""
import gettext
from functools import lru_cache
from pathlib import Path

_LOCALE_DIR = Path(__file__).resolve().parent.parent.parent / "locales"
_DOMAIN = "messages"
SUPPORTED_LANGUAGES = ("vi", "en")
DEFAULT_LANGUAGE = "vi"


@lru_cache(maxsize=len(SUPPORTED_LANGUAGES))
def _translator(language: str) -> gettext.NullTranslations:
    try:
        return gettext.translation(_DOMAIN, localedir=str(_LOCALE_DIR), languages=[language])
    except FileNotFoundError:
        return gettext.NullTranslations()  # returns msgid unchanged


def t(key: str, language: str | None, **kwargs: object) -> str:
    lang = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    translated = _translator(lang).gettext(key)
    return translated.format(**kwargs) if kwargs else translated
