-- The chat model the visitor picked for a conversation; null uses the CHAT_MODELS chain ("Auto").
-- Not checked against a model list: that list changes with scripts/sync_models.sh and the provider
ALTER TABLE conversations ADD COLUMN chat_model text CHECK (char_length(chat_model) <= 200);
