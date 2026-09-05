from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.gzip import GZipMiddleware
from sqlalchemy import select

from .config import (
    AIRLINE_IMAGE_DIR,
    AIRLINE_UPLOAD_DIR,
    APP_NAME,
    DATA_DIR,
    DEBUG,
    SECRET_KEY,
    SESSION_COOKIE,
    SESSION_HTTPS_ONLY,
    STATIC_DIR,
    IS_VERCEL,
    RUN_FULL_STARTUP_MAINTENANCE,
)
from .database import Base, SessionLocal, engine
from .routers import (
    airlines,
    auth,
    tasks,
    cadastros,
    calculations,
    company,
    dashboard,
    notifications,
    panels,
    pdf,
    persons,
    profile,
    requests,
    settings,
    menu_aliases,
    local_control,
    amadeus,
)
from .services.legacy_migration import migrate_legacy_data
from .services.quote_trip_backfill import backfill_quote_trip_details
from .services.seed import seed_builtin_airlines
from .services.schema_migrations import ensure_runtime_schema
from .services.user_defaults import ensure_user_defaults
from .services.team_accounts import ensure_company_owners
from .models import Airline, WebUser
from .services.hosted_bootstrap import ensure_hosted_admin
from .services.performance import ensure_performance_indexes

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if IS_VERCEL:
        # IMPORTANTE:
        # Em Vercel, o cold start não pode ficar criando/migrando/seedando o
        # PostgreSQL. Essas tarefas prendiam a Function antes da primeira
        # resposta e causavam FUNCTION_INVOCATION_TIMEOUT (504).
        #
        # O banco deve ser preparado uma única vez pelo script:
        #   python scripts/inicializar_neon.py
        logger.info("Vercel: inicialização leve concluída; banco não é migrado no cold start.")
        yield
        return

    # Execução local/servidor tradicional: mantém o comportamento anterior.
    Base.metadata.create_all(bind=engine)
    ensure_runtime_schema(engine)
    ensure_performance_indexes(engine)

    db = SessionLocal()
    try:
        seed_builtin_airlines(db)

        if RUN_FULL_STARTUP_MAINTENANCE:
            migration = migrate_legacy_data(db)
            trip_backfill = backfill_quote_trip_details(db)
            for user in db.query(WebUser).all():
                ensure_user_defaults(db, user)
            owners_fixed = ensure_company_owners(db)
        else:
            migration = {"status": "ignorado"}
            trip_backfill = 0
            owners_fixed = 0

        logger.info(
            "Inicialização concluída. Migração=%s | viagens=%s | proprietários=%s",
            migration,
            trip_backfill,
            owners_fixed,
        )
    finally:
        db.close()
    yield


app = FastAPI(
    title=f"{APP_NAME} Web V5.10.35 / V2.20 Performance Mobile",
    description="Sistema web responsivo de cotações aéreas.",
    debug=DEBUG,
    lifespan=lifespan,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie=SESSION_COOKIE,
    same_site="lax",
    https_only=SESSION_HTTPS_ONLY,
    max_age=60 * 60 * 12,
)

# HTML/JSON e arquivos textuais ficam menores no celular e em conexões móveis.
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)


@app.middleware("http")
async def performance_timing(request, call_next):
    """Mede rotas sem alterar a resposta; facilita achar a próxima tela lenta."""
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    path = request.url.path
    if path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "public, max-age=604800, stale-while-revalidate=86400")
    elif path.startswith("/imagens/"):
        response.headers.setdefault("Cache-Control", "public, max-age=86400, stale-while-revalidate=86400")
    else:
        response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
        response.headers["X-DBMILESX-Time"] = f"{elapsed_ms:.0f}ms"
        if elapsed_ms >= 800:
            logger.warning("Rota lenta: %s %s %.0fms", request.method, path, elapsed_ms)
    return response

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(AIRLINE_UPLOAD_DIR.parent)), name="uploads")
if AIRLINE_IMAGE_DIR.exists():
    app.mount("/imagens", StaticFiles(directory=str(AIRLINE_IMAGE_DIR)), name="airline_images")

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(calculations.router)
app.include_router(airlines.router)
app.include_router(cadastros.router)
app.include_router(company.router)
app.include_router(requests.router)
app.include_router(tasks.router)
app.include_router(notifications.router)
app.include_router(profile.router)
app.include_router(settings.router)
app.include_router(menu_aliases.router)
app.include_router(panels.router)
app.include_router(pdf.router)
app.include_router(persons.router)
app.include_router(local_control.router)
app.include_router(amadeus.router)

# Rotas de emergência ficam por último. Assim, nunca escondem as telas reais
# quando uma rota oficial já existe, mas continuam disponíveis como fallback.
try:
    from .routers import rotas_emergencia as _rotas_emergencia
    app.include_router(_rotas_emergencia.router)
