"""Load .env into the process environment for host/CLI runs.

Importing this module loads the project's `.env` (gitignored). It is loaded by
absolute path (relative to this file), so `python -m opener.cli...` picks up
credentials regardless of the current working directory.

`load_dotenv` does NOT override variables already present, so:
  - In Docker, compose-injected env vars win (importing this is a no-op).
  - Under tests, values set by the test runner / monkeypatch win.
"""
from pathlib import Path

from dotenv import load_dotenv

# src/opener/core/config.py -> project root is parents[3]
_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_ENV_PATH)
