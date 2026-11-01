#!/usr/bin/env python3
"""Mede endpoints públicos e acesso anônimo, sem carga, escrita ou login.

Uso: python scripts/diagnosticar_desempenho_fase4.py --url https://DOMINIO-REAL --amostras 3
Testar apenas sites próprios/autorizados. Sem parâmetros com credenciais.
"""
from __future__ import annotations
import argparse
import json
import statistics
import time
from pathlib import Path
from urllib import request, error, parse

PATHS = {'Saúde': '/health', 'Login': '/login', 'CSS': '/static/css/app.css',
         'Histórico sem sessão': '/calculations/history',
         'Diagnóstico sem sessão': '/diagnostics/performance'}

class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

OPENER = request.build_opener(NoRedirect)

def validate_url(raw: str) -> str:
    parsed = parse.urlparse(raw)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('Use apenas URL-base sem caminho, parâmetros ou usuário/senha.')
    if parsed.hostname.lower() in ('seu-projeto.vercel.app', 'seu-dominio-real', 'example.com', 'seu-dominio.com', 'dominio-real.vercel.app'):
        raise ValueError('Endereço de exemplo detectado. Informe o domínio verdadeiro do DBMILESX.')
    if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1'):
        raise ValueError('Para testes externos é obrigatório HTTPS.')
    return raw.rstrip('/')

def get(url: str, timeout: int = 8):
    start = time.perf_counter()
    req = request.Request(url, method='GET', headers={'User-Agent':'DBMILESX-Diagnostico-Proprio/1.0'})
    try:
        with OPENER.open(req, timeout=timeout) as response:
            status, headers = response.status, dict(response.headers)
            response.read(65536)
    except error.HTTPError as exc:
        status, headers = exc.code, dict(exc.headers)
        exc.read(4096)
    except (OSError, error.URLError) as exc:
        return {'erro': type(exc).__name__, 'ms': round((time.perf_counter()-start)*1000, 2)}
    return {'status': status, 'ms': round((time.perf_counter()-start)*1000, 2),
            'headers': {key.lower():value for key,value in headers.items()}}

def measure(base: str, samples: int) -> dict:
    report = {'url':base,'amostras':samples,'rotas':{},'seguranca':{}}
    for label, path in PATHS.items():
        values = [get(base+path) for _ in range(samples)]
        valid = [v['ms'] for v in values if 'status' in v]
        status = values[-1].get('status')
        report['rotas'][label] = {'status':status, 'media_ms':round(statistics.mean(valid),1) if valid else None,
            'mediana_ms':round(statistics.median(valid),1) if valid else None,
            'max_ms':round(max(valid),1) if valid else None,
            'falhas':sum('status' not in v for v in values)}
    login = get(base+'/login')
    headers = login.get('headers',{})
    for h in ('strict-transport-security','x-content-type-options','x-frame-options','referrer-policy'):
        report['seguranca'][h] = 'presente' if headers.get(h) else 'ausente'
    report['seguranca']['csp'] = ('enforcing' if headers.get('content-security-policy')
        else 'report-only' if headers.get('content-security-policy-report-only') else 'ausente')
    for label in ('Histórico sem sessão', 'Diagnóstico sem sessão'):
        code = report['rotas'][label]['status']
        report['seguranca'][label] = ('protegido' if code in (301,302,303,307,308,401,403)
            else 'ATENÇÃO: HTTP 200' if code == 200 else f'revisar: HTTP {code}')
    return report

def main():
    p=argparse.ArgumentParser(description='DBMILESX: teste leve de velocidade/segurança sem autenticação')
    p.add_argument('--url',required=True,help='Domínio HTTPS verdadeiro do DBMILESX')
    p.add_argument('--amostras',type=int,default=3,help='De 1 a 5 leituras por página')
    p.add_argument('--salvar',default='data/logs/diagnostico_fase4.json')
    p.add_argument('--comparar',type=Path,help='Relatório JSON anterior para comparar medianas')
    args=p.parse_args()
    if not 1 <= args.amostras <= 5: p.error('Use de 1 a 5 amostras')
    try: base=validate_url(args.url)
    except ValueError as exc: p.error(str(exc))
    report=measure(base,args.amostras)
    for label,item in report['rotas'].items():
        print(f"{label}: HTTP {item['status']} • mediana {item['mediana_ms']} ms • máximo {item['max_ms']} ms")
    print('Proteções:', ', '.join(f'{k}: {v}' for k,v in report['seguranca'].items()))
    if args.comparar:
        try:
            before=json.loads(args.comparar.read_text(encoding='utf-8'))
            print('\nComparação com o relatório anterior:')
            for label,item in report['rotas'].items():
                previous=before.get('rotas',{}).get(label,{}).get('mediana_ms')
                current=item.get('mediana_ms')
                if previous is not None and current is not None and previous > 0:
                    difference=(current/previous-1)*100
                    print(f'  {label}: {difference:+.1f}% na mediana (valores menores são melhores)')
        except (OSError,ValueError,TypeError,AttributeError) as exc:
            p.error(f'Não foi possível usar o relatório anterior: {exc}')
    outfile=Path(args.salvar)
    outfile.parent.mkdir(parents=True,exist_ok=True)
    outfile.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Relatório:',outfile)
    print('Mede só HTTP; não substitui teste de carga, auditoria de acesso ou Core Web Vitals.')

if __name__=='__main__': main()
