from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from urllib.parse import quote
from urllib.request import Request as UrlRequest, urlopen
from urllib.error import HTTPError, URLError

from ..config import (
    IS_VERCEL, FILE_STORAGE_PROVIDER, FILE_STORAGE_PUBLIC_URL,
    FILE_STORAGE_BUCKET, FILE_STORAGE_ENDPOINT,
)

BLOB_API = "https://vercel.com/api/blob"


@dataclass
class StorageStatus:
    provider: str
    label: str
    database: str
    files_ready: bool
    persistent: bool
    message: str
    public_url: str = ""
    bucket: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _blob_token() -> str:
    # O store atual possui read-write token. O fallback OIDC permite evolução
    # futura sem alterar a interface do restante do DBMILESX.
    return (os.getenv("BLOB_READ_WRITE_TOKEN") or os.getenv("VERCEL_OIDC_TOKEN") or "").strip()


def _blob_store_id() -> str:
    return (os.getenv("BLOB_STORE_ID") or "").strip()


def blob_ready() -> bool:
    return bool(_blob_token() and _blob_store_id())


def _blob_headers(*, content_type: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_blob_token()}",
        "x-vercel-blob-store-id": _blob_store_id(),
        "x-api-version": "12",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _blob_error(exc: Exception) -> RuntimeError:
    if isinstance(exc, HTTPError):
        try:
            detail = exc.read().decode("utf-8", "replace")[:600]
        except Exception:
            detail = ""
        return RuntimeError(f"Vercel Blob respondeu HTTP {exc.code}. {detail}".strip())
    return RuntimeError(f"Falha ao acessar o Vercel Blob: {exc}")


def blob_put(pathname: str, content: bytes, content_type: str = "application/octet-stream") -> dict:
    """Grava bytes no Vercel Blob privado e devolve os metadados do Blob."""
    if not blob_ready():
        raise RuntimeError("Vercel Blob não está configurado neste ambiente.")
    clean = str(pathname or "").strip().strip("/")
    if not clean:
        raise ValueError("Caminho do Blob inválido.")
    url = f"{BLOB_API}/?pathname={quote(clean, safe='/')}"
    headers = _blob_headers(content_type=content_type)
    headers.update({
        "x-vercel-blob-access": "private",
        "x-add-random-suffix": "0",
        "x-content-type": content_type or "application/octet-stream",
    })
    req = UrlRequest(url, data=content, headers=headers, method="PUT")
    try:
        with urlopen(req, timeout=30) as res:
            payload = json.loads(res.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else {"url": str(payload)}
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise _blob_error(exc) from exc


def blob_get(blob_url: str) -> tuple[bytes, str]:
    """Lê um arquivo privado via servidor, sem expor credenciais ao navegador."""
    if not blob_ready():
        raise RuntimeError("Vercel Blob não está configurado neste ambiente.")
    url = str(blob_url or "").strip()
    if not url.startswith("https://"):
        raise ValueError("URL do Blob inválida.")
    sep = "&" if "?" in url else "?"
    req = UrlRequest(f"{url}{sep}cache=0", headers={"Authorization": f"Bearer {_blob_token()}"}, method="GET")
    try:
        with urlopen(req, timeout=30) as res:
            return res.read(), str(res.headers.get("Content-Type") or "application/octet-stream")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise _blob_error(exc) from exc


def blob_delete(blob_url: str) -> None:
    """Exclui um Blob privado pela URL devolvida no upload."""
    if not blob_ready() or not blob_url:
        return
    body = json.dumps({"urls": [str(blob_url)]}).encode("utf-8")
    req = UrlRequest(
        f"{BLOB_API}/delete",
        data=body,
        headers=_blob_headers(content_type="application/json"),
        method="POST",
    )
    try:
        with urlopen(req, timeout=30):
            return
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise _blob_error(exc) from exc


def storage_status() -> StorageStatus:
    provider = (FILE_STORAGE_PROVIDER or "local").lower()
    # Se o projeto já estiver conectado ao Blob, detecta automaticamente mesmo
    # que FILE_STORAGE_PROVIDER ainda esteja com o valor antigo "local".
    if blob_ready():
        provider = "vercel_blob"
    labels = {
        "local": "Filesystem local",
        "vercel_blob": "Vercel Blob privado",
        "s3": "Amazon S3 / compatível",
        "r2": "Cloudflare R2",
    }
    label = labels.get(provider, provider.replace("_", " ").title())

    if provider == "vercel_blob":
        return StorageStatus(
            provider=provider,
            label=label,
            database="Neon PostgreSQL / DATABASE_URL",
            files_ready=blob_ready(),
            persistent=True,
            message=(
                "Vercel Blob privado conectado e pronto para anexos persistentes."
                if blob_ready() else
                "Blob selecionado, mas BLOB_STORE_ID/credencial ainda não foram detectados."
            ),
            bucket=_blob_store_id(),
        )

    if provider == "local":
        persistent = not IS_VERCEL
        return StorageStatus(
            provider=provider, label=label, database="Neon PostgreSQL / DATABASE_URL",
            files_ready=persistent, persistent=persistent,
            message=("Pronto para uso local." if persistent else
                     "Uploads locais não são persistentes no Vercel. Conecte Vercel Blob, S3 ou R2."),
        )

    token_ready = bool(os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("S3_ACCESS_KEY_ID") or os.getenv("R2_ACCESS_KEY_ID"))
    location_ready = bool(FILE_STORAGE_PUBLIC_URL or FILE_STORAGE_BUCKET or FILE_STORAGE_ENDPOINT)
    ready = token_ready and location_ready
    return StorageStatus(
        provider=provider, label=label, database="Neon PostgreSQL / DATABASE_URL",
        files_ready=ready, persistent=True, public_url=FILE_STORAGE_PUBLIC_URL, bucket=FILE_STORAGE_BUCKET,
        message=("Variáveis do armazenamento externo detectadas." if ready else
                 "Estrutura preparada. Falta configurar as credenciais/URL do provedor externo."),
    )
