from __future__ import annotations

import os
from dataclasses import dataclass, asdict

from ..config import (
    IS_VERCEL, FILE_STORAGE_PROVIDER, FILE_STORAGE_PUBLIC_URL,
    FILE_STORAGE_BUCKET, FILE_STORAGE_ENDPOINT,
)


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


def storage_status() -> StorageStatus:
    provider = (FILE_STORAGE_PROVIDER or "local").lower()
    labels = {
        "local": "Filesystem local",
        "vercel_blob": "Vercel Blob",
        "s3": "Amazon S3 / compatível",
        "r2": "Cloudflare R2",
    }
    label = labels.get(provider, provider.replace("_", " ").title())

    if provider == "local":
        persistent = not IS_VERCEL
        return StorageStatus(
            provider=provider, label=label, database="Neon PostgreSQL / DATABASE_URL",
            files_ready=persistent, persistent=persistent,
            message=(
                "Pronto para uso local." if persistent else
                "Banco Neon é persistente, mas uploads ainda precisam de Vercel Blob, S3 ou R2 para persistir no Vercel."
            ),
        )

    # Estrutura preparada para um adapter externo. A tela só marca como pronta
    # quando as variáveis mínimas do provedor foram definidas.
    token_ready = bool(
        os.getenv("BLOB_READ_WRITE_TOKEN")
        or os.getenv("AWS_ACCESS_KEY_ID")
        or os.getenv("S3_ACCESS_KEY_ID")
        or os.getenv("R2_ACCESS_KEY_ID")
    )
    location_ready = bool(FILE_STORAGE_PUBLIC_URL or FILE_STORAGE_BUCKET or FILE_STORAGE_ENDPOINT)
    ready = token_ready and location_ready
    return StorageStatus(
        provider=provider, label=label, database="Neon PostgreSQL / DATABASE_URL",
        files_ready=ready, persistent=True, public_url=FILE_STORAGE_PUBLIC_URL, bucket=FILE_STORAGE_BUCKET,
        message=(
            "Variáveis do armazenamento externo detectadas. Adapter pronto para ativação." if ready else
            "Estrutura preparada. Falta configurar as credenciais/URL do provedor externo na Vercel."
        ),
    )
