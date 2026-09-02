from __future__ import annotations

from datetime import date, datetime
from html import escape
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(tags=["rotas-emergencia-v592"])

def _parse_numeric(value: Any) -> float:
    """Função robusta para tratar campos numéricos vindos de formulários ou JSON."""
    if not value:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    
    text = str(value).replace("R$", "").replace(" ", "").strip()
    if "," in text and "." in text:
        # Verifica quem vem por último: o ponto ou a vírgula
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
        
    try:
        return float(text)
    except ValueError:
        return 0.0

def _money(value: float) -> str:
    try:
        return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"

def _shell(title: str, body: str, active: str = "vendas") -> HTMLResponse:
    tabs = [
        ("vendas", "/cadastros/financeiro/vendas", "Vendas lançadas"),
        ("fluxo", "/cadastros/financeiro/fluxo-caixa", "Fluxo de caixa"),
        ("pagamentos", "/cadastros/financeiro/formas-pagamento", "Formas de pagamento"),
    ]
    nav = "".join(
        f'<a class="tab {"on" if key == active else ""}" href="{href}">{label}</a>'
        for key, href, label in tabs
    )
    html = f"""
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · DBMILESX</title>
<style>
:root {{ --bg:#06111f; --panel:#0d1b2e; --panel2:#102641; --line:#1f3a57; --txt:#e9f3ff; --muted:#9eb6cb; --blue:#5b7cff; --green:#20c997; --cyan:#27d7c9; --warn:#f5bd45; }}
*{{box-sizing:border-box}} body{{margin:0;background:linear-gradient(135deg,#07101c,#081c31);color:var(--txt);font-family:Inter,Segoe UI,Arial,sans-serif;}}
a{{color:inherit;text-decoration:none}} .layout{{display:flex;min-height:100vh}} .side{{width:245px;background:#091626;border-right:1px solid var(--line);padding:22px 18px;position:sticky;top:0;height:100vh}}
.logo{{font-weight:800;letter-spacing:.4px;margin-bottom:28px}} .group{{margin:24px 0 10px;color:#7f99b4;font-size:11px;font-weight:800;letter-spacing:1.6px;text-transform:uppercase}}
.menu a{{display:block;padding:11px 12px;border-radius:12px;color:#b8c9db;margin:4px 0;font-weight:650;font-size:14px}} .menu a.on,.menu a:hover{{background:#122842;color:#fff}}
.main{{flex:1;padding:28px;max-width:1480px}} .head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;gap:12px}} h1{{margin:0;font-size:28px}} .sub{{color:var(--muted);font-size:14px;margin-top:6px}}
.tabs{{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}} .tab{{padding:10px 14px;border:1px solid var(--line);border-radius:999px;background:#0d1b2e;color:#b8c9db;font-weight:700;font-size:14px}} .tab.on{{background:linear-gradient(135deg,#526dff,#28c7d6);border-color:transparent;color:white}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(170px,1fr));gap:14px;margin:18px 0}} .card{{background:rgba(13,27,46,.92);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 15px 40px rgba(0,0,0,.18)}}
.kpi .label{{color:var(--muted);font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.8px}} .kpi .value{{font-size:26px;font-weight:900;margin-top:10px}} .kpi.blue .value{{color:#6b8cff}} .kpi.green .value{{color:var(--green)}} .kpi.warn .value{{color:var(--warn)}}
.table{{width:100%;border-collapse:collapse;background:rgba(13,27,46,.72);border:1px solid var(--line);border-radius:18px;overflow:hidden}} .table th,.table td{{padding:13px 14px;border-bottom:1px solid rgba(31,58,87,.7);text-align:left;font-size:14px}} .table th{{color:#9eb6cb;font-size:12px;text-transform:uppercase;letter-spacing:.7px;background:#10233a}} .pill{{display:inline-flex;padding:6px 9px;border-radius:999px;background:#132943;color:#cfe4fa;font-size:12px;font-weight:800}}
.empty{{border:1px dashed #2a486b;background:#0b1b2d;border-radius:18px;padding:24px;text-align:center;color:#a9bdd1}} .btn{{display:inline-block;border:1px solid var(--line);background:#122842;color:#dcecff;border-radius:12px;padding:10px 13px;font-weight:800;font-size:13px}} .btn.primary{{background:linear-gradient(135deg,#526dff,#28c7d6);border:0;color:white}}
.notice{{border:1px solid #315c7d;background:#0d253b;color:#cbe8ff;border-radius:16px;padding:14px;margin:12px 0;font-size:14px}} @media(max-width:900px){{.layout{{display:block}}.side{{position:relative;width:auto;height:auto}}.grid{{grid-template-columns:1fr 1fr}}}} @media(max-width:580px){{.grid{{grid-template-columns:1fr}}.main{{padding:16px}}}}
</style>
</head>
<body><div class="layout"><aside class="side"><div class="logo">✈ DBMILESX</div><nav class="menu"><div class="group">Principal</div><a href="/dashboard">Tela de início</a><a href="/calculations/new">Nova cotação</a><a href="/calculations/history">Histórico</a><div class="group">Cadastros</div><a href="/persons">Pessoas</a><a href="/cadastros/cotacoes">Cotações</a><a href="/cadastros/cotacoes-feitas">Cotações feitas</a><a href="/cadastros/fluxo-calculo">Fluxo de cálculo</a><a href="/cadastros/voos">Voos</a><div class="group">Financeiro</div><a class="on" href="/cadastros/financeiro/vendas">Vendas lançadas</a><a class="on" href="/cadastros/financeiro/fluxo-caixa">Fluxo de caixa</a><a class="on" href="/cadastros/financeiro/formas-pagamento">Formas de pagamento</a></nav></aside><main class="main"><div class="head"><div><h1>{escape(title)}</h1><div class="sub">Área financeira instalada por rota de segurança V5.9.2.</div></div><a class="btn primary" href="/cadastros/cotacoes">Voltar para cotações</a></div>{nav}{body}</main></div></body></html>
"""
    return HTMLResponse(html)

