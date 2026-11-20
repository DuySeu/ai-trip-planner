-- An answer about hotels keeps its hotel cards in messages.suggestions
ALTER TABLE messages
    DROP CONSTRAINT messages_intent_check,
    ADD CONSTRAINT messages_intent_check CHECK (intent IN (
        'plan_answer', 'plan_editor', 'trip_research', 'travel_advice', 'clarification',
        'ask', 'suggest', 'answer', 'trip_form', 'created_trip', 'canceled_trip', 'hotel_options'
    ));
