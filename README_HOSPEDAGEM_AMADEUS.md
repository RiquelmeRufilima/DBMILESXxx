# DBMILESX — pacote preparado para hospedagem + Amadeus

Este pacote mantém o sistema atual e acrescenta uma base segura para produção e para a integração futura com Amadeus.

## O que foi preparado

- Docker de produção com Chromium/Playwright para geração de PDF.
- `/health` pronto para health check da hospedagem.
- suporte a HTTPS por cookie seguro e proxy reverso.
- `APP_ENV=production` desativa o painel local por padrão.
- SQLite em volume persistente ou PostgreSQL via `DATABASE_URL`.
- dependências fixadas em `requirements.txt`.
- `render.yaml` de exemplo para Render.
- cliente Amadeus isolado em `app/services/amadeus.py`.
- rotas autenticadas e somente de leitura em `/api/amadeus/*`.
- nenhuma rota de reserva/emissão foi habilitada para evitar criar PNR/pedido por engano.

## Amadeus já preparado

Variáveis:

- `AMADEUS_ENABLED=0|1`
- `AMADEUS_ENV=test|production`
- `AMADEUS_CLIENT_ID`
- `AMADEUS_CLIENT_SECRET`
- `AMADEUS_TIMEOUT_SECONDS=25`

Rotas internas disponíveis após login:

- `GET /api/amadeus/status`
- `GET /api/amadeus/locations?keyword=Fortaleza`
- `GET /api/amadeus/flights?origin=FOR&destination=GRU&departure_date=2026-09-10&adults=1`

A integração implementa OAuth2 Client Credentials, busca de Airport/City e Flight Offers Search. O serviço também já possui método de Flight Offers Price para a próxima etapa.

## Antes de subir

1. Copie `.env.example` para `.env` apenas no seu computador/servidor. Não envie `.env` ao GitHub.
2. Gere `SECRET_KEY` com `python scripts/generate_secret.py`.
3. Defina `APP_URL` com seu domínio HTTPS.
4. Escolha o banco:
   - SQLite: use um disco/volume persistente e mantenha `PERSISTENT_ROOT=/var/lib/dbmilesx`.
   - PostgreSQL: defina `DATABASE_URL=postgresql+psycopg://...`.
5. No começo, deixe `AMADEUS_ENABLED=0`. Depois de cadastrar as chaves de teste no painel Amadeus, mude para `1` e mantenha `AMADEUS_ENV=test`.
6. Rode `python scripts/preflight.py` no ambiente de produção antes de liberar o sistema.

## Banco atual

O arquivo `data/dbmilesx_web.db` foi incluído porque veio no conjunto enviado para migração. Ele contém os dados atuais do sistema. **Mantenha este pacote/repositório privado.**

Em hospedagens Docker, o banco definitivo deve ficar no volume persistente, e não depender apenas do filesystem efêmero do container.

## Subir localmente com Docker

```bash
docker build -t dbmilesx .
docker run --rm -p 8000:8000 \
  -e APP_ENV=production \
  -e SECRET_KEY='SUA_CHAVE_FORTE' \
  -e SESSION_HTTPS_ONLY=0 \
  -e PERSISTENT_ROOT=/var/lib/dbmilesx \
  -v dbmilesx-data:/var/lib/dbmilesx \
  dbmilesx
```

Para teste local por HTTP, `SESSION_HTTPS_ONLY=0`. No domínio real com HTTPS, use `1`.

## Próxima etapa Amadeus

Depois que as credenciais funcionarem, a integração da interface pode ser feita sem reescrever a cotação:

1. pesquisar aeroportos/cidades pelo Amadeus;
2. buscar Flight Offers;
3. selecionar uma oferta;
4. preencher automaticamente os trechos da cotação DBMILESX;
5. validar preço com Flight Offers Price;
6. somente depois, com regras comerciais definidas, avaliar Flight Create Orders/Enterprise.

Não coloque `AMADEUS_CLIENT_SECRET` em JavaScript ou HTML. A chave fica somente no backend/variáveis de ambiente.

## Versao V2 - app correto
Este pacote foi refeito usando especificamente o arquivo `app(7).zip` enviado em 24/08/2026 como base do aplicativo. As alteracoes de hospedagem e a camada Amadeus foram aplicadas sobre essa versao, sem substituir o app por uma versao anterior.
