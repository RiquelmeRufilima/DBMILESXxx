from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import UploadFile

from ..config import BASE_DIR, UPLOAD_DIR, IS_VERCEL, EPHEMERAL_UPLOADS_ENABLED
from .storage import blob_ready, blob_put, blob_get, blob_delete

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
AIRLINE_IMAGE_EXTENSIONS = IMAGE_EXTENSIONS | {".svg"}
CHAT_ATTACHMENT_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}


def _hosted_upload_limit(max_bytes: int) -> int:
    if IS_VERCEL:
        # O payload das Vercel Functions tem limite baixo. Mantemos margem para
        # multipart, campos do formulário e headers.
        return min(max_bytes, 4 * 1024 * 1024)
    return max_bytes


def _ensure_upload_storage_available() -> None:
    if IS_VERCEL and not blob_ready() and not EPHEMERAL_UPLOADS_ENABLED:
        raise ValueError(
            "Uploads persistentes ainda não estão configurados no Vercel. "
            "Conecte o Vercel Blob ou, somente para teste temporário, ative "
            "EPHEMERAL_UPLOADS_ENABLED=true."
        )


async def save_upload_image(
    upload: UploadFile | None,
    target_dir: Path,
    *,
    max_bytes: int = 6 * 1024 * 1024,
    allowed_extensions: set[str] | None = None,
    filename_prefix: str = "img",
) -> str | None:
    """Salva uma imagem e devolve a URL relativa /uploads/...

    O caminho físico pode estar no projeto local ou em um disco persistente externo,
    como /var/data no Render. A URL pública permanece igual nos dois ambientes.
    """
    filename = str(getattr(upload, "filename", "") or "").strip()
    if upload is None or not filename:
        return None
    _ensure_upload_storage_available()
    max_bytes = _hosted_upload_limit(max_bytes)

    allowed = allowed_extensions or IMAGE_EXTENSIONS
    extension = Path(filename).suffix.lower()
    if extension not in allowed:
        readable = ", ".join(sorted(ext.lstrip(".").upper() for ext in allowed))
        raise ValueError(f"Use uma imagem nos formatos: {readable}.")

    content = await upload.read()
    if not content:
        raise ValueError("A imagem enviada está vazia.")
    if len(content) > max_bytes:
        raise ValueError(f"A imagem deve ter no máximo {max_bytes // (1024 * 1024)} MB.")

    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{filename_prefix}-{secrets.token_hex(12)}{extension}"
    target = target_dir / filename
    target.write_bytes(content)

    try:
        relative = target.resolve().relative_to(UPLOAD_DIR.resolve())
    except ValueError as exc:
        target.unlink(missing_ok=True)
        raise ValueError("A pasta escolhida para a imagem não pertence aos uploads do sistema.") from exc
    return f"uploads/{relative.as_posix()}"


def delete_relative_upload(relative_path: str | None) -> None:
    """Remove apenas arquivos localizados dentro da pasta oficial de uploads."""
    if not relative_path:
        return
    try:
        normalized = str(relative_path).replace("\\", "/").lstrip("/")
        if normalized.startswith("uploads/"):
            candidate = UPLOAD_DIR / normalized[len("uploads/") :]
        else:
            # Compatibilidade com registros muito antigos salvos como caminho do projeto.
            candidate = BASE_DIR / normalized

        path = candidate.resolve()
        path.relative_to(UPLOAD_DIR.resolve())
        if path.exists() and path.is_file():
            path.unlink()
    except Exception:
        # Falha de limpeza nunca deve derrubar o fluxo principal.
        return


async def save_chat_attachment(
    upload: UploadFile | None,
    target_dir: Path,
    *,
    max_bytes: int = 12 * 1024 * 1024,
) -> dict[str, object] | None:
    """Salva imagem ou PDF do chat com nome aleatório e metadados seguros."""
    if upload is None or not upload.filename:
        return None
    _ensure_upload_storage_available()
    max_bytes = _hosted_upload_limit(max_bytes)
    extension = Path(upload.filename).suffix.lower()
    if extension not in CHAT_ATTACHMENT_EXTENSIONS:
        raise ValueError("No chat, envie somente PNG, JPG, JPEG, WEBP ou PDF.")
    content = await upload.read()
    if not content:
        raise ValueError("O arquivo enviado está vazio.")
    if len(content) > max_bytes:
        raise ValueError(f"O arquivo deve ter no máximo {max_bytes // (1024 * 1024)} MB.")
    declared = str(getattr(upload, "content_type", "") or "").lower()
    if extension == ".pdf" and declared and "pdf" not in declared:
        raise ValueError("O arquivo selecionado não parece ser um PDF válido.")
    if extension in IMAGE_EXTENSIONS and declared and not declared.startswith("image/"):
        raise ValueError("O arquivo selecionado não parece ser uma imagem válida.")
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"chat-{secrets.token_hex(16)}{extension}"
    target = target_dir / stored_name
    target.write_bytes(content)
    relative = target.resolve().relative_to(UPLOAD_DIR.resolve())
    original_name = Path(upload.filename).name[:255]
    mime = "application/pdf" if extension == ".pdf" else (declared or f"image/{extension.lstrip('.')}")
    return {
        "path": f"uploads/{relative.as_posix()}",
        "name": original_name,
        "type": mime[:80],
        "size": len(content),
    }

