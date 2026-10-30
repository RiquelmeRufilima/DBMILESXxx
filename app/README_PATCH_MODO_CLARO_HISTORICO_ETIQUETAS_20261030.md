# DBMILESX — modo claro, chat, histórico mobile e filtro múltiplo por etiquetas

## Ajustes incluídos

1. **Barra lateral no modo claro**
   - adicionada borda mais visível;
   - melhor contraste nos grupos e links do menu;
   - acabamento melhor no menu lateral mobile.

2. **Chat no modo claro**
   - fundo da conversa com contraste mais suave;
   - coluna lateral e cabeçalho mais claros;
   - mensagens com leitura melhor no modo claro.

3. **Histórico mobile**
   - cards mais compactos;
   - textos menores para caber melhor na tela;
   - botões reorganizados em grade;
   - blocos escuros do modo claro ficaram claros.

4. **Etiquetas**
   - ao clicar em uma etiqueta do card, o sistema agora preserva as etiquetas já filtradas e adiciona a nova;
   - o filtro passa a funcionar com múltiplas etiquetas de forma mais natural.

5. **Cache busting**
   - versão do `app.css` atualizada para forçar recarregamento;
   - versão do `tags.js` atualizada para evitar cache antigo.

## Arquivos alterados

- `app/static/css/app.css`
- `app/static/js/tags.js`
- `app/templates/base.html`
- `app/templates/partials/tags.html`
- `app/templates/chat/index.html`
- `app/templates/calculations/history.html`

## Instalação

Substitua os arquivos do projeto pelos arquivos deste pacote e faça o deploy.

Sugestão de commit:

```bash
git add app/static/css/app.css app/static/js/tags.js app/templates/base.html app/templates/partials/tags.html app/templates/chat/index.html app/templates/calculations/history.html

git commit -m "feat: melhora modo claro, histórico mobile e filtro múltiplo por etiquetas"

git push
```
