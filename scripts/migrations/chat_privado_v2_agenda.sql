-- DBMILESX CHAT PRIVADO V2 — AGENDA + CONVERSAS SEM EMPRESA
-- Execute UMA VEZ no Neon SQL Editor.

-- ID público de contato.
ALTER TABLE web_users
ADD COLUMN IF NOT EXISTS contact_id VARCHAR(20);

CREATE UNIQUE INDEX IF NOT EXISTS ix_web_users_contact_id
ON web_users(contact_id)
WHERE contact_id IS NOT NULL;

-- Agenda pessoal.
CREATE TABLE IF NOT EXISTS web_user_chat_contacts (
    id SERIAL PRIMARY KEY,
    owner_user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    contact_user_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_web_user_chat_contact UNIQUE(owner_user_id, contact_user_id),
    CONSTRAINT ck_web_user_chat_contact_not_self CHECK(owner_user_id <> contact_user_id)
);

CREATE INDEX IF NOT EXISTS ix_user_chat_contacts_owner
ON web_user_chat_contacts(owner_user_id);

CREATE INDEX IF NOT EXISTS ix_user_chat_contacts_contact
ON web_user_chat_contacts(contact_user_id);

-- Chat privado.
CREATE TABLE IF NOT EXISTS web_private_chat_messages (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NULL REFERENCES web_companies(id) ON DELETE SET NULL,
    sender_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    recipient_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

-- Se a V1 já criou company_id como obrigatório, libera o privado sem empresa.
ALTER TABLE web_private_chat_messages
ALTER COLUMN company_id DROP NOT NULL;

CREATE INDEX IF NOT EXISTS ix_private_chat_sender ON web_private_chat_messages(sender_id);
CREATE INDEX IF NOT EXISTS ix_private_chat_recipient ON web_private_chat_messages(recipient_id);
CREATE INDEX IF NOT EXISTS ix_private_chat_read ON web_private_chat_messages(is_read);
CREATE INDEX IF NOT EXISTS ix_private_chat_created ON web_private_chat_messages(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_private_chat_pair_a ON web_private_chat_messages(sender_id, recipient_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_private_chat_pair_b ON web_private_chat_messages(recipient_id, sender_id, created_at DESC);
