"""Backend i18n surface — the only import point for other modules."""

from src.i18n.catalog import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, t

__all__ = ["t", "SUPPORTED_LANGUAGES", "DEFAULT_LANGUAGE"]
