"""Configure um SQLite temporário antes que o pytest importe a aplicação."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TEST_STORAGE = tempfile.TemporaryDirectory(prefix="dbmilesx-pytest-")
_TEST_ROOT = Path(_TEST_STORAGE.name)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_ROOT / 'suite.sqlite3'}"
os.environ["PERSISTENT_ROOT"] = str(_TEST_ROOT)
os.environ["SECRET_KEY"] = "test-secret-key-only-for-pytest-1234567890"
os.environ["APP_ENV"] = "test"
os.environ["RUN_FULL_STARTUP_MAINTENANCE"] = "0"
os.environ["SESSION_HTTPS_ONLY"] = "0"
for _name in ("VERCEL", "BOOTSTRAP_ADMIN_EMAIL", "BOOTSTRAP_ADMIN_PASSWORD"):
    os.environ.pop(_name, None)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if "app.config" in sys.modules:
    raise RuntimeError("app.config foi carregado antes da configuração SQLite do pytest")
