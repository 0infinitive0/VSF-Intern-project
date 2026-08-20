"""RAGAS eval harness. Importing this package puts backend/ on sys.path so
`src.services...` imports resolve regardless of the caller's cwd, and loads
backend/.env before anything else touches src.config.get_settings().

Order matters here: src.config.Settings() reads os.environ at construction
time and get_settings() is @lru_cache'd, so whichever happens first -
backend/.env being loaded, or the first get_settings() call anywhere in the
process - wins for the rest of the process. Only src/services/llm.py calls
load_dotenv() in the backend itself, so a harness script that imports e.g.
src.agents.session before anything that happens to import src.services.llm
would otherwise get Settings() built from bare shell env (provider defaults
to "ollama", model to "llama3.1") and silently fail every OpenAI call for
the rest of the run. Loading .env here, unconditionally, before backend/ is
even on sys.path, removes the dependence on import order entirely.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"

# override=True is not optional: load_dotenv leaves an already-exported variable
# alone, so an ambient LLM_MODEL/EMBEDDING_PROVIDER in the operator's shell (or a
# root-level .env sourced into it) silently wins over backend/.env and makes the
# eval measure a model the app does not run — observed: gpt-4o-mini scored in place
# of the configured gpt-5.1, with no error and no visible difference in the output.
load_dotenv(_BACKEND_DIR / ".env", override=True)

# AFTER load_dotenv, never before: backend/.env sets SESSION_PERSISTENCE_ENABLED=true,
# and with override=True it would win over anything set here first.
#
# `routes._persistence_enabled` (api/routes.py) is read once at import from
# `Settings`, and gates both `_persist_turn` and the registry's load/delete hooks.
# An eval run replays scripted conversations through the production turn driver, so
# without this every replay writes session rows and transcripts into the real store
# under a `ragas-eval-` id. Setting it here — before backend/ is even importable —
# is the only placement that cannot lose a race with an import of `routes`.
# `e2e_eval.py` asserts the flag actually took effect rather than trusting this line.
os.environ["SESSION_PERSISTENCE_ENABLED"] = "false"

if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