except Exception as exc:
    logger.warning("Rotas de emergência não carregadas: %s", exc)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    import traceback
    from datetime import datetime
    reference = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
    try:
        log_dir = DATA_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "server_errors.log").open("a", encoding="utf-8") as handle:
            handle.write(f"\n[{reference}] {request.method} {request.url}\n")
            handle.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except Exception:
        pass
    logger.exception("Erro interno %s em %s", reference, request.url.path)
    return HTMLResponse(
        f"""<!doctype html><html lang='pt-BR'><meta charset='utf-8'><title>Erro recuperável</title><body style='font-family:Arial;background:#071525;color:#eaf4ff;padding:40px'><h2>Não foi possível abrir esta tela.</h2><p>O erro foi registrado com o código <b>{reference}</b>.</p><p>Feche e abra o DBMILESX novamente. Se persistir, consulte <code>data/logs/server_errors.log</code>.</p><p><a style='color:#69c7ff' href='/dashboard'>Voltar ao início</a></p></body></html>""",
        status_code=500,
    )


@app.get("/health")
def health():
    # Não toca no banco: serve para confirmar que a Function/FastAPI iniciou.
    return {"status": "ok", "app": APP_NAME, "version": "5.10.35-subcotacoes-separadas-historico-vertical"}


@app.get("/health/db")
def health_db():
    """Testa o Neon/PostgreSQL sem expor credenciais."""
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        logger.exception("Falha no teste do banco hospedado")
        return JSONResponse(
            {
                "status": "error",
                "database": "unavailable",
                "error_type": type(exc).__name__,
                "message": str(exc)[:500],
            },
            status_code=503,
        )


@app.get("/cotacoes")
def redirect_cotacoes_root():
    return RedirectResponse("/cadastros/cotacoes", status_code=303)


@app.get("/cotacoes-feitas")
def redirect_cotacoes_feitas_root():
    return RedirectResponse("/cadastros/cotacoes-feitas", status_code=303)


@app.get("/fluxo-calculo")
def redirect_fluxo_calculo_root():
    return RedirectResponse("/cadastros/fluxo-calculo", status_code=303)


@app.get("/voos")
def redirect_voos_root():
    return RedirectResponse("/cadastros/voos", status_code=303)


@app.get("/financeiro")
def redirect_financeiro_root():
    return RedirectResponse("/cadastros/financeiro", status_code=303)


@app.get("/vendas")
def redirect_vendas_root():
    return RedirectResponse("/cadastros/financeiro/vendas", status_code=303)


@app.get("/fluxo-caixa")
def redirect_fluxo_caixa_root():
    return RedirectResponse("/cadastros/financeiro/fluxo-caixa", status_code=303)


# Compatibilidade dos novos menus: aceita URLs antigas, curtas e alternativas.
@app.get("/financeiro/vendas")
@app.get("/financeiro/vendas-lancadas")
@app.get("/vendas-lancadas")
def redirect_financeiro_vendas_alias():
    return RedirectResponse("/cadastros/financeiro/vendas", status_code=303)


@app.get("/financeiro/fluxo-caixa")
@app.get("/financeiro/fluxo-de-caixa")
@app.get("/fluxo-de-caixa")
def redirect_financeiro_fluxo_alias():
    return RedirectResponse("/cadastros/financeiro/fluxo-caixa", status_code=303)


@app.get("/financeiro/formas-pagamento")
@app.get("/financeiro/formas-de-pagamento")
@app.get("/financeiro/pagamentos")
@app.get("/financeiro/meios-pagamento")
@app.get("/formas-pagamento")
@app.get("/formas-de-pagamento")
def redirect_financeiro_pagamentos_alias():
    return RedirectResponse("/cadastros/financeiro/formas-pagamento", status_code=303)


@app.get("/cadastros/vendas-lancadas")
def redirect_cadastros_vendas_alias():
    return RedirectResponse("/cadastros/financeiro/vendas", status_code=303)


@app.get("/cadastros/fluxo-caixa")
@app.get("/cadastros/fluxo-de-caixa")
def redirect_cadastros_fluxo_caixa_alias():
    return RedirectResponse("/cadastros/financeiro/fluxo-caixa", status_code=303)


@app.get("/cadastros/formas-pagamento")
@app.get("/cadastros/formas-de-pagamento")
def redirect_cadastros_formas_alias():
    return RedirectResponse("/cadastros/financeiro/formas-pagamento", status_code=303)


@app.get("/configuracoes")
@app.get("/configuracoes/estilos-formatacao")
@app.get("/configuracoes/estilos-de-formatacao")
@app.get("/settings/appearance")
@app.get("/settings/notifications")
def redirect_settings_aliases():
    return RedirectResponse("/settings", status_code=303)


# V5.9.0 - proteção extra: se algum botão antigo chamar uma URL parecida,
# redireciona para a tela correta em vez de mostrar {"detail":"Not Found"}.
@app.get("/configuracoes/aparencia")
@app.get("/configuracoes/tema")
@app.get("/configuracoes/visual")
@app.get("/configuracoes/styles")
@app.get("/configuracoes/formatting")
@app.get("/settings/visual")
@app.get("/settings/configuracao")
def redirect_more_settings_aliases():
    return RedirectResponse("/settings", status_code=303)
