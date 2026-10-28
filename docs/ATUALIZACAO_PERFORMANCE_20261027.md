# Atualização DBMILESX — desempenho, check-in e contas

## O que mudou

- **Chat privado e grupo:** abre as 30 mensagens mais recentes, consulta depois somente IDs novos (a cada ~1,6 s com aba ativa), e oferece **Carregar mensagens anteriores** em lotes de 30. O envio de texto aparece imediatamente na tela com estado provisório; a confirmação vem do banco. Conversas abrem 20 de cada vez.
- **Pessoas:** apenas 20 registros são consultados inicialmente; **Carregar mais 20 pessoas** acrescenta o próximo lote sem trocar de tela, mantendo filtros de busca e etiquetas.
- **Histórico de cotações:** 20 cards inicialmente e **Carregar mais 20 cotações** no lugar da navegação obrigatória. O SQL combina os dois tipos de cotação antes da paginação, sem copiar todos os IDs anteriores para Python.
- **Notificações:** carregamento em lotes de 20.
- **Resultado da cotação:** removidos os textos `[cite: 39]`; título, botões, cards e detalhamento com layout responsivo.
- **Check-in:** processamento diário de voos aceitos, registro de aviso na central e tentativa de Web Push nos dispositivos autorizados; deduplicação por voo, data e usuário.
- **E-mail:** bloqueia novo cadastro para e-mails existentes, mesmo pendentes; identificação e índice de unicidade por `lower(trim(email))`.

## Antes de publicar

1. Faça backup do PostgreSQL/Neon de produção.
2. Confirme que computador e celular usam **a mesma URL do aplicativo** e que a implantação usa o **mesmo `DATABASE_URL` de produção**. Se o e-mail da captura tiver duas contas, execute com segurança `python scripts/diagnosticar_contas.py email@exemplo.com` com o ambiente apontando para produção. Não una IDs ou empresas só com base em um endereço: isso pode misturar clientes, chats, permissões e cotações.
3. No Neon, consulte primeiro a query de colisões comentada em `scripts/migrations/checkin_push_unique_email_20261027.sql`. Resolva possíveis duplicidades com validação do dono dos dados. **Não rode a parte do índice único se a consulta retornar colisões.** Depois execute a migração SQL completa.
4. Configure no ambiente de produção as seguintes variáveis **secretas**:
   - `CRON_SECRET`: valor aleatório forte (mínimo 16 caracteres), indispensável para a rotina agendada.
   - `VAPID_PUBLIC_KEY`: chave pública Web Push (base64url).
   - `VAPID_PRIVATE_KEY`: chave privada correspondente (base64url, jamais entregue ao navegador).
   - `VAPID_SUBJECT`: contato, por exemplo `mailto:suporte@seu-dominio.com`.
5. Gere um par VAPID **uma única vez** usando `python scripts/generate_vapid.py` em seu computador. Guarde a chave privada no gerenciador de segredos; se mudar o par, dispositivos já inscritos precisam ativar notificações novamente.
6. Publique o projeto e confirme a rota `/health/db`. Na Vercel, o cron `/internal/cron/checkin` executa diariamente às **12:00 UTC** e exige o token `Authorization: Bearer <CRON_SECRET>`. O cron é disparado apenas na implantação de produção.

## Receber no celular

1. Abra **Notificações** no próprio celular.
2. Toque em **Ativar notificações neste dispositivo** e permita o acesso no sistema operacional.
3. No **iPhone**, adicione primeiro o site à Tela de Início, abra o ícone instalado e faça a ativação por ali (iOS 16.4+). Em Android, Chrome e navegadores com Web Push, basta conceder a permissão quando disponível.
4. Para outro telefone ou computador, repita a ativação naquele dispositivo.

**Limites importantes:** o cron diário não garante aviso no minuto exato da abertura do check-in; horários e regras variam por companhia e aeroporto. O sistema considera a data/hora registrada como horário de Brasília quando não existe fuso no cadastro e tenta notificar dentro da janela de 48h (ou 24h, se configurada). Revise as datas, horários e status dos voos. No plano gratuito Hobby da Vercel, crons têm precisão de até uma hora e frequência máxima diária; para alertas mais precisos, use um agendador de maior frequência em plano compatível.

## Validação

Com as dependências instaladas, execute `python -m pytest tests/test_progressive_features.py tests/test_calculator.py -q`.
Os testes de paginação, histórico SQL, chat incremental e deduplicação de check-in foram executados com SQLite isolado. Para validar entrega real de push, é necessário **publicar**, configurar as chaves, autorizar no aparelho e acompanhar os registros do cron. Nenhum envio real foi executado durante esta atualização.
