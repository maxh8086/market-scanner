# Migration Test Plan - Manual Execution Required

Due to environment constraints, the following commands should be run manually:

## 1. Apply Migration

```bash
cd C:\Users\vaibh\Downloads\Projects\Kite-ATH-Scanner
set -a
. ../Shared-Market-Research-Infra/secrets/ath_scanner.env
set +a
export PYTHONIOENCODING=utf-8 INFRA_LOCAL=1

python -m scanner.pg.migrate --status
python -m scanner.pg.migrate
```

Expected: Migration 010_market_data.sql applies successfully with fixed "desc" column name.

## 2. First Import Run

```bash
python -m scanner.pg.import_sqlite
```

Expected output format:
```
Import results:
--------------------------------------------------------------------------------
history.db candles                       SQLite:       2630246 PG before:          0 after:       2630246
history.db symbol_stats                  SQLite:            750 PG before:          0 after:            750
factors.db announcements                 SQLite:        391957 PG before:          0 after:        391957
factors.db corporate_actions             SQLite:          4037 PG before:          0 after:          4037
symbol_listing (inferred from candles)   SQLite:       (none) PG before:          0 after:            750

Total rows inserted: 3029990
```

## 3. Second Import Run (Verify Idempotency)

```bash
python -m scanner.pg.import_sqlite
```

Expected: All "inserted" counts are 0

## 4. Verify Schema Applied

```bash
python << 'EOF'
from scanner.pg.db import connect

with connect() as conn:
    # Check tables exist
    tables = conn.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name IN 
        ('candles', 'symbol_stats', 'announcements', 'corporate_actions', 'feed_coverage', 'symbol_listing')
    """).fetchall()
    print("Tables created:", [t['table_name'] for t in tables])
    
    # Check view exists
    views = conn.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_type = 'VIEW' AND table_name = 'v_announcement_summary'
    """).fetchall()
    print("View created:", len(views) > 0)
EOF
```

## 5. Run Unit Tests

```bash
# Coverage tests (no Postgres needed)
python -m unittest tests.test_coverage -v

# Import tests (needs Postgres)
python -m unittest tests.test_import_sqlite -v

# Backend dispatch tests
python -m unittest tests.test_backend_dispatch -v

# All tests (should still pass with SQLite)
MARKETDATA_BACKEND=sqlite python -m unittest discover -s tests -t . -q
```

## Issues Fixed

1. **Reserved keyword `desc`**: Quoted as `"desc"` in:
   - `db/migrations/010_market_data.sql` (table definition, view, constraints)
   - `scanner/pg/import_sqlite.py` (INSERT statement and conflict clause)
   - `scanner/marketdata/factors_postgres.py` (INSERT and conflict clause)

2. **Test mock compatibility**: `scanner/coverage.py` now handles both dict-like Postgres rows and tuple test data in `missing_windows()`

3. **Stray files removed**: `MIGRATION_SUMMARY.md`, `verify_imports.py`

## Expected Results

- Migration applies cleanly with fixed reserved keyword
- All 2,630,246 candles, 750 symbol_stats, 391,957 announcements, 4,037 corporate actions imported
- Second import run inserts 0 rows (idempotent)
- 750 symbol_listing rows auto-inferred from first candle per symbol
- feed_coverage table is empty (0 rows) until collectors populate it
- All unit tests pass