def _read_finance_data() -> dict[str, Any]:
    """Leitura tolerante: não deixa a tela quebrar se o banco/modelo estiver diferente."""
    data: dict[str, Any] = {"sales": [], "payments": [], "errors": []}
    try:
        from ..database import SessionLocal
        from ..models import AcceptedQuote, WebUser
        db = SessionLocal()
        try:
            rows = db.query(AcceptedQuote).order_by(AcceptedQuote.id.desc()).limit(500).all()
            for item in rows:
                payload = item.extra_json if isinstance(getattr(item, "extra_json", None), dict) else {}
                sale_meta = payload.get("sale") if isinstance(payload.get("sale"), dict) else {}
                launched = getattr(item, "status", "") == "lancada" or bool(sale_meta.get("launched"))
                if not launched:
                    continue
                user = db.get(WebUser, getattr(item, "user_id", None)) if getattr(item, "user_id", None) else None
                sale_items = payload.get("sale_items") if isinstance(payload.get("sale_items"), list) else []
                cost_items = payload.get("cost_items") if isinstance(payload.get("cost_items"), list) else []
                
                sale_total = 0.0
                for x in sale_items:
                    if isinstance(x, dict):
                        # Chamada atualizada com o tratador seguro de valores numéricos
                        sale_total += _parse_numeric(x.get("value"))
                        
                if not sale_total:
                    sale_total = _parse_numeric(getattr(item, "sale_value", 0))
                    
                cost_total = 0.0
                for x in cost_items:
                    if isinstance(x, dict):
                        # Chamada atualizada com o tratador seguro de valores numéricos
                        cost_total += _parse_numeric(x.get("value"))
                        
                client = payload.get("client_name") or payload.get("passenger_name") or getattr(item, "locator", "") or "Venda lançada"
                title = payload.get("title") or f"Venda #{getattr(item, 'id', '')}"
                when = getattr(item, "updated_at", None) or getattr(item, "selected_at", None) or datetime.utcnow()
                sale = {"id": getattr(item, "id", ""), "title": str(title), "client": str(client), "user": getattr(user, "name", "Usuário"), "date": when.date() if hasattr(when, "date") else date.today(), "sale_total": sale_total, "cost_total": cost_total, "profit": sale_total - cost_total, "items": sale_items}
                data["sales"].append(sale)
                
                if sale_items:
                    for pay in sale_items:
                        if isinstance(pay, dict):
                            method = str(pay.get("payment_method") or pay.get("account") or "Não informado")
                            installments = str(pay.get("installments") or "1")
                            # Chamada atualizada com o tratador seguro de valores numéricos
                            value = _parse_numeric(pay.get("value"))
                            data["payments"].append({"method": method, "installments": installments, "value": value, "client": sale["client"], "user": sale["user"]})
                else:
                    data["payments"].append({"method": "Não informado", "installments": "1", "value": sale_total, "client": sale["client"], "user": sale["user"]})
        finally:
            db.close()
    except Exception as exc:
        data["errors"].append(str(exc))
    return data

