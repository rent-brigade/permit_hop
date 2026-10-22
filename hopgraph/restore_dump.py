"""Restore the hopgraph database from the CSV dump in data/dump/.

Run this after init_db.py (which starts the local Postgres, creates the
hopgraph database, and applies schema.sql) -- see README.md:
    uv run python -m hopgraph.restore_dump
"""

import psycopg2

from .dump_tables import TABLE_COLUMNS
from .paths import DB_NAME, DUMP_DIR, PGDATA


def main() -> None:
    conn = psycopg2.connect(host=str(PGDATA), dbname=DB_NAME, user="postgres")
    cur = conn.cursor()
    for table, cols in TABLE_COLUMNS.items():
        col_clause = f"({', '.join(cols)})" if cols else ""
        path = DUMP_DIR / f"{table}.csv"
        with open(path) as f:
            cur.copy_expert(f"COPY {table}{col_clause} FROM STDIN WITH CSV", f)
        print(f"loaded {table}")
    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
