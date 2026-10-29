# DBMILESX — auditoria local de segurança (29/10/2026)

## Alterações entregues
- Limite por e-mail: **7 erros de senha em janela móvel de 15 minutos**, mantendo limite por IP de 20 falhas em 15 minutos.
- Sessões sem `auth_version` válido deixam de ser aceitas: o usuário precisa autenticar novamente. Cookies com versão diferente da atual continuam sendo recusados.
- Removida chave duplicada `reservation_lookup` do dicionário de limites (o limite efetivo preservado é 30 em 10 minutos).
- Teste de força bruta atualizado para 7 tentativas.

## Testes
`python -m pytest tests/test_security.py -q` → **33 passed** em SQLite temporário; não houve testes ofensivos em produção. Avisos depreciação para `datetime.utcnow()` permanecem.

## ACL / AAA — achados e pendências
- **Autenticação**: hash de senha, CSRF no formulário, limitação de login e versão de sessão já existiam no repositório.
- **Autorização/ACL**: existem verificações de `company_id` em diversas rotas, mas esta entrega NÃO é uma auditoria exaustiva de cada endpoint. Revisar todas as consultas e gravações multitenant, especialmente novas rotas e downloads, com testes de IDOR.
- **Auditoria/accounting**: existe log de tentativas no banco (`web_auth_attempts`), mas não um trilho centralizado e completo de ações administrativas, edições e exclusões. Recomenda-se tabela de eventos imutáveis por usuário/empresa e política de retenção.
- **Falha do limitador**: `seconds_until_allowed` atualmente retorna 0 quando a proteção do banco falha (fail-open). Recomenda-se monitoramento de alertas e estratégia fail-closed controlada/redundante para ambientes produtivos.
- **Corrida entre requisições**: o modelo atual conta tentativas antes do login e grava após a falha; ataques paralelos podem ultrapassar o limite temporariamente. Para limitação estrita, implemente contador atômico por chave em Redis/Upstash ou transações com lock por chave, e WAF da Vercel.
- **IP por proxy**: `client_ip()` usa cabeçalhos de encaminhamento. Garanta proxy confiável; cabeçalhos forjados podem prejudicar limites por IP em outros ambientes.
- **Google OAuth**: o bloqueio de 7 erros se aplica ao login por senha local. O fluxo Google é controlado pelo provedor e precisa de controles próprios contra abuso.
- **MFA**: recomendado para administradores, preferencialmente TOTP/passkeys, com recuperação segura.
- **Session cookies**: `SESSION_HTTPS_ONLY=1` deve estar ativo em produção; confira `SECRET_KEY` forte e exclusivo, HTTPS, tempo de sessão e rotação de segredos.

## Implantação
1. Salve um backup/commit do estado atual.
2. Copie só os três arquivos do ZIP preservando seus caminhos.
3. Rode `python -m pytest tests/test_security.py -q` em ambiente de teste e publique na Vercel.
4. Usuários com cookies antigos poderão precisar entrar novamente.
5. Não é necessária migração SQL para os arquivos alterados.
