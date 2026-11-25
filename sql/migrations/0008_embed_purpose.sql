-- Embedding calls (the guardrail's embedding guard) are logged as their own purpose
ALTER TABLE llm_calls DROP CONSTRAINT llm_calls_purpose_check;
ALTER TABLE llm_calls ADD CONSTRAINT llm_calls_purpose_check CHECK (purpose IN (
    'generate', 'repair', 'classify', 'edit', 'answer', 'discover', 'suggest', 'guard', 'embed'
));
