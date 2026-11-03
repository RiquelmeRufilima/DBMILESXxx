-- Execute no SQL Editor do Neon SOMENTE se sua versão não possuir
-- a coluna children no cadastro de grupos. Não remove dados.
-- Tire backup ou snapshot do banco antes.
BEGIN;
ALTER TABLE web_quote_groups ADD COLUMN IF NOT EXISTS children INTEGER NOT NULL DEFAULT 0;
COMMIT;
-- Confirmação:
SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_name='web_quote_groups' AND column_name='children';
