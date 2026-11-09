-- Fundamentals in long format: one row per (company, section, period, label).
-- Row sets differ by company (banks, non-banks, companies with different templates), so no
-- column is created per label. Design: docs/designs/fundamentals-tables.md.
--
-- NOT APPLIED. scanner/pg/migrate.py applies every pending file on the next start.ps1 run.
-- Apply only after the user approves.

-- Every value as shown on the source page.
CREATE TABLE fund_line (
  symbol      text NOT NULL,
  section     text NOT NULL CHECK (section IN
                ('quarters', 'profit_loss', 'balance_sheet', 'cash_flow', 'ratios', 'shareholding')),
  period      text NOT NULL,           -- as shown: 'Mar 2025', 'Sep 2025', 'TTM'
  period_end  date,                    -- NULL for TTM and other non-date periods
  label       text NOT NULL,           -- as shown, footnote '+' stripped
  canonical   text,                    -- from fund_row_map; NULL when unmapped (kept, not dropped)
  value       numeric,                 -- NULL when the cell is blank or '-'
  raw         text,                    -- cell text exactly as shown
  source      text NOT NULL DEFAULT 'screener' CHECK (source IN ('screener', 'nse')),
  fetched_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (symbol, section, period, label, source)
);
CREATE INDEX fund_line_canonical_idx ON fund_line (symbol, canonical);
CREATE INDEX fund_line_period_end_idx ON fund_line (symbol, period_end);

-- Maps a page label to a canonical field. Companies use different labels for the same item
-- (for example Revenue for Sales on bank pages, Borrowing for Borrowings).
CREATE TABLE fund_row_map (
  section    text NOT NULL,
  label      text NOT NULL,
  canonical  text NOT NULL,
  PRIMARY KEY (section, label)
);

-- Current key ratios and holding data, one row per company.
CREATE TABLE fund_snapshot (
  symbol               text PRIMARY KEY,
  key_ratios           jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {name: value}, as shown
  key_ratio_basis      jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {name: how it was derived}
  pledge_pct           numeric,
  promoter_holding_pct numeric,
  fetched_at           timestamptz NOT NULL DEFAULT now()
);

-- Compounded growth as shown on the page (10y, 5y, 3y, TTM).
CREATE TABLE fund_growth (
  symbol   text NOT NULL,
  horizon  text NOT NULL CHECK (horizon IN ('10y', '5y', '3y', 'TTM')),
  value    numeric,
  raw      text,
  PRIMARY KEY (symbol, horizon)
);

-- Same grant pattern as 026: the app role reads and writes, no DELETE.
GRANT SELECT, INSERT, UPDATE ON fund_line, fund_row_map, fund_snapshot, fund_growth TO market_scanner_app;
