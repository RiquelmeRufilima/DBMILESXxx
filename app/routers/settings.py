from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import current_user
from ..models import QuoteGroup, WebQuote, Person
from ..security import validate_csrf_token, verify_password
from ..services import mfa
from ..services.protection import register_attempt, seconds_until_allowed, client_ip
from ..services.storage import storage_status
from ..web import THEME_PRESETS, context, flash, templates

router = APIRouter(tags=["settings"])


def _settings(pref) -> dict:
    try:
        data = json.loads(pref.settings_json or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_settings(pref, updates: dict) -> None:
    data = _settings(pref)
    data.update(updates)
    pref.settings_json = json.dumps(data, ensure_ascii=False)


def _stats(db: Session, user) -> dict:
    if user.company_id:
        qfilter = QuoteGroup.company_id == user.company_id
        ofilter = WebQuote.company_id == user.company_id
        pfilter = Person.company_id == user.company_id
    else:
        qfilter = QuoteGroup.user_id == user.id
        ofilter = WebQuote.user_id == user.id
        pfilter = Person.user_id == user.id
    return {
        "quote_groups": int(db.scalar(select(func.count(QuoteGroup.id)).where(qfilter)) or 0),
        "quotes": int(db.scalar(select(func.count(WebQuote.id)).where(ofilter)) or 0),
        "persons": int(db.scalar(select(func.count(Person.id)).where(pfilter)) or 0),
    }


@router.get("/settings")
def settings_page(request: Request, tab: str = "appearance", db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    valid_tabs = {"appearance", "experience", "notifications", "security", "backup"}
    active_tab = tab if tab in valid_tabs else "appearance"
    return templates.TemplateResponse(
        request, "settings/index.html",
        context(request, user=user, active_settings_tab=active_tab, storage=storage_status().as_dict(), settings_stats=_stats(db,user), mfa_enabled=mfa.enabled(user), mfa_pending_secret=mfa.pending_secret(user), mfa_recovery_codes=request.session.pop("new_mfa_recovery_codes", [])),
    )


@router.get("/settings/appearance")
@router.get("/settings/notifications")
@router.get("/configuracoes")
@router.get("/configuracoes/estilos-formatacao")
@router.get("/configuracoes/estilos-de-formatacao")
def settings_alias_page(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/appearance")
def update_appearance(
    request: Request,
    theme_preset: str = Form("ocean"),
    accent_color: str = Form("#26c5e6"),
    background_style: str = Form("gradient"),
    compact_mode: str | None = Form(None),
    csrf_token: str = Form(...), db: Session = Depends(get_db),
):
    user = current_user(request, db)
    if user is None: return RedirectResponse("/login", status_code=303)
    if not validate_csrf_token(request.session, csrf_token):
        flash(request, "Sessão expirada.", "error"); return RedirectResponse("/settings", status_code=303)
    pref = user.preference
    pref.theme_preset = theme_preset if theme_preset in THEME_PRESETS else "ocean"
    pref.accent_color = accent_color if re.match(r"^#[0-9A-Fa-f]{6}$", accent_color) else THEME_PRESETS[pref.theme_preset]["primary"]
    pref.background_style = background_style if background_style in {"gradient","plain","soft"} else "gradient"
    pref.compact_mode = compact_mode == "on"
    db.commit(); flash(request, "Aparência atualizada.", "success")
    return RedirectResponse("/settings?tab=appearance", status_code=303)


@router.post("/settings/theme-mode")
async def update_theme_mode(request: Request, db: Session = Depends(get_db)):
    """Tema claro/escuro salvo na CONTA: celular e computador ficam iguais."""
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"ok": False}, status_code=401)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not validate_csrf_token(request.session, str(payload.get("csrf_token") or "")):
        return JSONResponse({"ok": False, "message": "Sessão expirada."}, status_code=403)
    mode = str(payload.get("mode") or "")
    if mode not in {"light", "dark", "system"}:
        return JSONResponse({"ok": False, "message": "Tema inválido."}, status_code=400)
    if user.preference is not None:
        user.preference.theme_mode = mode
        db.commit()
    return {"ok": True, "mode": mode}


@router.post("/settings/experience")
def update_experience(
    request: Request, default_page: str = Form("dashboard"), animations: str|None=Form(None),
    remember_last_tab: str|None=Form(None), show_top_search: str|None=Form(None),
    dense_tables: str|None=Form(None), csrf_token: str = Form(...), db: Session = Depends(get_db),
):
    user=current_user(request,db)
    if user is None:return RedirectResponse("/login",status_code=303)
    if not validate_csrf_token(request.session,csrf_token):
        flash(request,"Sessão expirada.","error");return RedirectResponse("/settings?tab=experience",status_code=303)
    _save_settings(user.preference,{
        "default_page": default_page if default_page in {"dashboard","quotes","calculator","tasks"} else "dashboard",
        "animations": animations=="on", "remember_last_tab": remember_last_tab=="on",
        "show_top_search": show_top_search=="on", "dense_tables": dense_tables=="on",
    })
    db.commit();flash(request,"Preferências de uso atualizadas.","success")
    return RedirectResponse("/settings?tab=experience",status_code=303)


@router.post("/settings/notifications")
def update_notification_preferences(
    request: Request, email_notifications: str|None=Form(None), in_app_notifications: str|None=Form(None),
    quote_updates: str|None=Form(None), task_reminders: str|None=Form(None), csrf_token: str=Form(...), db: Session=Depends(get_db),
):
    user=current_user(request,db)
    if user is None:return RedirectResponse("/login",status_code=303)
    if not validate_csrf_token(request.session,csrf_token):
        flash(request,"Sessão expirada.","error");return RedirectResponse("/settings?tab=notifications",status_code=303)
    user.preference.email_notifications=email_notifications=="on"
    user.preference.in_app_notifications=in_app_notifications=="on"
    _save_settings(user.preference,{"quote_updates":quote_updates=="on","task_reminders":task_reminders=="on"})
    db.commit();flash(request,"Preferências de notificação atualizadas.","success")
    return RedirectResponse("/settings?tab=notifications",status_code=303)


@router.post("/settings/security")
def update_security(
    request: Request, hide_sensitive_values: str|None=Form(None), auto_lock_minutes: int=Form(0),
    csrf_token: str=Form(...), db: Session=Depends(get_db),
):
    user=current_user(request,db)
    if user is None:return RedirectResponse("/login",status_code=303)
    if not validate_csrf_token(request.session,csrf_token):
        flash(request,"Sessão expirada.","error");return RedirectResponse("/settings?tab=security",status_code=303)
    auto_lock_minutes=max(0,min(int(auto_lock_minutes or 0),480))
    _save_settings(user.preference,{"hide_sensitive_values":hide_sensitive_values=="on","auto_lock_minutes":auto_lock_minutes})
    db.commit();flash(request,"Preferências de segurança atualizadas.","success")
    return RedirectResponse("/settings?tab=security",status_code=303)


@router.post("/settings/security/revoke-sessions")
def revoke_other_sessions(request: Request, csrf_token: str=Form(...), db: Session=Depends(get_db)):
    user=current_user(request,db)
    if user is None:return RedirectResponse("/login",status_code=303)
    if not validate_csrf_token(request.session,csrf_token):
        flash(request,"Sessão expirada.","error");return RedirectResponse("/settings?tab=security",status_code=303)
    user.auth_version=int(user.auth_version or 1)+1
    db.commit()
    request.session["auth_version"]=int(user.auth_version)
    flash(request,"Outras sessões foram encerradas. Esta sessão continua ativa.","success")
    return RedirectResponse("/settings?tab=security",status_code=303)


@router.post("/settings/backup")
def update_backup_preferences(
    request: Request, backup_frequency: str=Form("manual"), include_attachments: str|None=Form(None),
    csrf_token: str=Form(...), db: Session=Depends(get_db),
):
    user=current_user(request,db)
    if user is None:return RedirectResponse("/login",status_code=303)
    if not validate_csrf_token(request.session,csrf_token):
        flash(request,"Sessão expirada.","error");return RedirectResponse("/settings?tab=backup",status_code=303)
    if backup_frequency not in {"manual","daily","weekly","monthly"}: backup_frequency="manual"
    _save_settings(user.preference,{"backup_frequency":backup_frequency,"backup_include_attachments":include_attachments=="on"})
    db.commit();flash(request,"Preferências de backup salvas. A execução automática depende do storage externo estar ativo.","success")
    return RedirectResponse("/settings?tab=backup",status_code=303)


@router.get("/settings/backup/export")
def export_settings_backup(request: Request, db: Session=Depends(get_db)):
    user=current_user(request,db)
    if user is None:return RedirectResponse("/login",status_code=303)
    payload={
        "format":"dbmilesx-settings-backup-v1", "generated_at":datetime.utcnow().isoformat()+"Z",
        "user":{"id":user.id,"name":user.name,"email":user.email,"role":user.role,"company_id":user.company_id},
        "company":({"id":user.company.id,"name":user.company.name,"cnpj":user.company.cnpj,"email":user.company.email} if user.company else None),
        "appearance":{"theme_preset":user.preference.theme_preset,"accent_color":user.preference.accent_color,"background_style":user.preference.background_style,"compact_mode":user.preference.compact_mode},
        "preferences":_settings(user.preference), "stats":_stats(db,user), "storage":storage_status().as_dict(),
    }
    filename=f"dbmilesx-backup-config-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.json"
    return JSONResponse(payload, headers={"Content-Disposition":f'attachment; filename="{filename}"'})


@router.post('/settings/security/mfa/setup')
def mfa_setup(request: Request, password: str=Form(...), csrf_token: str=Form(...), db: Session=Depends(get_db)):
    user = current_user(request,db)
    if user is None: return RedirectResponse('/login',status_code=303)
    if not validate_csrf_token(request.session,csrf_token):
        flash(request,'Sessão expirada.','error'); return RedirectResponse('/settings?tab=security',status_code=303)
    if mfa.enabled(user):
        flash(request,'2FA já está ativo.','info'); return RedirectResponse('/settings?tab=security',status_code=303)
    if not verify_password(password,user.password_hash):
        flash(request,'Senha incorreta.','error'); return RedirectResponse('/settings?tab=security',status_code=303)
    d=mfa.data(user);d['mfa_pending_encrypted']=mfa.encrypt(mfa.generate());mfa.save(user,d)
    db.commit();return RedirectResponse('/settings?tab=security',status_code=303)


@router.post('/settings/security/mfa/enable')
def mfa_enable(request: Request, code: str=Form(...), csrf_token: str=Form(...), db: Session=Depends(get_db)):
    user=current_user(request,db)
    if user is None:return RedirectResponse('/login',status_code=303)
    if not validate_csrf_token(request.session,csrf_token):
        flash(request,'Sessão expirada.','error');return RedirectResponse('/settings?tab=security',status_code=303)
    if mfa.enabled(user) or not mfa.pending_secret(user):
        flash(request,'Inicie a configuração do 2FA.','error');return RedirectResponse('/settings?tab=security',status_code=303)
    wait=seconds_until_allowed(db,'mfa_setup',str(user.id))
    if wait:
        flash(request,'Muitas tentativas. Tente novamente mais tarde.','error');return RedirectResponse('/settings?tab=security',status_code=303)
    if not mfa.verify(user,code):
        register_attempt(db,'mfa_setup',str(user.id))
        flash(request,'Código inválido.','error');return RedirectResponse('/settings?tab=security',status_code=303)
    d=mfa.data(user);d['mfa_secret_encrypted']=d.pop('mfa_pending_encrypted');d['mfa_enabled']=True
    plain,hashed=mfa.recovery_codes();d['mfa_recovery_hashes']=hashed
    mfa.save(user,d);user.auth_version=int(user.auth_version or 1)+1;db.commit()
    request.session['auth_version']=int(user.auth_version)
    # Show once, not persisted as plaintext in the database.
    request.session['new_mfa_recovery_codes']=plain
    flash(request,'2FA ativado. Guarde seus códigos de recuperação.','success')
    return RedirectResponse('/settings?tab=security',status_code=303)


@router.post('/settings/security/mfa/disable')
def mfa_disable(request: Request,password: str=Form(...),code: str=Form(...),csrf_token: str=Form(...),db: Session=Depends(get_db)):
    user=current_user(request,db)
    if user is None:return RedirectResponse('/login',status_code=303)
    if not validate_csrf_token(request.session,csrf_token):
        flash(request,'Sessão expirada.','error');return RedirectResponse('/settings?tab=security',status_code=303)
    wait=seconds_until_allowed(db,'mfa_disable',str(user.id))
    if wait:
        flash(request,'Muitas tentativas. Tente mais tarde.','error');return RedirectResponse('/settings?tab=security',status_code=303)
    if not verify_password(password,user.password_hash) or not (mfa.verify(user,code,consume=True) or mfa.verify_recovery(user,code)):
        register_attempt(db,'mfa_disable',str(user.id))
        flash(request,'Senha ou código inválido.','error');return RedirectResponse('/settings?tab=security',status_code=303)
    d=mfa.data(user)
    for key in ('mfa_enabled','mfa_secret_encrypted','mfa_pending_encrypted','mfa_recovery_hashes','mfa_last_window'):
        d.pop(key,None)
    mfa.save(user,d);user.auth_version=int(user.auth_version or 1)+1;db.commit()
    request.session['auth_version']=int(user.auth_version)
    flash(request,'2FA desativado nesta conta.','success')
    return RedirectResponse('/settings?tab=security',status_code=303)
