-- Trips are kept until their user deletes them; nothing expires them any more
DROP INDEX trips_expires_at_idx;
ALTER TABLE trips DROP COLUMN expires_at;
