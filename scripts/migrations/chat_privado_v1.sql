-- DBMILESX CHAT PRIVADO V1
-- Execute UMA VEZ no Neon SQL Editor antes do deploy dos arquivos novos.

ALTER TABLE web_users
ADD COLUMN IF NOT EXISTS contact_id VARCHAR(20);

CREATE UNIQUE INDEX IF NOT EXISTS ix_web_users_contact_id
ON web_users(contact_id)
WHERE contact_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS web_private_chat_messages (
    id SERIAL PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES web_companies(id) ON DELETE CASCADE,
    sender_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    recipient_id INTEGER NOT NULL REFERENCES web_users(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_private_chat_company ON web_private_chat_messages(company_id);
CREATE INDEX IF NOT EXISTS ix_private_chat_sender ON web_private_chat_messages(sender_id);
CREATE INDEX IF NOT EXISTS ix_private_chat_recipient ON web_private_chat_messages(recipient_id);
CREATE INDEX IF NOT EXISTS ix_private_chat_read ON web_private_chat_messages(is_read);
CREATE INDEX IF NOT EXISTS ix_private_chat_created ON web_private_chat_messages(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_private_chat_pair_a ON web_private_chat_messages(company_id, sender_id, recipient_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_private_chat_pair_b ON web_private_chat_messages(company_id, recipient_id, sender_id, created_at DESC);
