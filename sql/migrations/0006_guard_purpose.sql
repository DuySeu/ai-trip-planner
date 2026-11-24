-- The chat guardrail's topic check is its own purpose, so its calls can be told from the router's
ALTER TABLE llm_calls DROP CONSTRAINT llm_calls_purpose_check;
ALTER TABLE llm_calls ADD CONSTRAINT llm_calls_purpose_check CHECK (purpose IN (
    'generate', 'repair', 'classify', 'edit', 'answer', 'discover', 'suggest', 'guard'
));
