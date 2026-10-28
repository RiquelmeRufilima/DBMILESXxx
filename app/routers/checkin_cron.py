"""Execução agendada em produção; endpoint nunca é público sem CRON_SECRET."""
from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..services.checkin_reminders import process_checkin_reminders

router = APIRouter(tags=["check-in"])


@router.get("/internal/cron/checkin")
def checkin_cron(request: Request, db: Session = Depends(get_db)):
    expected = os.getenv("CRON_SECRET", "").strip()
    received = request.headers.get("authorization", "")
    if not expected or not secrets.compare_digest(received, f"Bearer {expected}"):
        return JSONResponse({"ok": False}, status_code=401)
    return {"ok": True, **process_checkin_reminders(db)}
