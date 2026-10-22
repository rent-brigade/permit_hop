"""Ensure the local embedded Postgres server is running.

Run this before anything in the hopgraph package tries to connect:
    uv run python -m hopgraph.start_pg
On first run, pgserver initdb's a fresh cluster at paths.PGDATA (then run
init_db.py to create the hopgraph database). cleanup_mode=None means the
server keeps running as an independent process after this script exits --
it is not tied to this script's lifetime.
"""

import pgserver

from .paths import DB_NAME, PGDATA


def start():
    return pgserver.get_server(str(PGDATA), cleanup_mode=None)


def main() -> None:
    server = start()
    print(f"Postgres running, pgdata={server.pgdata}")
    print(f"Connect via: host={PGDATA} dbname={DB_NAME} user=postgres")


if __name__ == "__main__":
    main()
