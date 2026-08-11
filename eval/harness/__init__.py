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

import sys
from pathlib import Path

from dotenv import load_dotenv

_BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"

load_dotenv(_BACKEND_DIR / ".env")

if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