@router.get("/cadastros/financeiro")
@router.get("/cadastros/financeiro/")
@router.get("/cadastros/financeiro/vendas")
@router.get("/cadastros/financeiro/vendas-lancadas")
@router.get("/financeiro")
@router.get("/financeiro/vendas")
@router.get("/financeiro/vendas-lancadas")
def financeiro_vendas_emergencia(request: Request):
    data = _read_finance_data()
    sales = data["sales"]
    total = sum(x["sale_total"] for x in sales)
    profit = sum(x["profit"] for x in sales)
    rows = "".join(f"<tr><td><span class='pill'>#{escape(str(x['id']))}</span></td><td>{escape(x['client'])}<div class='sub'>{escape(x['title'])}</div></td><td>{escape(x['user'])}</td><td>{escape(str(x['date']))}</td><td>{_money(x['sale_total'])}</td><td>{_money(x['profit'])}</td></tr>" for x in sales[:80])
    if not rows:
        rows = "<tr><td colspan='6'><div class='empty'>Nenhuma venda lançada encontrada ainda. Quando você clicar em <b>Lançar venda</b> na cotação, ela aparece aqui.</div></td></tr>"
    notice = "" if not data["errors"] else f"<div class='notice'>Aviso técnico: {escape(data['errors'][0])}</div>"
    body = f"""{notice}<div class='grid'><div class='card kpi blue'><div class='label'>Vendas lançadas</div><div class='value'>{len(sales)}</div></div><div class='card kpi green'><div class='label'>Valor vendido</div><div class='value'>{_money(total)}</div></div><div class='card kpi warn'><div class='label'>Lucro estimado</div><div class='value'>{_money(profit)}</div></div><div class='card kpi'><div class='label'>Origem</div><div class='value'>Cotações</div></div></div><table class='table'><thead><tr><th>ID</th><th>Cliente / venda</th><th>Usuário</th><th>Data</th><th>Venda</th><th>Resultado</th></tr></thead><tbody>{rows}</tbody></table>"""
    return _shell("Vendas lançadas", body, "vendas")

