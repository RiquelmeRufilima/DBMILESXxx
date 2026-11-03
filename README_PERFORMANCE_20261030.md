# Desempenho e carregamento progressivo — 30/10/2026

## O que foi alterado

- `/cadastros/cotacoes`: a primeira resposta apresenta imediatamente a estrutura do quadro (cabeçalho, filtros, ações e skeletons). A segunda solicitação, autenticada e com os mesmos filtros, carrega os dados do quadro. Os cartões são inseridos aos poucos no navegador para não congelar a interface. Em **Aguardando**, só 10 cartões são inseridos inicialmente; o botão carrega os próximos 10.
- As consultas do quadro aplicam filtros de usuário, status e data no banco, antes da leitura dos relacionamentos.
- `/cadastros/fluxo-calculo`: consultas de grupos, opções, aceites e cotações legadas são limitadas ao período selecionado, inclusive grupos antigos com opções novas.
- `/calculations/history`: otimização de pintura dos cartões fora da tela quando o navegador suporta `content-visibility` (a paginação existente foi mantida).
- Respostas grandes podem ser comprimidas via GZip; `Server-Timing` informa tempo de processamento interno.
- A página autenticada `/diagnostics/performance` testa TTFB aproximado, tempo total e tamanho de resposta de quatro recursos. Links de acesso ficam em **Cotações** e **Histórico de cálculos**.

## Como testar no sistema publicado

1. Faça deploy desta atualização e abra **Cotações → Teste de velocidade**.
2. Clique **Iniciar teste**, anote os tempos e **Copiar relatório**.
3. Repita em celular e computador, no mesmo Wi‑Fi, para comparações consistentes.
4. Para o carregamento progressivo, abra o Quadro de Cotações e observe as faixas surgindo uma após a outra.

**Importante:** nenhuma medição de produção foi feita aqui; tempos reais dependem da Vercel, Neon, conexão e dados da sua conta. O teste executa leituras autenticadas, sem modificar informações.

## Teste local isolado (sem acessar dados reais)

No diretório do projeto, com dependências instaladas:

```bash
python scripts/benchmark_local_performance.py --rows 200 --runs 5
PYTHONPATH=. pytest -q tests/test_performance_board_regression.py tests/test_oct30_mobile_tracking_regressions.py
```

O benchmark usa uma base SQLite temporária, com cotações **fictícias**. Não mede internet ou latência de hospedagem.

## Publicação

Se publicar pelo GitHub/Vercel, substitua/mescle os arquivos deste ZIP no repositório, faça commit e deploy. Não é necessário executar migração de banco para esta alteração.
