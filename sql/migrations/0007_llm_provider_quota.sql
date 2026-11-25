-- LLM_PROVIDER picks one of three providers; each one's daily quota block is kept under its own name
ALTER TABLE quota_blocks DROP CONSTRAINT quota_blocks_service_check;
ALTER TABLE quota_blocks ADD CONSTRAINT quota_blocks_service_check CHECK (service IN (
    'openrouter', 'openai', 'bedrock', 'tavily'
));
