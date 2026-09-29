"""Neo4j graph of the run's documents, and the facts only a graph shows.

The document store (TinyDB) stays the system of record. During a run every
filing, its AI extraction, each stock's conclusion and fundamentals are loaded
into Neo4j so cross-document questions become one query: how many *different*
customers does a company have, is an order from a repeat customer, which other
companies sell to the same customer.

    (Company)-[:FILED]->(Filing)-[:YIELDED]->(Extraction)-[:WITH]->(Counterparty)
    (Company)-[:CONCLUDED]->(Conclusion)          (Company)-[:HAS]->(Fundamentals)

Every node carries ``expires_at`` (scanner/retention.py). Neo4j Community has no
TTL, so ``purge`` deletes nodes that are past that date *and processed* (a filing
is processed once it has an extraction; conclusions and fundamentals are
processed by definition), then removes counterparties and companies left with
nothing attached.

The driver is imported lazily and injected in tests; no query here is built by
string-formatting data -- values always go in as parameters.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date
from typing import Any, Iterable, Optional

from scanner import retention

BATCH = 200
SCHEMA_QUERIES = (
    "CREATE CONSTRAINT company_symbol IF NOT EXISTS FOR (n:Company) REQUIRE n.symbol IS UNIQUE",
    "CREATE CONSTRAINT filing_id IF NOT EXISTS FOR (n:Filing) REQUIRE n.seq_id IS UNIQUE",
    "CREATE CONSTRAINT extraction_key IF NOT EXISTS FOR (n:Extraction) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT counterparty_name IF NOT EXISTS FOR (n:Counterparty) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT conclusion_key IF NOT EXISTS FOR (n:Conclusion) REQUIRE n.key IS UNIQUE",
    "CREATE CONSTRAINT fundamentals_symbol IF NOT EXISTS FOR (n:Fundamentals) REQUIRE n.symbol IS UNIQUE",
    "CREATE INDEX filing_expiry IF NOT EXISTS FOR (n:Filing) ON (n.expires_at)",
    "CREATE INDEX conclusion_expiry IF NOT EXISTS FOR (n:Conclusion) ON (n.expires_at)",
)

LOAD_FILINGS = """
UNWIND $rows AS r
MERGE (c:Company {symbol: r.symbol})
MERGE (f:Filing {seq_id: r.seq_id})
SET f.symbol = r.symbol, f.isin = r.isin, f.kind = r.kind, f.desc = r.desc,
    f.an_date = r.an_date, f.url = r.url, f.text = r.text, f.expires_at = r.expires_at,
    f.processed = coalesce(f.processed, false)
MERGE (c)-[:FILED]->(f)
"""

LOAD_EXTRACTIONS = """
UNWIND $rows AS r
MATCH (f:Filing {seq_id: r.seq_id})
MERGE (e:Extraction {key: r.key})
SET e.seq_id = r.seq_id, e.kind = r.kind, e.symbol = r.symbol, e.model = r.model,
    e.order_value_inr = r.order_value_inr, e.execution_months = r.execution_months,
    e.data = r.data, e.expires_at = r.expires_at
MERGE (f)-[:YIELDED]->(e)
SET f.processed = true
WITH e, r WHERE r.counterparty IS NOT NULL
MERGE (p:Counterparty {name: r.counterparty})
SET p.type = coalesce(r.counterparty_type, p.type)
MERGE (e)-[:WITH]->(p)
"""

LOAD_CONCLUSIONS = """
UNWIND $rows AS r
MERGE (c:Company {symbol: r.symbol})
MERGE (k:Conclusion {key: r.key})
SET k.symbol = r.symbol, k.as_of = r.as_of, k.stance = r.stance, k.score = r.score,
    k.conclusion = r.conclusion, k.model = r.model, k.expires_at = r.expires_at
