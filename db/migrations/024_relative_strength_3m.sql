-- Switch relative strength from a 12-month to a 3-month window.
-- Renames the return columns to match the new window. Existing rows hold 12-month
-- returns, so they are cleared here; scanner/relative_strength.py rebuilds them.
-- Run once, as the table owner (admin role).
ALTER TABLE relative_strength RENAME COLUMN stock_return_12m TO stock_return_3m;
ALTER TABLE relative_strength RENAME COLUMN index_return_12m TO index_return_3m;
TRUNCATE relative_strength;
