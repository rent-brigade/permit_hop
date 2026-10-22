"""Ensure the local embedded Postgres server is running.

Run this (from this directory, with this project's .venv) before anything
in the main permits/graph package tries to connect. cleanup_mode=None means
the server keeps running as an independent process after this script exits
-- it is not tied to this script's lifetime.
"""

from pathlib import Path

import pgserver

PGDATA = Path(__file__).parent / "data"


def main() -> None:
    server = pgserver.get_server(str(PGDATA), cleanup_mode=None)
    print(f"Postgres running, pgdata={server.pgdata}")
    print(f"Connect via: host={PGDATA} dbname=hopgraph user=postgres")


if __name__ == "__main__":
    main()
