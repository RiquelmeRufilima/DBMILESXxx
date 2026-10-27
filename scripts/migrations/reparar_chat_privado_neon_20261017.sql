-- DBMILESX - CORREÇÃO DO CHAT PRIVADO / AGENDA
-- Execute no Neon > SQL Editor.
-- Seguro para rodar mais de uma vez.

ALTER TABLE web_users
ADD COLUMN IF NOT EXISTS contact_id VARCHAR(20);

CREATE UNIQUE INDEX IF NOT EXISTS ix_web_users_contact_id
ON web_users(contact_id)
WHERE contact_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS web_user_chat_contacts (
    id SERIAL PRIMARY KEY,
    owner_user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    contact_user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_web_user_chat_contacts_owner
ON web_user_chat_contacts(owner_user_id);
CREATE INDEX IF NOT EXISTS ix_web_user_chat_contacts_contact
ON web_user_chat_contacts(contact_user_id);
CREATE INDEX IF NOT EXISTS ix_web_user_chat_contacts_created
ON web_user_chat_contacts(created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_web_user_chat_contacts_pair
ON web_user_chat_contacts(owner_user_id, contact_user_id);

CREATE TABLE IF NOT EXISTS web_private_chat_messages (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NULL REFERENCES web_companies(id) ON DELETE SET NULL,
    sender_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    recipient_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

ALTER TABLE web_private_chat_messages ADD COLUMN IF NOT EXISTS company_id INTEGER;
ALTER TABLE web_private_chat_messages ADD COLUMN IF NOT EXISTS sender_id INTEGER;
ALTER TABLE web_private_chat_messages ADD COLUMN IF NOT EXISTS recipient_id INTEGER;
ALTER TABLE web_private_chat_messages ADD COLUMN IF NOT EXISTS message TEXT;
ALTER TABLE web_private_chat_messages ADD COLUMN IF NOT EXISTS is_read BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE web_private_chat_messages ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW();
ALTER TABLE web_private_chat_messages ALTER COLUMN company_id DROP NOT NULL;

CREATE INDEX IF NOT EXISTS ix_private_chat_company ON web_private_chat_messages(company_id);
CREATE INDEX IF NOT EXISTS ix_private_chat_sender ON web_private_chat_messages(sender_id);
CREATE INDEX IF NOT EXISTS ix_private_chat_recipient ON web_private_chat_messages(recipient_id);
CREATE INDEX IF NOT EXISTS ix_private_chat_read ON web_private_chat_messages(is_read);
CREATE INDEX IF NOT EXISTS ix_private_chat_created ON web_private_chat_messages(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_private_chat_pair_sender ON web_private_chat_messages(sender_id, recipient_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_private_chat_pair_recipient ON web_private_chat_messages(recipient_id, sender_id, created_at DESC);

SELECT
  EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'web_users' AND column_name = 'contact_id'
  ) AS contact_id_ok,
  to_regclass('public.web_user_chat_contacts') IS NOT NULL AS agenda_ok,
  to_regclass('public.web_private_chat_messages') IS NOT NULL AS privado_ok;
