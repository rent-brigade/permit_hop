# Los Angeles Ownership Hop Graph

Ingests and processes the table ``parcels_raw`` from the county assessor (credentials not provided, to be filled in in ``hopgraph/db_secrets.py`` (see ``hopgraph/db_secrets.example.py``))
to cluster parcels by likely common owners. Contains a Flask app frontend to query these clusters.

## Setup

Install the environment with ``uv sync`` (Python 3.12 is pinned, since the embedded Postgres package ``pgserver`` doesn't support 3.13). All commands are run from the repo root, and all scripts live in ``hopgraph/``.

## Updating the data

Updating the data for the frontend querying has five steps:

1. ``uv run python -m hopgraph.ingest`` loads the data into ``data/parcels_raw.parquet``.
2. ``normalize.py`` and ``annotate.py`` clean the data (called automatically by the next step).
3. ``uv run python -m hopgraph.build_graph`` writes ``data/clusters.parquet``, ``data/edges.parquet`` and ``data/weak_links.parquet``.
4. ``uv run python -m hopgraph.load`` loads those outputs into the local Postgres database (in ``pgdata/``), which is what the Flask app queries.
5. ``uv run python -m hopgraph.backfill_latlon`` adds parcel coordinates for the map.

On a fresh machine, run ``uv run python -m hopgraph.init_db`` before step 4 to create the database. If you have a copy of the CSV dump in ``data/dump/``, you can skip steps 1–5 and run ``uv run python -m hopgraph.restore_dump`` instead (``dump_tables`` creates that dump).

## Running the app

Start the Postgres database with ``uv run python -m hopgraph.start_pg`` and then run ``uv run flask --app hopgraph.webapp.app run --debug``, which serves the app at http://127.0.0.1:5000.

Made with Claude Code. Still needs some cleanup, though some spot checks of known clusters (/non-clusters) has seemed robust so far.
