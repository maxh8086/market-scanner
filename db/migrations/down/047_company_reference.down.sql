-- Reverts 047_company_reference.sql.
DROP VIEW IF EXISTS company_reference_by_isin;
DROP TABLE IF EXISTS company_reference;
