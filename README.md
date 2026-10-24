# Owner networks for LA County parcels

Finds candidate owner networks in the parcel database: owners (by `owner_key`) linked through a shared mailing address or a shared care-of contact, grouped by connected components of a graph. A network is a lead for a researcher, not a finding of common ownership (parcel ADR 0010).

The parcel database does the cleaning: dedupe (`owner_key`), owner type (`owner_type`, including public bodies), and keyed mailing addresses. This repo only reads the `api` schema through `parcel_query` and runs the graph.

## Setup

Requires Python 3.13, [uv](https://docs.astral.sh/uv/), and **read access to the private repo `rent-brigade/lac-parcels`**, which provides the `parcel_query` and `parcel_cleaning` packages. `uv sync` installs them from git, using your git credentials:

- HTTPS: sign in with `gh auth login` (or a credential helper with a token that can read the repo).
- SSH: run `git config --global url."git@github.com:".insteadOf "https://github.com/"` and have a key on your GitHub account.

```
uv sync
cp .env.example .env    # then fill in DB_CONNECTION_STRING (a read-only researcher_ro string from the parcel maintainers)
```

To work against a local checkout of lac-parcels instead, temporarily point the two `[tool.uv.sources]` entries in `pyproject.toml` at its `packages/parcel_query` and `packages/parcel_cleaning` directories (`{ path = "...", editable = true }`), and do not commit that change.

The tests need neither the database nor the connection string.

## Building the networks

```
uv run python -m hopgraph.build_graph
```

Reads every private owner with an active parcel (keyset pages over `api.owner_summary`), builds the graph, and writes `data/clusters.parquet`, `data/edges.parquet`, `data/weak_links.parquet` and `data/meta.json` (the database run and cleaning version the output came from). Rebuild after each new data run: `owner_key` can change when the cleaning version changes.

Not yet timed at full scale (2.4M parcels). `researcher_ro` has a 30 s statement timeout; `source.py` raises it to 120 s per page and pages by 20,000 owners. If a page is too slow, lower `PAGE_SIZE` in `hopgraph/source.py`.

## Running the app

```
uv run flask --app hopgraph.webapp.app run --debug
```

Serves http://127.0.0.1:5000. Cluster membership comes from the parquet files; owner names, parcels and search come live from the database (owner-name trigram index, address keys, `owner_key`).

## Tests

```
uv run pytest
```

Synthetic data only; no database needed.

## Method

- **Nodes:** one per `owner_key` (name plus mailing address and unit, as the database keyed it). The same entity name at two mailing addresses is two nodes.
- **Keys:** the mailing building (`mail_building_address_key`) and the care-of contact (`special_name_assessee` where the legend is `C/O`; see `CONTACT_LEGEND` in `config.py`). Edges join an owner to each key it holds.
- **Hubs:** a key held by more than 5 distinct owners (`HUB_DEGREE_THRESHOLD`) is left out of the graph and saved to `weak_links.parquet`. This stops hops through property managers, registered agents and law-firm addresses.
- **Excluded:** owners with `owner_type = 'public'` (in SQL), and mortgage servicers and securitization trustees (name pattern, `FINANCIAL_SERVICES_PATTERN`; the database does not classify these).
- **Tiers:** `tier1` has an address key and a person-contact key; `tier2` any other linking key; `single` none; `oversized_needs_review` more than 20 owners unless the cluster holds a key in `VERIFIED_LARGE_CLUSTER_EXCEPTIONS`. These can be real portfolios or shared-vendor chaining, so check them by hand.
- **Cluster ids** are a hash of the sorted member `owner_key`s, so the same network keeps its id across runs.

## Not carried over from the raw-data version

- Possible self-transfer flag (needed sale fields; not part of the graph).
- Landlord-unit totals now come from the database's `total_units`.
- The local Postgres, `ingest`, `load` and `dump` steps.