# Arquivos aceitos nos anexos das cotações/reservas.
QUOTE_ATTACHMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".rtf",
    ".odt", ".ods", ".ppt", ".pptx", ".json", ".xml", ".zip",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".ico", ".svg",
}


async def save_quote_attachment(
    upload: UploadFile | None,
    target_dir: Path,
    *,
    max_bytes: int = 25 * 1024 * 1024,
    blob_path_prefix: str | None = None,
) -> dict[str, object] | None:
    """Salva anexo de cotação no Blob quando disponível; local como fallback.

    O AcceptedQuote continua guardando apenas metadados no JSON existente,
    portanto esta integração não exige criar tabela nova no Neon.
    """
    filename = str(getattr(upload, "filename", "") or "").strip()
    if upload is None or not filename:
        return None
    _ensure_upload_storage_available()
    max_bytes = _hosted_upload_limit(max_bytes)

    extension = Path(filename).suffix.lower()
    if extension not in QUOTE_ATTACHMENT_EXTENSIONS:
        readable = ", ".join(sorted(ext.lstrip(".").upper() for ext in QUOTE_ATTACHMENT_EXTENSIONS))
        raise ValueError(f"Formato não permitido. Use um destes formatos: {readable}.")

    content = await upload.read()
    if not content:
        raise ValueError(f"O arquivo {Path(filename).name} está vazio.")
    if len(content) > max_bytes:
        raise ValueError(f"Cada anexo deve ter no máximo {max_bytes // (1024 * 1024)} MB.")

    stored_name = f"quote-{secrets.token_hex(16)}{extension}"
    original_name = Path(filename).name[:255]
    mime = str(getattr(upload, "content_type", "") or "application/octet-stream")[:120]
    entry_id = secrets.token_hex(12)

    if blob_ready():
        prefix = (blob_path_prefix or "quotes").strip().strip("/")
        pathname = f"{prefix}/{stored_name}"
        try:
            result = blob_put(pathname, content, mime)
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc
        return {
            "id": entry_id,
            "path": pathname,
            "blob_url": str(result.get("url") or result.get("downloadUrl") or ""),
            "storage": "vercel_blob",
            "name": original_name,
            "type": mime,
            "size": len(content),
            "extension": extension,
        }

    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / stored_name
    target.write_bytes(content)
    try:
        relative = target.resolve().relative_to(UPLOAD_DIR.resolve())
    except ValueError as exc:
        target.unlink(missing_ok=True)
        raise ValueError("A pasta escolhida para o anexo não pertence aos uploads do sistema.") from exc
    return {
        "id": entry_id,
        "path": f"uploads/{relative.as_posix()}",
        "storage": "local",
        "name": original_name,
        "type": mime,
        "size": len(content),
        "extension": extension,
    }


def delete_stored_attachment(entry: dict[str, object] | None) -> None:
    if not isinstance(entry, dict):
        return
    if str(entry.get("storage") or "") == "vercel_blob":
        url = str(entry.get("blob_url") or "")
        if url:
            try:
                blob_delete(url)
            except Exception:
                pass
        return
    delete_relative_upload(str(entry.get("path") or ""))


def read_stored_attachment(entry: dict[str, object]) -> tuple[bytes, str]:
    if str(entry.get("storage") or "") == "vercel_blob":
        url = str(entry.get("blob_url") or "")
        if not url:
            raise FileNotFoundError("Anexo sem URL do Blob.")
        return blob_get(url)

    normalized = str(entry.get("path") or "").replace("\\", "/").lstrip("/")
    candidate = UPLOAD_DIR / normalized[len("uploads/"):] if normalized.startswith("uploads/") else BASE_DIR / normalized
    path = candidate.resolve()
    path.relative_to(UPLOAD_DIR.resolve())
    if not path.exists() or not path.is_file():
        raise FileNotFoundError("Anexo não encontrado.")
    return path.read_bytes(), str(entry.get("type") or "application/octet-stream")

