"""Benchmark local e ISOLADO: não acessa banco de produção nem altera clientes.

    python scripts/benchmark_local_performance.py --rows 200 --runs 5

Mede a geração do HTML via Python/Jinja. Para rede/Vercel/Neon, acesse
/diagnostics/performance enquanto estiver logado no sistema publicado.
"""
import argparse
import os
import statistics
import tempfile
import sys
from pathlib import Path
from time import perf_counter

# Permite executar `python scripts/benchmark_local_performance.py` da raiz.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import event
from starlette.requests import Request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=200)
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    if not (1 <= args.rows <= 800) or not (1 <= args.runs <= 25):
        parser.error("--rows deve estar entre 1 e 800; --runs entre 1 e 25")

    # Força SQLite temporário antes dos imports: nunca usar Neon de verdade.
    with tempfile.TemporaryDirectory(prefix="dbm-perf-benchmark-") as folder:
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(folder) / 'test.sqlite'}"
        os.environ["PERSISTENT_ROOT"] = folder
        os.environ["SECRET_KEY"] = "perf-benchmark-isolated-0123456789-abcdef"
        os.environ["APP_ENV"] = "test"
        os.environ["RUN_FULL_STARTUP_MAINTENANCE"] = "0"
        os.environ.pop("VERCEL", None)

        from app.database import Base, SessionLocal, engine
        from app.models import AcceptedQuote, QuoteGroup, WebCompany, WebUser
        from app.routers.cadastros import cotacoes
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            company = WebCompany(name="Dados sintéticos")
            db.add(company)
            db.flush()
            user = WebUser(name="Teste", email="bench@example.invalid", password_hash="invalid",
                           company_id=company.id, contact_id="DBM-970001", active=True)
            db.add(user)
            db.flush()
            for i in range(args.rows):
                group = QuoteGroup(user_id=user.id, company_id=company.id,
                                   quote_name=f"Reserva fictícia {i:04d}", origin="FOR", destination="GRU")
                db.add(group)
                db.flush()
                db.add(AcceptedQuote(group_id=group.id, user_id=user.id, company_id=company.id,
                                     status="aguardando" if i % 2 else "aprovado", sale_value=300.0+i))
            db.commit()

            def req(load=False):
                qs = b"__load=1" if load else b""
                return Request({"type":"http", "http_version":"1.1", "scheme":"http",
                                "server":("localhost", 80), "client":("127.0.0.1", 1234),
                                "method":"GET", "path":"/cadastros/cotacoes",
                                "raw_path":b"/cadastros/cotacoes", "root_path":"",
                                "query_string":qs, "headers":[],
                                "session":{"user_id":user.id,"auth_version":1}})

            times = {"shell":[], "full":[]}
            accepted_queries = {"shell":0, "full":0}
            current = "shell"

            def record(_conn,_cursor,statement,_params,_context,_many):
                if statement.lstrip().lower().startswith("select") and "web_accepted_quotes" in statement:
                    accepted_queries[current] += 1

            event.listen(engine, "before_cursor_execute", record)
            # Aquecimento comum aos dois caminhos, retirado das medidas.
            cotacoes(req(False), db=db)
            cotacoes(req(True), db=db)
            accepted_queries = {"shell":0,"full":0}
            for _ in range(args.runs):
                for key, flag in (("full", True), ("shell", False)):
                    current = key
                    start = perf_counter()
                    response = cotacoes(req(flag), db=db)
                    times[key].append((perf_counter()-start)*1000)
                    if flag:
                        assert sum(response.context["counts"].values()) == args.rows
                    else:
                        assert response.context["board_deferred"] and not sum(response.context["counts"].values())
            assert accepted_queries["shell"] == 0
            print(f"Banco temporário | {args.rows} cotações fictícias | {args.runs} repetições")
            print(f"Abertura do quadro (esqueleto): mediana {statistics.median(times['shell']):.1f} ms, consultas de cotações {accepted_queries['shell']}")
            print(f"Quadro completo (dados):         mediana {statistics.median(times['full']):.1f} ms, consultas de cotações {accepted_queries['full']}")
            print("Esses números NÃO incluem internet, navegador, Neon ou inicialização a frio da Vercel.")


if __name__ == "__main__":
    main()