MERGE (c)-[:CONCLUDED]->(k)
"""

LOAD_FUNDAMENTALS = """
UNWIND $rows AS r
MERGE (c:Company {symbol: r.symbol})
MERGE (u:Fundamentals {symbol: r.symbol})
SET u.data = r.data, u.expires_at = r.expires_at
MERGE (c)-[:HAS]->(u)
"""

# One row per company that has at least one extracted counterparty.
FACTS = """
MATCH (c:Company)-[:FILED]->(:Filing)-[:YIELDED]->(e:Extraction)-[:WITH]->(p:Counterparty)
WITH c, p, count(DISTINCT e) AS orders
WITH c, collect({name: p.name, orders: orders}) AS customers
OPTIONAL MATCH (c)-[:FILED]->(:Filing)-[:YIELDED]->(:Extraction)-[:WITH]->(:Counterparty)
      <-[:WITH]-(:Extraction)<-[:YIELDED]-(:Filing)<-[:FILED]-(peer:Company)
WHERE peer <> c
WITH c, customers, collect(DISTINCT peer.symbol) AS peers
RETURN c.symbol AS symbol,
       size(customers) AS distinct_customers,
       [x IN customers WHERE x.orders > 1 | x.name] AS repeat_customers,
       peers[..5] AS peers_sharing_customer
"""

# (label, query); each returns the number of nodes it deleted as ``n``.
PURGE_QUERIES = (
    ("filings", """
        MATCH (f:Filing) WHERE f.expires_at < $today AND ($any OR f.processed = true)
        OPTIONAL MATCH (f)-[:YIELDED]->(e:Extraction)
        WITH f, collect(e) AS es
        FOREACH (x IN es | DETACH DELETE x)
        DETACH DELETE f
        RETURN count(f) AS n"""),
    ("conclusions", """
        MATCH (k:Conclusion) WHERE k.expires_at < $today
        DETACH DELETE k RETURN count(k) AS n"""),
    ("fundamentals", """
        MATCH (u:Fundamentals) WHERE u.expires_at < $today
        DETACH DELETE u RETURN count(u) AS n"""),
    ("counterparties", """
        MATCH (p:Counterparty) WHERE NOT (p)<-[:WITH]-()
        DETACH DELETE p RETURN count(p) AS n"""),
    ("companies", """
        MATCH (c:Company) WHERE NOT (c)-[]->()
        DETACH DELETE c RETURN count(c) AS n"""),
)

STATUS = "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS n ORDER BY label"

_NO_NAME = {"not stated", "not specified", "n/a", "na", "none", "null", "unknown", "undisclosed"}


def _clean(value: Any) -> Any:
    """Neo4j properties must be primitives (or lists of them); nested data goes in as JSON."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _batches(rows: list, size: int = BATCH) -> Iterable[list]:
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def _norm_name(name: Any) -> Optional[str]:
    """Counterparty as written in the filing, whitespace-collapsed; None if not a real name."""
    text = " ".join(str(name or "").split())
    if len(text) < 3 or text.lower() in _NO_NAME:
        return None
    return text[:120]


def connect(uri: Optional[str] = None, user: Optional[str] = None,
            password: Optional[str] = None):
    """Open a driver from arguments, NEO4J_URI, and NEO4J_AUTH or NEO4J_USER/NEO4J_PASSWORD."""
    from neo4j import GraphDatabase          # lazy: unit tests use a fake driver
    uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    # The server reads NEO4J_AUTH="user/password"; reuse it so one env file serves both.
    auth_user, _, auth_pw = os.environ.get("NEO4J_AUTH", "").partition("/")
    user = user or os.environ.get("NEO4J_USER") or auth_user or "neo4j"
    password = password or os.environ.get("NEO4J_PASSWORD") or auth_pw
    if not password:
        raise SystemExit("NEO4J_AUTH / NEO4J_PASSWORD is not set (start.ps1 writes NEO4J_AUTH to .env.neo4j).")
    return GraphDatabase.driver(uri, auth=(user, password))


