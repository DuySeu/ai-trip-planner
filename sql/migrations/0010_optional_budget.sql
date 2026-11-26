-- The visitor may leave the budget to the planner: amount and scope are then both null
ALTER TABLE trips ALTER COLUMN budget_amount DROP NOT NULL;
ALTER TABLE trips ALTER COLUMN budget_scope DROP NOT NULL;
ALTER TABLE trips ADD CONSTRAINT trips_budget_pair CHECK ((budget_amount IS NULL) = (budget_scope IS NULL));
