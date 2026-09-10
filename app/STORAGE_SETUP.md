# DBMILESX — armazenamento em Vercel + Neon

O Neon já mantém os dados PostgreSQL de forma persistente. O filesystem das Functions da Vercel não deve ser usado para anexos, logos, avatares e fotos permanentes.

A versão atual prepara uma camada de configuração de storage com estas variáveis:

- `FILE_STORAGE_PROVIDER=vercel_blob|s3|r2|local`
- `FILE_STORAGE_PUBLIC_URL=`
- `FILE_STORAGE_BUCKET=`
- `FILE_STORAGE_REGION=`
- `FILE_STORAGE_ENDPOINT=`

Credenciais esperadas podem ser fornecidas pelas variáveis do próprio provedor, como `BLOB_READ_WRITE_TOKEN`, `AWS_ACCESS_KEY_ID` ou `R2_ACCESS_KEY_ID`.

Enquanto o adapter externo não estiver ativado, o painel Configurações > Backup e storage informa que os uploads permanentes estão pendentes na Vercel. O banco Neon continua normal.

Próxima etapa recomendada: escolher um único provedor de arquivos e migrar `services/uploads.py` para gravar os bytes nesse provider, mantendo no Neon apenas a URL e metadados.
