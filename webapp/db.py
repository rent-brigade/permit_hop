"""Connection pool to the local serving Postgres (graph/pgserver_env/).

The API only ever reads from these tables -- graph construction itself is
the batch job in graph/build_graph.py, not something this app recomputes.
Requires the local Postgres to already be running:
    (cd graph/pgserver_env && uv run python start_pg.py)
"""

import re
from pathlib import Path

from psycopg2.pool import SimpleConnectionPool

PGDATA = Path(__file__).parent.parent / "pgserver_env" / "data"

_pool: SimpleConnectionPool | None = None


def get_pool() -> SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(1, 8, host=str(PGDATA), dbname="hopgraph", user="postgres")
    return _pool


def build_prefix_tsquery(term: str) -> str | None:
    """'111 w palm' -> '111 & w & palm:*' -- exact match on every word except
    the last (still being typed), which gets prefix matching. Passed as a
    query parameter (not interpolated into SQL text), so this only needs to
    produce well-formed tsquery syntax, not worry about SQL injection."""
    words = re.findall(r"[A-Za-z0-9]+", term)
    if not words:
        return None
    *head, last = words
    return " & ".join([*head, f"{last}:*"])