class Graph:
    def __init__(self, driver, cfg: Optional[retention.Retention] = None):
        self.driver = driver
        self.cfg = cfg or retention.load()

    def close(self) -> None:
        self.driver.close()

    def _run(self, query: str, **params) -> list[dict]:
        with self.driver.session() as session:
            return [dict(r) for r in session.run(query, **params)]

    def wait_ready(self, seconds: int = 120) -> bool:
        end = time.time() + seconds
        while True:
            try:
                self._run("RETURN 1 AS ok")
                return True
            except Exception:                # noqa: BLE001 -- the driver raises many types while booting
                if time.time() >= end:
                    return False
                time.sleep(3)

    def ensure_schema(self) -> None:
        for q in SCHEMA_QUERIES:
            self._run(q)

    # ---- loading -------------------------------------------------------

    def _expiry(self, doc: dict, *bases: str) -> str:
        if doc.get("expires_at"):
            return doc["expires_at"]
        return retention.expires_at(next((doc[b] for b in bases if doc.get(b)), None), self.cfg)

    def load_filings(self, filings: Iterable[dict]) -> int:
        rows = [{"seq_id": str(f["seq_id"]), "symbol": f.get("symbol") or "",
                 "isin": f.get("isin"), "kind": f.get("kind"), "desc": f.get("desc"),
                 "an_date": f.get("an_date"), "url": f.get("url"),
                 "text": f.get("raw_text") or "",
                 "expires_at": self._expiry(f, "an_date", "stored_at")} for f in filings]
        rows = [r for r in rows if r["symbol"]]
        for chunk in _batches(rows, 50):     # filings carry full text; keep batches small
            self._run(LOAD_FILINGS, rows=chunk)
        return len(rows)

    def load_extractions(self, extractions: Iterable[dict]) -> int:
        rows = []
        for e in extractions:
            data = e.get("data") or {}
            if e.get("error") or not data:
                continue
            rows.append({
                "key": f"{e['seq_id']}|{e.get('kind')}", "seq_id": str(e["seq_id"]),
                "kind": e.get("kind"), "symbol": e.get("symbol"), "model": e.get("model"),
                "order_value_inr": data.get("order_value_inr"),
                "execution_months": _clean(data.get("execution_months")),
                "data": _clean(data),
                "counterparty": _norm_name(data.get("counterparty")),
                "counterparty_type": data.get("counterparty_type"),
                "expires_at": self._expiry(e, "stored_at"),
            })
        for chunk in _batches(rows):
            self._run(LOAD_EXTRACTIONS, rows=chunk)
        return len(rows)

    def load_conclusions(self, conclusions: Iterable[dict]) -> int:
        rows = [{"key": f"{c['symbol']}|{c.get('as_of')}", "symbol": c["symbol"],
                 "as_of": c.get("as_of"), "stance": c.get("stance"), "score": c.get("score"),
                 "conclusion": c.get("conclusion"), "model": c.get("model"),
                 "expires_at": self._expiry(c, "as_of")}
                for c in conclusions if not c.get("error") and c.get("conclusion")]
        for chunk in _batches(rows):
            self._run(LOAD_CONCLUSIONS, rows=chunk)
        return len(rows)

    def load_fundamentals(self, fundamentals: Iterable[dict]) -> int:
        rows = [{"symbol": f["symbol"], "data": _clean({k: v for k, v in f.items()}),
                 "expires_at": self._expiry(f, "stored_at")}
                for f in fundamentals if f.get("symbol")]
        for chunk in _batches(rows):
            self._run(LOAD_FUNDAMENTALS, rows=chunk)
        return len(rows)

    # ---- reading -------------------------------------------------------

    def facts(self) -> dict[str, dict]:
        """Per-symbol facts a single document cannot show."""
        return {r["symbol"]: {"distinct_customers": r["distinct_customers"],
                              "repeat_customers": r["repeat_customers"],
                              "peers_sharing_customer": r["peers_sharing_customer"]}
                for r in self._run(FACTS)}

    def status(self) -> dict[str, int]:
        return {r["label"]: r["n"] for r in self._run(STATUS)}

    # ---- retention -----------------------------------------------------

    def purge(self, today: Optional[date] = None) -> dict[str, int]:
        """Delete expired, processed nodes; a no-op when purging is switched off."""
        counts = {label: 0 for label, _ in PURGE_QUERIES}
        if not self.cfg.purge:
            return counts
        params = {"today": (today or date.today()).isoformat(),
                  "any": not self.cfg.only_when_processed}
        for label, query in PURGE_QUERIES:
            rows = self._run(query, **params)
            counts[label] = int(rows[0]["n"]) if rows else 0
        return counts
