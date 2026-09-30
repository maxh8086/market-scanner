"""Load the document store into Neo4j, read graph facts back, and purge expired data.

    python graph_sync.py load          # filings + extractions + fundamentals
    python graph_sync.py conclusions   # conclusions
    python graph_sync.py facts         # write data/graph_facts.json
    python graph_sync.py purge         # delete expired + processed nodes (and TinyDB rows)
    python graph_sync.py status        # node counts
    python graph_sync.py <cmd> --dry-run   # show what would happen, change nothing

Connection: NEO4J_URI (default bolt://localhost:7687), NEO4J_USER, NEO4J_PASSWORD.
Retention: config/retention.json (years, purge on/off) -- see scanner/retention.py.
The graph is an accelerator, never a dependency: if Neo4j is unreachable this exits 3
and the rest of the pipeline carries on without graph facts.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scanner import docstore, graph, retention

FACTS_PATH = Path("data/graph_facts.json")


def _all(db, table: str) -> list[dict]:
    return [dict(d) for d in db.table(table).all()]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["load", "conclusions", "facts", "purge", "status", "announcements"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--wait", type=int, default=120, help="seconds to wait for Neo4j")
    args = p.parse_args(argv)

    cfg = retention.load()
    db = docstore.open_db()

    if args.dry_run:
        if args.command == "purge":
            print(f"retention: {cfg}")
            print("docstore would purge:", retention.purge_docstore(db, cfg, dry_run=True))
        else:
            s = docstore.stats(db)
            print(f"would run '{args.command}' against {s['filings']} filings, "
                  f"{s['extractions']} extractions, {s['conclusions']} conclusions")
        db.close()
        return 0

    try:
        g = graph.Graph(graph.connect(), cfg)
        ready = g.wait_ready(args.wait)
    except Exception as e:                   # noqa: BLE001
        print(f"Neo4j unavailable ({type(e).__name__}); continuing without the graph.",
              file=sys.stderr)
        db.close()
        return 3
    if not ready:
        print("Neo4j not reachable; continuing without the graph.", file=sys.stderr)
        db.close()
        return 3

    try:
        g.ensure_schema()
        if args.command == "load":
            n = (g.load_filings(_all(db, docstore.FILINGS)),
                 g.load_extractions(_all(db, docstore.EXTRACTIONS)),
                 g.load_fundamentals(_all(db, docstore.FUNDAMENTALS)))
            print(f"loaded {n[0]} filings, {n[1]} extractions, {n[2]} fundamentals")
        elif args.command == "conclusions":
            print(f"loaded {g.load_conclusions(_all(db, docstore.CONCLUSIONS))} conclusions")
        elif args.command == "announcements":
            try:
                from scanner import pg
                with pg.connect() as conn:
                    rows = conn.execute(
                        "SELECT symbol, isin, category, n, first_date, last_date "
                        "FROM v_announcement_summary"
                    ).fetchall()
                # Convert to dicts
                rows = [dict(r) for r in rows] if rows else []
                n = g.sync_announcement_summary(rows)
                print(f"synced {n} announcement summaries")
            except Exception as e:  # noqa: BLE001
                print(f"announcement sync failed ({type(e).__name__}: {e}); "
                      "the Postgres view v_announcement_summary may not exist yet")
        elif args.command == "facts":
            facts = g.facts()
            FACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            FACTS_PATH.write_text(json.dumps(facts, indent=1), encoding="utf-8")
            print(f"graph facts for {len(facts)} companies -> {FACTS_PATH}")
        elif args.command == "purge":
            if not cfg.purge:
                print(f"purge is off in config/retention.json ({cfg.years}y kept, nothing deleted)")
            else:
                print("graph purged:", g.purge())
                print("docstore purged:", retention.purge_docstore(db, cfg))
        if args.command in ("load", "purge", "status"):
            print("graph now:", g.status())
    finally:
        g.close()
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
