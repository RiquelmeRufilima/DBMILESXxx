from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent.parent
IS_VERCEL = bool(os.getenv("VERCEL"))
if load_dotenv:
    load_dotenv(BASE_DIR / ".env")

APP_DIR = BASE_DIR / "app"
BUNDLED_DATA_DIR = BASE_DIR / "data"
BUNDLED_UPLOAD_DIR = BASE_DIR / "uploads"

STORAGE_POINTER_FILE = BASE_DIR / "ARMAZENAMENTO_DBMILESX.txt"


def _storage_root_from_pointer() -> Path | None:
    """Lê o armazenamento externo sem misturar dados com o código do app."""
    if not STORAGE_POINTER_FILE.exists():
        return None
    try:
        raw = STORAGE_POINTER_FILE.read_text(encoding="utf-8-sig").strip().strip('"')
    except OSError:
        return None
    if not raw:
        return None
    path = Path(os.path.expandvars(raw)).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


_persistent_root_raw = os.getenv("PERSISTENT_ROOT", "").strip()
if _persistent_root_raw:
    PERSISTENT_ROOT = Path(_persistent_root_raw).expanduser().resolve()
elif IS_VERCEL:
    # O código da Function não deve ser usado como armazenamento gravável.
    # /tmp existe para arquivos temporários, logs e cache da instância.
    PERSISTENT_ROOT = Path("/tmp/dbmilesx")
else:
    PERSISTENT_ROOT = _storage_root_from_pointer()

# Em hospedagem, dados e imagens ficam no volume persistente. No computador
# local, o atualizador pode apontar para DBMILESX_ARMAZENAMENTO, fora de app/.
DATA_DIR = (PERSISTENT_ROOT / "data") if PERSISTENT_ROOT else BUNDLED_DATA_DIR
UPLOAD_DIR = (PERSISTENT_ROOT / "uploads") if PERSISTENT_ROOT else BUNDLED_UPLOAD_DIR

AIRLINE_UPLOAD_DIR = UPLOAD_DIR / "airlines"
PROFILE_UPLOAD_DIR = UPLOAD_DIR / "profiles"
COMPANY_UPLOAD_DIR = UPLOAD_DIR / "companies"
GROUP_UPLOAD_DIR = UPLOAD_DIR / "group_documents"
CHAT_UPLOAD_DIR = UPLOAD_DIR / "chat"
TASK_UPLOAD_DIR = UPLOAD_DIR / "tasks"
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"
AIRLINE_IMAGE_DIR = APP_DIR / "imagens"
LOCAL_CONTROL_HASH_FILE = DATA_DIR / ".local_control_hash"


def _copy_missing_tree(source: Path, destination: Path) -> None:
    """Copia apenas arquivos ausentes, sem sobrescrever dados já alterados."""
    if not source.exists() or source.resolve() == destination.resolve():
        return
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _bootstrap_storage() -> None:
    for directory in (
        DATA_DIR,
        UPLOAD_DIR,
        AIRLINE_UPLOAD_DIR,
        PROFILE_UPLOAD_DIR,
        COMPANY_UPLOAD_DIR,
        GROUP_UPLOAD_DIR,
        CHAT_UPLOAD_DIR,
        TASK_UPLOAD_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    if not PERSISTENT_ROOT:
        return

    # Primeiro deploy no Render: leva o banco e as imagens do pacote para o disco.
    bundled_db = BUNDLED_DATA_DIR / "dbmilesx_web.db"
    persistent_db = DATA_DIR / "dbmilesx_web.db"
    if bundled_db.exists() and not persistent_db.exists():
        persistent_db.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bundled_db, persistent_db)

    _copy_missing_tree(BUNDLED_UPLOAD_DIR, UPLOAD_DIR)


_bootstrap_storage()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "sim", "on"}


