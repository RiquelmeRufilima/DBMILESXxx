-- Execute uma vez no MESMO PostgreSQL (DATABASE_URL) usado por produção.
-- Antes do índice, confira colisões (maiúsculas, espaços ou dados legados):
-- SELECT lower(trim(email)) AS email, count(*), array_agg(id ORDER BY id) AS ids
-- FROM web_users GROUP BY lower(trim(email)) HAVING count(*) > 1;
-- Se houver colisões, NÃO apague registros automaticamente. Confirme propriedade,
-- empresa e dependências antes de migrar/mesclar as contas.

CREATE TABLE IF NOT EXISTS web_push_subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_web_push_subscriptions_user_id ON web_push_subscriptions(user_id);

CREATE TABLE IF NOT EXISTS web_checkin_reminders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    flight_key VARCHAR(120) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_checkin_user_flight UNIQUE (user_id, flight_key)
);
CREATE INDEX IF NOT EXISTS ix_web_checkin_reminders_user_id ON web_checkin_reminders(user_id);

-- Rejeita duas contas com o mesmo e-mail mesmo que variem maiúsculas/espaços.
-- Se houver duplicatas legadas, este comando falha até serem reconciliadas.
CREATE UNIQUE INDEX IF NOT EXISTS ux_web_users_email_normalized
    ON web_users (lower(trim(email)));

-- Índices para abrir abas e buscar somente lotes recentes.
CREATE INDEX IF NOT EXISTS ix_chat_company_recent ON web_chat_messages(company_id, id);
CREATE INDEX IF NOT EXISTS ix_pv_sender_recipient_recent ON web_private_chat_messages(sender_id, recipient_id, id);
CREATE INDEX IF NOT EXISTS ix_pv_recipient_sender_recent ON web_private_chat_messages(recipient_id, sender_id, id);
CREATE INDEX IF NOT EXISTS ix_pv_unread_recipient ON web_private_chat_messages(recipient_id, is_read);
CREATE INDEX IF NOT EXISTS ix_person_company_progress ON web_persons(company_id, is_complete, created_at, id);
CREATE INDEX IF NOT EXISTS ix_person_user_progress ON web_persons(user_id, is_complete, created_at, id);
