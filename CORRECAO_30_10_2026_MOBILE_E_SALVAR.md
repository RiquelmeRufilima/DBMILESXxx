# DBMILESX — correção de 30/10/2026 (modo claro, hospedagens, etiquetas e mobile)

Este pacote é **incremental sobre** `DBMILESX_CORRECAO_COMPLETA_ACOMPANHAMENTOS_LIGHT_20261030.zip`. Os arquivos abaixo devem substituir exatamente os caminhos correspondentes da versão integrada, sem copiar módulos antigos de outros ZIPs.

## Alterações

1. **Hospedagens:** a listagem de acompanhamentos agora mostra a classificação de 1 a 5 estrelas, quando presente no serviço, além de nome, check-in, check-out, reserva e botão de edição.
2. **Modo claro:** troca superfícies escuras residuais dos cartões de voo, serviços, painel de roteiro e indicadores de Fluxo de Cálculo por cartões claros e texto escuro. O modo escuro não foi alterado.
3. **Etiquetas:** o modal apresenta o botão `+ Nova etiqueta` mesmo antes de digitar. Digite nome, escolha a cor e use o botão para criá-la no cadastro existente. As etiquetas já aplicadas continuam selecionadas.
4. **Histórico mobile:** reduz tamanhos, compacta os blocos e inicia cada cotação fechada; abrir e fechar detalhes não recarrega a página.
5. **Cotações mobile:** faixas do quadro passam a ficar uma abaixo da outra; topo e filtros reorganizados em grade mobile compacta.
6. **Aguardando:** contém somente cotações que já foram aceitas/enviadas ou criadas manualmente no quadro. Cálculos não aceitos permanecem no Histórico de cálculos. Os cards de Aguardando são revelados de dez em dez, sem trocar de página. **O carregamento do banco permanece limitado a 800 registros, como antes**, portanto não é paginação SQL; trata-se de exibição progressiva no navegador.
7. **Salvar:** no editor, uma falha isolada na consulta de etiquetas é registrada em log e não deve mais impedir a abertura da cotação após salvar. O fluxo de salvamento de serviços e valores foi retestado em banco temporário.

## Diagnóstico do erro de produção

O código de ocorrência `20261030-141230-377939` mostrado na captura **não traz a exceção em si**. Como ela não foi reproduzida pelos testes locais, não é possível afirmar que todos os casos de 500 foram eliminados. Se o erro se repetir:

- Abra **Vercel → Projeto → Logs (Runtime)** e filtre pelo horário do erro;
- Encontre o Python traceback correspondente a `20261030-141230-377939` (ou novo código);
- Remova e oculte senhas, tokens, dados de sessão e dados pessoais antes de compartilhar o traceback.

O banco Neon e os registros existentes não são modificados por este pacote, e não há SQL novo.

## Arquivos alterados

- `app/routers/cadastros.py`
- `app/templates/cadastros/cotacoes.html`
- `app/templates/cadastros/service_tracking.html`
- `app/templates/calculations/history.html`
- `app/templates/partials/tags.html`
- `app/static/js/tags.js`
- `app/static/css/dbm-light-and-compact-20261030.css`
- `app/templates/base.html`
- `tests/test_oct30_mobile_tracking_regressions.py` (novo)

## Commit

```bash
git add app/routers/cadastros.py app/templates/cadastros/cotacoes.html app/templates/cadastros/service_tracking.html app/templates/calculations/history.html app/templates/partials/tags.html app/static/js/tags.js app/static/css/dbm-light-and-compact-20261030.css app/templates/base.html tests/test_oct30_mobile_tracking_regressions.py
git commit -m "fix: compacta historico e quadro mobile, restaura contraste e estrelas"
git push
```

## Validação local

- Templates Jinja: compilação com filtros reais da aplicação passou;
- JS: `node --check` passou;
- Python: compilação passou;
- Pytest: 12 testes direcionados passaram (inclui 6 testes dos pacotes anteriores);
- Não houve teste de produção real (Vercel/Neon) nem validação visual completa no iPhone.
