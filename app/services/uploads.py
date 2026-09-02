from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import UploadFile

from ..config import BASE_DIR, UPLOAD_DIR

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
AIRLINE_IMAGE_EXTENSIONS = IMAGE_EXTENSIONS | {".svg"}
CHAT_ATTACHMENT_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}


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
) -> dict[str, object] | None:
    """Salva um anexo da cotação e devolve metadados seguros.

    O arquivo fica dentro de uploads/quotes/<id>, enquanto o AcceptedQuote guarda
    somente caminho/nome/tipo/tamanho no JSON já existente. Assim não é preciso
    alterar a estrutura do banco e instalações antigas continuam compatíveis.
    """
    filename = str(getattr(upload, "filename", "") or "").strip()
    if upload is None or not filename:
        return None

    extension = Path(filename).suffix.lower()
    if extension not in QUOTE_ATTACHMENT_EXTENSIONS:
        readable = ", ".join(sorted(ext.lstrip(".").upper() for ext in QUOTE_ATTACHMENT_EXTENSIONS))
        raise ValueError(f"Formato não permitido. Use um destes formatos: {readable}.")

    content = await upload.read()
    if not content:
        raise ValueError(f"O arquivo {Path(filename).name} está vazio.")
    if len(content) > max_bytes:
        raise ValueError(f"Cada anexo deve ter no máximo {max_bytes // (1024 * 1024)} MB.")

    target_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"quote-{secrets.token_hex(16)}{extension}"
    target = target_dir / stored_name
    target.write_bytes(content)

    try:
        relative = target.resolve().relative_to(UPLOAD_DIR.resolve())
    except ValueError as exc:
        target.unlink(missing_ok=True)
        raise ValueError("A pasta escolhida para o anexo não pertence aos uploads do sistema.") from exc

    return {
        "id": secrets.token_hex(12),
        "path": f"uploads/{relative.as_posix()}",
        "name": Path(filename).name[:255],
        "type": str(getattr(upload, "content_type", "") or "application/octet-stream")[:120],
        "size": len(content),
        "extension": extension,
    }
