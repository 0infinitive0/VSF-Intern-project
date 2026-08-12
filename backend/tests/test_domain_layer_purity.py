"""Fails if any module under `src/domain/` imports upward (`services`,
`agents`, `api`), Supabase, or an LLM client. Static AST check, not a real
import, so it never needs credentials or network access — the same reason
`domain/` itself has none. See `ARCHITECTURE.md` § Layer Architecture &
Import Rules."""

from __future__ import annotations

import ast
from pathlib import Path

_DOMAIN_DIR = Path(__file__).resolve().parents[1] / "src" / "domain"

# Prefix-matched against each imported module's dotted name.
_FORBIDDEN_PREFIXES = (
    "src.services",
    "src.agents",
    "src.api",
    "supabase",
    "langchain",  # langchain_core / langchain_openai / langchain_ollama
    "langgraph",
    "openai",
    "ollama",
    "anthropic",
)


def _imported_module_names(source: str) -> set[str]:
    """Absolute import targets, plus a synthetic `<escapes-package>` marker for
    any relative import with level >= 2 (`from .. import x` / `from ..services
    import x`) — from a module directly inside `src/domain/`, that resolves to
    `src` or above, which is exactly how an upward import could hide from a
    prefix check that only looks at absolute dotted names. `level == 1`
    (`from . import sibling`) stays within `src.domain` itself and is fine."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level >= 2:
                names.add("<escapes-package>")
            elif node.level == 0 and node.module:
                names.add(node.module)
    return names


def _forbidden_imports(module_names: set[str]) -> set[str]:
    if "<escapes-package>" in module_names:
        return {"<escapes-package>"}
    return {
        name
        for name in module_names
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in _FORBIDDEN_PREFIXES)
    }


def test_domain_layer_has_no_upward_or_infrastructure_imports() -> None:
    domain_files = sorted(_DOMAIN_DIR.rglob("*.py"))
    assert domain_files, f"expected at least one module under {_DOMAIN_DIR}"

    violations: dict[str, set[str]] = {}
    for file_path in domain_files:
        module_names = _imported_module_names(file_path.read_text(encoding="utf-8"))
        forbidden = _forbidden_imports(module_names)
        if forbidden:
            violations[str(file_path.relative_to(_DOMAIN_DIR.parents[1]))] = forbidden

    assert not violations, f"domain layer must not import upward or infra modules: {violations}"
