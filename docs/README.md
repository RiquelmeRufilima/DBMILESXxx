# DBMILESX Web V5

A V5 é a evolução da primeira versão web do DBMILESX. Ela mantém o backend em **Python + FastAPI** e acrescenta as telas e fluxos que estavam faltando na V4, sem alterar as fórmulas legadas das companhias existentes.

## O que entrou na V5

### Navegação e visual

- nova **Tela de início** com atalhos e mais ícones;
- menu para computador e navegação móvel;
- logos reais do DBMILESX na tela de login e dentro do sistema;
- ícone azul do DBMILESX como favicon, PWA e atalho do Windows;
- interface responsiva para PC, tablet, Android e iPhone;
- modo claro, escuro ou conforme o sistema;
- seis paletas prontas;
- cor principal personalizada;
- fundo em gradiente, suave ou liso;
- modo compacto para telas com muita informação.

### Conta e equipe

- **Perfil** com dados pessoais e foto;
- **Configurações** de aparência e notificações;
- **Notificações** internas com contador de não lidas;
- **Chat da empresa**;
- **Painel administrativo** para administradores e gerentes;
- **Painel de membro** para usuários comuns;
- área da empresa e visão da equipe.

### Solicitações de cotação por link

- criação de links públicos de cotação;
- formulário que o cliente abre sem login;
- escolha de ida, ida e volta ou multitrecho;
- datas, passageiros, crianças, bebês, bagagens e observações;
- caixa de entrada de solicitações;
- notificação quando chega um novo pedido;
- botão para transformar a solicitação diretamente em uma cotação.

### Calculadora e cotações

- **Nova cotação limpa**;
- botão para **limpar a cotação**;
- **editar uma cotação existente**;
- duplicar/reaproveitar uma cotação;
- preencher a calculadora a partir de uma solicitação recebida;
- tipo de viagem:
  - somente ida;
  - ida e volta;
  - multitrecho;
- datas de ida e volta;
- vários trechos no modo multitrecho;
- nome e contato do cliente;
- observações;
- histórico com busca e detalhamento;
- acesso aos resultados, edição e documentos a partir do histórico.

### Companhias personalizadas

Além das companhias legadas protegidas, o usuário pode criar uma **companhia genérica e customizável**.

O nome é obrigatório. São opcionais:

- logo;
- cor;
- descrição.

O primeiro tipo de cálculo já nasce com a fórmula padrão:

```text
(milhas * milheiro) + taxa
```

O usuário decide se o resultado:

- já representa o total de todos os passageiros; ou
- deve ser multiplicado pela quantidade de passageiros.

Também pode criar campos próprios, por exemplo:

```text
milhas
milheiro
taxa
desconto
juros
taxa_adicional
desconto_taxa
valor_dinheiro
taxa_resgate
numero_trechos
```

Exemplos de fórmulas:

```text
(milhas * milheiro) + taxa
```

```text
((milhas * milheiro) + taxa) * (1 - desconto / 100)
```

```text
((milhas * milheiro) + taxa) * (1 + juros / 100)
```

```text
(milhas * milheiro) + (taxa * (1 - desconto_taxa / 100))
```

Variáveis automáticas disponíveis:

```text
passageiros
bebes
bagagens
```

Uma mesma companhia pode receber vários tipos de cálculo. O motor de fórmula é restrito e **não usa `eval()` livre**.

## Fórmulas existentes preservadas

As regras atuais continuam em:

```text
app/services/calculator.py
```

A modernização não altera a matemática das companhias existentes:

- LATAM;
- GOL / Smiles;
- GOL Deságio;
- Azul Pontos;
- Azul Pontos + Dinheiro;
- American;
- Azul Pelo Mundo.

O custo adicional continua sendo somado depois da regra principal.

## Documentos em PDF

A V5 separa três documentos:

1. **PDF de cotação/proposta** — documento para o cliente, sem revelar o custo interno;
2. **PDF de custo** — relatório interno com o valor calculado;
3. **PDF de lucro** — custo, valor de venda, lucro e margem.

Os PDFs usam HTML + CSS:

```text
app/templates/pdf/quote.html
app/templates/pdf/cost.html
app/templates/pdf/profit.html
app/static/css/pdf.css
```

A renderização é feita pelo Chromium por meio do Playwright.

