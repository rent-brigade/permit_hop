# Los Angeles Ownership Hop Graph

Ingests and processes the table ``parcels_raw`` from the county assessor (credentials not provided, to be filled in in ``hopgraph/db_secrets.py``, see ``hopgraph/db_secrets.example.py``)
to cluster parcels by likely common owners. Contains a Flask app frontend to query these clusters.

## Setup

Install the environment with ``uv sync`` (uses Python 3.12 as the embedded Postgres package ``pgserver`` doesn't support 3.13). 

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

## Methodology

The clusters are primarily based on ``mail_addr_key`` (joined during cleaning from ``mail house no``, ``m street name``, ``m unit``, and ``m zip``) and ``co_name_clean`` (cleaned from ``special name assessee``). 

The nodes are owner names: first owner name, uppercased with spaces collapsed, stored as owner_name_norm. You group by each key and collect the set of distinct owner names that share it (build_graph.py:_surviving_key_groups).

``build_graph.py`` then builds a bipartite graph with owner-name nodes on one side, address and contact key nodes on the other, and builds clusters from connected components.

A key shared by more than 5 distinct owner names (threshold set as variable ``HUB_DEGREE_THRESHOLD``) is left out of clustering and saved to weak_links.parquet. This is to stop superfluous clustering by shared property managers, registered agents and law-firm addresses. 

The results are grouped into tiers:
  - tier1: the cluster has an address link and a person-contact link. This is what the frontend useses.
  - tier2: only one kind of link.
  - single: no links at all.
  - oversized_needs_review: more than 20 owner names, unless the cluster is in VERIFIED_LARGE_CLUSTER_EXCEPTIONS. These can, empirically, either be genuine or anomalous, and should be checked by hand in updates.


Some rows are dropped before building the graph, flagged by regex on the owner name:
  - ``is_government``: only applied when the name has no LLC/LP/trust/corp suffix, so private LLCs with a word like "CITY" aren't caught.
  - ``is_financial_services``: mortgage servicers and securitization trustees.

Made with Claude Code. Still needs some cleanup, though some spot checks of known clusters (/non-clusters) has seemed robust so far.
