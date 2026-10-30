-- DBMILESX: catálogo com Companhias, Sistemas e Consolidadoras e Operadoras.
-- Executar uma vez no Neon SQL Editor do banco usado pela Vercel, ANTES do deploy.
-- As companhias originais permanecem na categoria Companhias.
BEGIN;
ALTER TABLE web_airlines
    ADD COLUMN IF NOT EXISTS catalog_category VARCHAR(32) NOT NULL DEFAULT 'airlines';
-- Mantém consistência mesmo se um registro original tiver sido editado antes.
UPDATE web_airlines SET catalog_category = 'airlines' WHERE builtin = TRUE;
COMMIT;
