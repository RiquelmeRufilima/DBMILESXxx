# DBMILESX — pacote Vercel V2.10.5

Este pacote foi preparado a partir da V2.10.4 do DBMILESX.

## Arquivos novos na raiz

- `api/index.py` — entrada FastAPI usada pelo Vercel.
- `vercel.json` — envia todas as rotas (`/login`, `/dashboard`, `/static`, etc.) para a mesma Function.
- `pyproject.toml` e `requirements.txt` — dependências Python.
- `.python-version` — Python 3.12.
- `.vercelignore` e `.gitignore` — impedem envio de banco, uploads, venv e backups.
- `.env.example` — lista das variáveis que você deve criar no Vercel.
- `scripts/gerar_secret_key.py` — gera uma SECRET_KEY.

## Arquivos do app alterados

- `app/config.py`
  - reconhece ambiente Vercel;
  - exige `SECRET_KEY`;
  - exige PostgreSQL em `DATABASE_URL`;
  - usa `/tmp/dbmilesx` somente para temporários/logs;
  - monta APP_URL com `VERCEL_URL`.

- `app/database.py`
  - usa `NullPool` com PostgreSQL em Vercel para evitar pools presos a instâncias serverless.

- `app/services/schema_migrations.py`
  - corrige defaults BOOLEAN para PostgreSQL.

- `app/services/hosted_bootstrap.py`
  - cria o primeiro administrador quando o banco está vazio e as variáveis BOOTSTRAP_* estão configuradas.

- `app/main.py`
  - inicialização mais leve em cold starts;
  - seed das companhias padrão apenas quando necessário;
  - não roda manutenção pesada em todo cold start.

- `app/services/uploads.py`
  - uploads persistentes ficam bloqueados no Vercel por padrão;
  - `EPHEMERAL_UPLOADS_ENABLED=true` libera somente teste temporário;
  - limite seguro de ~4 MB por arquivo em Functions.

- `app/services/pdf_service.py`
  - mostra mensagem clara quando tentar gerar PDF server-side no Vercel.
  - a prévia HTML continua disponível.

## Variáveis obrigatórias no Vercel

Crie em `Project Settings > Environment Variables`:

1. `APP_ENV=production`
2. `SECRET_KEY=<chave aleatória longa>`
3. `DATABASE_URL=<PostgreSQL>`
4. `SESSION_HTTPS_ONLY=true`
5. `LOCAL_ADMIN_ENABLED=false`

Para o PRIMEIRO acesso em um PostgreSQL vazio:

6. `BOOTSTRAP_ADMIN_EMAIL`
7. `BOOTSTRAP_ADMIN_PASSWORD`
8. `BOOTSTRAP_ADMIN_NAME`
9. `BOOTSTRAP_COMPANY_NAME`

Depois que conseguir entrar, remova `BOOTSTRAP_ADMIN_PASSWORD` do Vercel e faça novo deploy.

## Banco

Não envie `data/` para o GitHub/Vercel.
O banco SQLite local não deve ser usado como banco permanente no Vercel.

Este pacote cria/atualiza as tabelas no PostgreSQL configurado em `DATABASE_URL`.
Se você quiser levar todo o histórico do SQLite atual para o PostgreSQL, faça uma migração separada dos dados.

## Uploads

`uploads/` também não deve ir para o GitHub.
O filesystem das Functions é temporário. Para logos/anexos persistentes, será necessário conectar Vercel Blob, S3 ou storage semelhante.

## PDF

O DBMILESX usa Chromium/Playwright para PDF. Este pacote não instala um navegador headless dentro da Function.
A prévia HTML continua funcionando; a rota de PDF informará que precisa de um serviço externo de PDF/Chromium.

## Publicar

1. Coloque o conteúdo deste ZIP no repositório.
2. Suba para GitHub.
3. Importe o repositório no Vercel.
4. Configure as variáveis acima.
5. Faça Deploy.
6. Abra `/health` para testar.
7. Depois abra `/`.

## Teste local

```bash
pip install -r requirements.txt
python run.py
```

A versão local continua funcionando com SQLite se `DATABASE_URL` não estiver definida e `VERCEL` não estiver ativo.