def _secret_key() -> str:
    env_value = os.getenv("SECRET_KEY", "").strip()
    if env_value:
        return env_value

    if IS_VERCEL:
        raise RuntimeError(
            "SECRET_KEY não configurada. No Vercel, crie a variável SECRET_KEY "
            "em Project Settings > Environment Variables."
        )

    key_file = DATA_DIR / ".secret_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()

    value = secrets.token_urlsafe(48)
    key_file.write_text(value, encoding="utf-8")
    return value


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        if IS_VERCEL and os.getenv("VERCEL_ALLOW_EPHEMERAL_SQLITE", "").strip().lower() not in {"1", "true", "yes", "sim", "on"}:
            raise RuntimeError(
                "DATABASE_URL não configurada. O Vercel não deve usar SQLite como banco "
                "persistente. Configure um PostgreSQL em Project Settings > Environment Variables."
            )

        # Banco oficial da instalação local. No Vercel, este fallback só é
        # permitido explicitamente para testes temporários.
        canonical = DATA_DIR / "dbmilesx_web.db"
        if canonical.exists():
            return f"sqlite:///{canonical.as_posix()}"

        legacy_names = [
            DATA_DIR / "dbmilesx_web-ISIVIAGENS04.db",
            DATA_DIR / "dbmilesx_web-ISIVIAGENS03-2.db",
            DATA_DIR / "dbmilesx_web-ISIVIAGENS03.db",
        ]
        for candidate in legacy_names:
            if candidate.exists():
                return f"sqlite:///{candidate.as_posix()}"

        dbs = sorted(
            DATA_DIR.glob("*.db"),
            key=lambda p: (p.stat().st_mtime, p.stat().st_size),
            reverse=True,
        )
        if dbs:
            return f"sqlite:///{dbs[0].as_posix()}"
        return f"sqlite:///{canonical.as_posix()}"

    # Compatibilidade com URLs fornecidas pelo Render Postgres.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


SECRET_KEY = _secret_key()
DATABASE_URL = _database_url()
APP_NAME = os.getenv("APP_NAME", "DBMILESX")
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV in {"production", "prod"} or bool(os.getenv("RENDER")) or IS_VERCEL
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
_vercel_host = os.getenv("VERCEL_PROJECT_PRODUCTION_URL") or os.getenv("VERCEL_URL")
APP_URL = (
    os.getenv("APP_URL")
    or os.getenv("RENDER_EXTERNAL_URL")
    or (f"https://{_vercel_host}" if _vercel_host else None)
    or f"http://127.0.0.1:{APP_PORT}"
)
SESSION_COOKIE = os.getenv("SESSION_COOKIE", "dbmilesx_session")
DEBUG = _env_bool("DEBUG", False)
SESSION_HTTPS_ONLY = _env_bool("SESSION_HTTPS_ONLY", IS_PRODUCTION)

# Em Vercel, tarefas pesadas de manutenção não precisam rodar em todo cold start.
RUN_FULL_STARTUP_MAINTENANCE = _env_bool("RUN_FULL_STARTUP_MAINTENANCE", not IS_PRODUCTION)

# Uploads no filesystem do Vercel não são persistentes. Deixamos bloqueado por
# padrão; ative apenas para testes temporários.
EPHEMERAL_UPLOADS_ENABLED = _env_bool("EPHEMERAL_UPLOADS_ENABLED", not IS_VERCEL)

# Novas contas são criadas pelo acesso principal; cadastro público fica fechado.
REGISTRATION_ENABLED = _env_bool("REGISTRATION_ENABLED", False)
MAX_TEAM_USERS = max(1, int(os.getenv("MAX_TEAM_USERS", "10")))

# O painel mestre só existe no computador local e não aparece nas interfaces.
LOCAL_ADMIN_ENABLED = _env_bool("LOCAL_ADMIN_ENABLED", not IS_PRODUCTION)

# Integração Amadeus (somente leitura por padrão).
AMADEUS_ENABLED = _env_bool("AMADEUS_ENABLED", False)
AMADEUS_ENV = os.getenv("AMADEUS_ENV", "test").strip().lower()
AMADEUS_CLIENT_ID = os.getenv("AMADEUS_CLIENT_ID", "").strip()
AMADEUS_CLIENT_SECRET = os.getenv("AMADEUS_CLIENT_SECRET", "").strip()
AMADEUS_TIMEOUT_SECONDS = max(5, int(os.getenv("AMADEUS_TIMEOUT_SECONDS", "25")))

LEGACY_DB_CANDIDATES = [
    BASE_DIR / "sistema_aereo_secure.db",
    BASE_DIR.parent / "sistema_aereo_secure.db",
]


def find_legacy_database() -> Path | None:
    explicit = os.getenv("LEGACY_DB_PATH")
    if explicit:
        path = Path(explicit).expanduser().resolve()
        return path if path.exists() else None

    for path in LEGACY_DB_CANDIDATES:
        if path.exists():
            return path
    return None