@router.get("/cadastros/financeiro/fluxo-caixa")
@router.get("/cadastros/financeiro/fluxo-de-caixa")
@router.get("/cadastros/fluxo-caixa")
@router.get("/cadastros/fluxo-de-caixa")
@router.get("/financeiro/fluxo-caixa")
@router.get("/financeiro/fluxo-de-caixa")
@router.get("/fluxo-caixa")
@router.get("/fluxo-de-caixa")
def financeiro_fluxo_emergencia(request: Request):
    data = _read_finance_data()
    payments = data["payments"]
    total = sum(x["value"] for x in payments)
    rows = "".join(f"<tr><td>{escape(x['method'])}</td><td>{escape(str(x['installments']))}x</td><td>{escape(x['client'])}</td><td>{escape(x['user'])}</td><td>{_money(x['value'])}</td></tr>" for x in payments[:120])
    if not rows:
        rows = "<tr><td colspan='5'><div class='empty'>Nenhuma entrada no fluxo de caixa ainda. Lance uma venda para alimentar esta tela.</div></td></tr>"
    body = f"""<div class='grid'><div class='card kpi green'><div class='label'>Entradas previstas</div><div class='value'>{_money(total)}</div></div><div class='card kpi blue'><div class='label'>Pagamentos</div><div class='value'>{len(payments)}</div></div><div class='card kpi'><div class='label'>Status</div><div class='value'>Ativo</div></div></div><table class='table'><thead><tr><th>Forma</th><th>Parcelas</th><th>Cliente</th><th>Usuário</th><th>Valor</th></tr></thead><tbody>{rows}</tbody></table>"""
    return _shell("Fluxo de caixa", body, "fluxo")

@router.get("/cadastros/financeiro/formas-pagamento")
@router.get("/cadastros/financeiro/formas-de-pagamento")
@router.get("/cadastros/formas-pagamento")
@router.get("/cadastros/formas-de-pagamento")
@router.get("/financeiro/formas-pagamento")
@router.get("/financeiro/formas-de-pagamento")
@router.get("/financeiro/meios-pagamento")
@router.get("/financeiro/meios-de-pagamento")
@router.get("/formas-pagamento")
@router.get("/formas-de-pagamento")
def financeiro_pagamentos_emergencia(request: Request):
    data = _read_finance_data()
    summary: dict[str, dict[str, Any]] = {}
    for x in data["payments"]:
        key = x["method"] or "Não informado"
        item = summary.setdefault(key, {"count": 0, "total": 0.0, "parcelas": set()})
        item["count"] += 1
        item["total"] += x["value"]
        item["parcelas"].add(str(x["installments"]))
    rows = "".join(f"<tr><td>{escape(k)}</td><td>{v['count']}</td><td>{', '.join(sorted(v['parcelas']))}x</td><td>{_money(v['total'])}</td><td><span class='pill'>Logo/taxa editável na próxima etapa</span></td></tr>" for k,v in sorted(summary.items(), key=lambda kv: kv[1]['total'], reverse=True))
    if not rows:
        rows = "<tr><td colspan='5'><div class='empty'>Nenhuma forma de pagamento usada ainda. Exemplo futuro: Infinity Black, Master, Pix, Boleto, parcelas, taxa e prazo.</div></td></tr>"
    body = f"""<div class='notice'>Esta tela já separa as formas usadas nas vendas lançadas. A próxima etapa é o cadastro editável com logo, taxa, prazo e maquininha.</div><table class='table'><thead><tr><th>Forma</th><th>Qtd.</th><th>Parcelas</th><th>Total</th><th>Configuração</th></tr></thead><tbody>{rows}</tbody></table>"""
    return _shell("Formas de pagamento", body, "pagamentos")

@router.get("/verificar-menus")
def verificar_menus_emergencia():
    body = """<div class='notice'><b>Rotas V5.9.2 carregadas.</b> Se você está vendo esta tela, o servidor iniciou usando <code>app.main:app</code> corretamente.</div><div class='grid'><a class='card' href='/cadastros/financeiro/vendas'>Vendas lançadas</a><a class='card' href='/cadastros/financeiro/fluxo-caixa'>Fluxo de caixa</a><a class='card' href='/cadastros/financeiro/formas-pagamento'>Formas de pagamento</a><a class='card' href='/cadastros/cotacoes'>Cotações</a></div>"""
    return _shell("Verificar menus", body, "vendas")

@router.get("/settings/estilos-formatacao")
@router.get("/settings/estilos-de-formatacao")
@router.get("/configuracoes/estilos-formatacao")
@router.get("/configuracoes/estilos-de-formatacao")
@router.get("/configuracoes")
@router.get("/configurações")
def configuracoes_alias_emergencia():
    return RedirectResponse("/settings", status_code=303)