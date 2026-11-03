# DBMILESX — Segurança, Fase 2 (sem MFA obrigatório)

**Pré-requisito:** Fase 1 de proteção dos uploads instalada e testada.

## O que o pacote faz

- Adiciona cabeçalho `X-Permitted-Cross-Domain-Policies: none`.
- Adiciona CSP **somente Report-Only**, apenas nas respostas HTML e respeitando CSP especial já existente. Não altera HTML, JS, CSS, banco, rotas, autenticação ou outras telas.
- **Não altera MFA**, que permanece opcional para todos, inclusive administradores.
- Não exige consultas ao banco nem introduz scripts no navegador. A carga por resposta é somente um cabeçalho pequeno.
- Inclui quatro testes de regressão.

## Instalação segura no Codespaces

1. Faça um commit/backup do estado atual do projeto; extraia este ZIP **na raiz** preservando pastas `app/`, `scripts/`, `tests/`.
2. Execute `python scripts/aplicar_seguranca_fase2.py --dry-run`.
3. Se a validação for aprovada, execute `python scripts/aplicar_seguranca_fase2.py`.
4. Teste: `python -m pytest tests/test_security.py tests/test_security_phase2.py -q`.
5. Antes do deploy, abra login, Histórico, Companhias, Lucratividade e arquivos privados em homologação.
6. Verifique `git diff --check` e envie apenas `app/main.py`, `app/services/security_headers.py`, `tests/test_security_phase2.py`.

## Vulnerabilidades nas dependências — **etapa opcional e separada**

O projeto antigo usa `cryptography>=44,<47` e `pywebpush>=2,<3`. A versão `pywebpush 2.5.0` exige `cryptography>=47`, portanto uma atualização isolada de um pacote causaria conflito.

Depois da Fase 2 estável e **em homologação**, para atualizar as *restrições do projeto* de forma compatível:

```
python scripts/aplicar_seguranca_fase2.py --dry-run --upgrade-python-deps
python scripts/aplicar_seguranca_fase2.py --upgrade-python-deps
python -m pip install -r requirements.txt
python -m pytest tests/test_security.py tests/test_security_phase2.py -q
python -m pip_audit -r requirements.txt
```

A mudança nos requisitos **não instala automaticamente** nem atualiza a produção até deploy. Valide também notificações Web Push e cron.

O relatório anterior de `npm audit` menciona dependências transitivas de `@vercel/blob`; **não rode `npm audit fix --force`** automaticamente. Faça uma atualização de Node separada, após testar upload/download em homologação. `@vercel/blob` 2.8.2 é candidato a revisão, não foi aplicado neste pacote.

## Desfazer

- Os arquivos originais modificados pelo instalador são copiados para `data/backups/security_phase2/` (pasta local não versionada).
- Para reverter só o código da Fase 2, reverta o commit ou restaure `app/main.py` desse backup. Não delete arquivos de outros projetos.

**Limites:** os testes locais não demonstram a segurança de uma implantação pública. Antes de classificar como seguro, teste com URL real da Vercel e contas autorizadas/não autorizadas.