## Histórico antigo e atualização da V4

A V5 não apaga o banco da V4.

Na inicialização, ela:

- cria somente as tabelas novas que estiverem faltando;
- mantém usuários, empresas, cotações e histórico já existentes;
- recupera os detalhes de viagem possíveis das cotações antigas;
- não altera cotações que já possuem os novos detalhes.

O backfill é idempotente: pode iniciar o sistema várias vezes sem duplicar os detalhes.

## Atualizar a instalação que já está em `C:\sistema_aereo`

Use o pacote **ATUALIZACAO_DBMILESX_V5.zip**.

1. Feche a janela `DBMILESX Server`.
2. Faça uma cópia de segurança destas pastas:

```text
C:\sistema_aereo\data
C:\sistema_aereo\uploads
```

3. Extraia o conteúdo do ZIP diretamente em:

```text
C:\sistema_aereo
```

4. Quando o Windows perguntar, escolha:

```text
Mesclar pastas
Substituir arquivos no destino
```

5. Abra:

```text
iniciar_app.bat
```

Para esta atualização não é necessário apagar a `.venv` nem executar `instalar.bat` novamente. A V5 usa as mesmas dependências principais da V4.

### O pacote de atualização não contém

- banco de dados;
- chave secreta;
- fotos de perfil;
- logos enviadas pelos usuários;
- ambiente `.venv`.

Portanto, ele foi preparado para preservar seus dados existentes.

## Instalação limpa em outro computador

Use o pacote completo **DBMILESX_WEB_V5_COMPLETO.zip**.

1. Extraia em um local fora do OneDrive, por exemplo:

```text
C:\sistema_aereo
```

2. Execute uma vez:

```text
instalar.bat
```

3. Depois, para uso diário:

```text
iniciar_app.bat
```

4. Opcionalmente crie o atalho:

```text
criar_atalho_desktop.bat
```

## Inicialização melhorada

O `iniciar_app.bat` da V5 não abre mais o navegador depois de uma espera fixa. Agora ele:

1. inicia o servidor;
2. consulta `/health` até o sistema responder;
3. somente então abre o navegador em modo de aplicativo.

Isso evita a impressão de travamento quando o Python ainda está iniciando.

## Acesso local e pela rede

No computador principal:

```text
http://127.0.0.1:8000
```

Em outro computador ou celular conectado à mesma rede, use o endereço mostrado pelo inicializador, por exemplo:

```text
http://192.168.0.10:8000
```

O computador principal precisa permanecer ligado enquanto os demais usam o sistema local.

## Onde rodar

Para desenvolvimento e uso local, prefira:

```text
C:\sistema_aereo
```

Evite executar o banco SQLite e a `.venv` diretamente dentro do OneDrive. O OneDrive pode ser usado para guardar o ZIP da versão e backups, enquanto cada computador executa uma cópia local.

## Banco de dados

Sem `DATABASE_URL`, a aplicação usa:

```text
data/dbmilesx_web.db
```

Em hospedagem futura, pode usar PostgreSQL:

```text
DATABASE_URL=postgresql+psycopg://usuario:senha@servidor:5432/dbmilesx
```

## Estrutura principal

```text
DBMILESX_WEB_V5/
├── app/
│   ├── main.py
│   ├── models.py
│   ├── database.py
│   ├── routers/
│   ├── services/
│   ├── templates/
│   └── static/
├── data/
├── uploads/
├── tests/
├── run.py
├── requirements.txt
├── instalar.bat
├── iniciar_app.bat
└── Dockerfile
```

## Segurança dos arquivos

Nunca compartilhe junto com a versão pública:

```text
data/dbmilesx_web.db
data/.secret_key
.env
```

O ZIP completo entregue aqui foi limpo para não incluir esses arquivos.

## Limites atuais

A V5 é uma versão local e ainda não é uma implantação de produção para milhares de usuários. Para a etapa pública em grande escala, ainda será necessário adicionar:

- PostgreSQL de produção;
- migrações formais com Alembic;
- HTTPS;
- armazenamento externo de imagens;
- Redis para chat em múltiplos servidores;
- backups automatizados;
- logs e monitoramento;
- política de recuperação de senha por e-mail.

A arquitetura FastAPI + HTML/CSS/JS já foi organizada para permitir essa evolução sem refazer as fórmulas da calculadora.
