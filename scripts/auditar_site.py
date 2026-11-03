#!/usr/bin/env python3
"""DBMILESX: diagnóstico de leitura de desempenho e de proteções HTTP.

Utilização:
  python scripts/auditar_site.py --codigo .
  python scripts/auditar_site.py --url https://SEU-PROJETO.vercel.app
  python scripts/auditar_site.py --url http://127.0.0.1:8000 --repeticoes 5

Não autentica, não faz POST, não testa senhas, não altera dados, não segue redirects
nem executa carga alta. Use exclusivamente em aplicações próprias ou autorizadas.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path
from urllib import request, error, parse


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = request.build_opener(NoRedirect)
PATHS = (
    ("Inicialização (/health)", "/health"),
    ("Página de login", "/login"),
    ("Histórico protegido", "/calculations/history"),
    ("Diagnóstico protegido", "/diagnostics/performance"),
    ("CSS estático", "/static/css/app.css"),
)


def request_once(url: str, timeout: float) -> dict:
    req = request.Request(url, method="GET", headers={"User-Agent": "DBMILESX-Auditoria-Manual/1.0", "Accept": "text/html,application/json,*/*"})
    start = time.perf_counter()
    try:
        with OPENER.open(req, timeout=timeout) as resp:
            status = resp.status
            headers = {k.lower(): v for k, v in resp.headers.items()}
            body = resp.read(2 * 1024 * 1024)
    except error.HTTPError as exc:
        status = exc.code
        headers = {k.lower(): v for k, v in exc.headers.items()}
        body = exc.read(1024)
    except (error.URLError, TimeoutError, OSError) as exc:
        return {"erro": f"{type(exc).__name__}: {exc}", "ms": round((time.perf_counter()-start)*1000, 1)}
    return {"status": status, "ms": round((time.perf_counter()-start)*1000, 1),
            "bytes_lidos": len(body), "headers": headers}


def static_checks(root: Path) -> list[dict]:
    checks = []
    def add(level, subject, why):
        checks.append({"nivel":level,"item":subject,"observacao":why})
    main = (root / "app/main.py").read_text(encoding="utf-8") if (root / "app/main.py").is_file() else ""
    config = (root / "app/config.py").read_text(encoding="utf-8") if (root / "app/config.py").is_file() else ""
    sec = (root / "app/security.py").read_text(encoding="utf-8") if (root / "app/security.py").is_file() else ""
    vercelignore = (root / ".vercelignore").read_text(encoding="utf-8") if (root / ".vercelignore").is_file() else ""
    gitignore = (root / ".gitignore").read_text(encoding="utf-8") if (root / ".gitignore").is_file() else ""
    if not main:
        add("ERRO", "Estrutura do projeto", "app/main.py não encontrado. Execute a partir da pasta principal.")
        return checks
    if 'app.mount("/uploads", StaticFiles(' in main:
        add("ALTO", "Arquivos locais", "A pasta /uploads é servida diretamente: arquivos conhecidos podem ser baixados sem sessão.")
    if '"message": str(exc)' in main:
        add("MÉDIO", "Diagnóstico do banco", "A rota /health/db pode revelar a mensagem interna da exceção.")
    if '"Content-Security-Policy"' not in main or ('if path.startswith(("/uploads/"' in main and main.count('Content-Security-Policy') == 1):
        add("MÉDIO", "CSP global", "A política CSP não parece ser aplicada a todas as páginas HTML.")
    if 'Strict-Transport-Security' in main and 'X-Content-Type-Options' in main:
        add("OK", "Cabeçalhos", "HSTS e nosniff estão definidos no código; confirme resposta real HTTPS.")
    if 'SESSION_HTTPS_ONLY = _env_bool("SESSION_HTTPS_ONLY", IS_PRODUCTION)' in config:
        add("OK", "Cookie de sessão", "Secure é ativado por padrão em produção, mas verifique configurações reais.")
    if 'bcrypt.hashpw' in sec and 'compare_digest' in sec:
        add("OK", "Senhas e CSRF", "Bcrypt e comparação constante foram encontrados.")
    if re.search(r"^tests/?$", vercelignore, re.MULTILINE):
        add("OK", "Deploy", "Pasta tests excluída do deploy por .vercelignore.")
    else:
        add("MÉDIO", "Deploy", "tests/ não está excluída por .vercelignore; o deploy pode incluir testes desnecessariamente.")
    if 'node_modules/' not in gitignore:
        add("MÉDIO", "Repositório", "Ignorar node_modules/ no Git é recomendado.")
    return checks


def print_checks(items):
    print("\nAUDITORIA ESTÁTICA (código local; não comprova configuração externa)")
    for c in items:
        print(f"  [{c['nivel']}] {c['item']}: {c['observacao']}")


def live_checks(url: str, repetitions: int, timeout: float) -> tuple[list[dict],list[dict]]:
    base = url.rstrip("/")
    parsed = parse.urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("Informe a URL base, sem usuário/senha, caminhos, parâmetros ou fragmentos.")
    if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Para sites remotos use HTTPS. HTTP só é permitido em localhost.")
    print("\nTESTE ONLINE (apenas GETs; nenhum login ou alteração de dados)")
    summary = []
    for name, path in PATHS:
        samples = [request_once(base + path, timeout) for _ in range(repetitions)]
        timings = [v['ms'] for v in samples if 'status' in v]
        status = samples[-1].get('status', 'falhou')
        mean = round(statistics.mean(timings), 1) if timings else None
        median = round(statistics.median(timings), 1) if timings else None
        print(f"  {name}: HTTP {status}, média={mean} ms, mediana={median} ms ({len(timings)}/{repetitions})")
        summary.append({"nome":name,"caminho":path,"status":status,"media_ms":mean,"mediana_ms":median,"amostras":timings})
    checks=[]
    def add(level, item, observation):
        checks.append({"nivel":level,"item":item,"observacao":observation})
    login = request_once(base + "/login", timeout)
    headers = login.get("headers", {})
    for key, label in (("x-content-type-options","X-Content-Type-Options"),("x-frame-options","X-Frame-Options"),("referrer-policy","Referrer-Policy")):
        add("OK" if headers.get(key) else "MÉDIO", label, headers.get(key) or "Ausente na resposta")
    if parsed.scheme == "https":
        add("OK" if headers.get("strict-transport-security") else "ALTO", "HSTS", headers.get("strict-transport-security") or "Ausente na resposta HTTPS")
    add("OK" if headers.get("content-security-policy") else "MÉDIO", "CSP página de login", "Presente" if headers.get("content-security-policy") else "Não encontrada na resposta HTML")
    cookie = headers.get("set-cookie", "")
    if cookie:
        for flag in ("Secure", "HttpOnly", "SameSite"):
            add("OK" if flag.lower() in cookie.lower() else ("INFO" if flag == "Secure" and parsed.scheme == "http" else "MÉDIO"), f"Cookie {flag}", "Presente" if flag.lower() in cookie.lower() else ("Ausente em HTTP local (esperado no desenvolvimento)" if flag == "Secure" and parsed.scheme == "http" else "Não encontrado em Set-Cookie"))
    for path in ("/calculations/history", "/diagnostics/performance"):
        res = request_once(base + path, timeout)
        code=res.get("status", 0)
        add("OK" if code in (301,302,303,307,308,401,403) else "ALTO" if code == 200 else "MÉDIO", f"Acesso anônimo {path}", f"HTTP {code} (esperado bloqueio ou redirecionamento)")
    doc = request_once(base + "/openapi.json", timeout)
    add("INFO" if doc.get("status") == 200 else "OK", "Documentação da API", "Swagger/OpenAPI disponível publicamente" if doc.get("status") == 200 else f"HTTP {doc.get('status','falhou')}")
    return summary,checks


def main():
    parser=argparse.ArgumentParser(description="Auditoria segura de site próprio: leitura, sem carga ou escrita")
    parser.add_argument("--codigo", type=Path, default=Path("."), help="Pasta principal do código")
    parser.add_argument("--url", help="Endereço HTTPS do próprio site (ou http://localhost)")
    parser.add_argument("--repeticoes", type=int, default=3, help="GETs por caminho (1 a 5, padrão 3)")
    parser.add_argument("--timeout", type=float, default=8, help="Timeout por GET em segundos (2 a 20)")
    parser.add_argument("--json", type=Path, help="Salvar diagnóstico sem segredos em arquivo JSON")
    args=parser.parse_args()
    if not 1 <= args.repeticoes <= 5 or not 2 <= args.timeout <= 20:
        parser.error("Use de 1 a 5 repetições e timeout de 2 a 20 segundos")
    report={"codigo":str(args.codigo.resolve()),"checks_locais":static_checks(args.codigo)}
    print_checks(report["checks_locais"])
    if args.url:
        try:
            measurements, checks=live_checks(args.url, args.repeticoes, args.timeout)
        except ValueError as exc:
            parser.error(str(exc))
        report['medicoes']=measurements
        report['checks_online']=checks
        print("\nVALIDAÇÃO DOS CABEÇALHOS E ROTAS")
        for c in checks:
            print(f"  [{c['nivel']}] {c['item']}: {c['observacao']}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nRelatório salvo: {args.json}")
    print("\nObservação: esta verificação não substitui pentest, revisão de permissões, backup e WAF.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
