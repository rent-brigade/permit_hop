# permit_hop

Ownership hop-graph over the LA County Assessor parcel roll: links differently
named owners (often single-property LLCs) that share a mailing address and/or
a named C/O contact, and serves the resulting clusters through a small Flask
search app backed by an embedded Postgres.

## Setup

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is pinned because the
embedded Postgres (`pgserver`) has no 3.13 wheels; uv installs it if needed.

```bash
uv sync
```

## Layout

```
hopgraph/            pipeline + database scripts (run as python -m hopgraph.<name>)
  paths.py           all filesystem locations (data/, pgdata/, schema.sql)
  config.py          clustering thresholds and name-filter regexes
  ingest.py          pull parcels_raw from the source Neon DB -> data/parcels_raw.parquet
  normalize.py       cleaning + linkage keys (mailing address, C/O contact)
  annotate.py        possible_self_transfer flag
  build_graph.py     hop graph -> data/{clusters,edges,weak_links}.parquet
  start_pg.py        start the embedded Postgres (cluster lives in pgdata/)
  init_db.py         create the hopgraph database + apply schema.sql
  load.py            load the parquet outputs into Postgres
  backfill_latlon.py add parcel lat/lon from the source DB
  dump_tables.py     export the serving tables to data/dump/*.csv
  restore_dump.py    load data/dump/*.csv back in
  webapp/            Flask API + search page
data/                pipeline data and the CSV dump (gitignored)
pgdata/              embedded Postgres cluster (gitignored)
```

Scripts that read the source database (`ingest`, `backfill_latlon`) need
`hopgraph/db_secrets.py`: copy `hopgraph/db_secrets.example.py` and fill in the
connection string. It is gitignored.

## Run the web app

```bash
uv run python -m hopgraph.start_pg                    # once per login/reboot
uv run flask --app hopgraph.webapp.app run --debug    # http://127.0.0.1:5000
```

## Build the database on a fresh machine

```bash
uv run python -m hopgraph.init_db          # starts Postgres, creates db, applies schema
```

Then either restore from a dump (put the CSVs in `data/dump/`):

```bash
uv run python -m hopgraph.restore_dump
```

or rebuild from the source data:

```bash
uv run python -m hopgraph.ingest           # needs db_secrets.py
uv run python -m hopgraph.build_graph
uv run python -m hopgraph.load
uv run python -m hopgraph.backfill_latlon  # needs db_secrets.py
```

Set `HOPGRAPH_PGDATA=/some/path` to keep the Postgres cluster somewhere other
than `pgdata/` (useful if the checkout path is long: macOS limits unix-socket
paths to ~104 characters, and the socket lives in this directory).
