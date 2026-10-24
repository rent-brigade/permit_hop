"""Flask API + GUI for the owner networks.

The clusters are the cached output of `python -m hopgraph.build_graph` (parquet in
data/), read once into memory. Names, parcels and search come live from the parcel
database through parcel_query, using its indexes (owner-name trigram, address keys,
owner_key). A cluster is a lead for a researcher, not a finding.

Run with:
    uv run python -m hopgraph.build_graph   # once per data run
    uv run flask --app hopgraph.webapp.app run --debug
"""

from functools import lru_cache

import pandas as pd
from flask import Flask, jsonify, render_template, request
from parcel_query import find_owners, search_address

from .. import source
from ..paths import DATA_DIR

app = Flask(__name__)

SEARCH_LIMIT_PER_KIND = 8


@lru_cache(maxsize=1)
def _data():
    clusters = pd.read_parquet(DATA_DIR / "clusters.parquet")
    edges = pd.read_parquet(DATA_DIR / "edges.parquet")
    cluster_of = {k: c for c, keys in zip(clusters["cluster_id"], clusters["owner_keys"]) for k in keys}
    return clusters.set_index("cluster_id"), edges, cluster_of


_conn = None


def _db():
    """One read-only connection, reopened if the server dropped it."""
    global _conn
    if _conn is None or _conn.closed:
        _conn = source.connect()
    return _conn


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/search")
def search():
    q = request.args.get("q", "").strip()
    if len(q) < 3:
        return jsonify({"results": []})
    _, _, cluster_of = _data()
    conn = _db()

    results = []
    owners = find_owners(conn, q, limit=SEARCH_LIMIT_PER_KIND)
    for row in owners.itertuples():
        results.append(
            {
                "kind": "owner",
                "label": row.owner_full_name,
                "entity_type": row.owner_type,
                "cluster_id": cluster_of.get(row.owner_key),
                "n_parcels": int(row.active_parcel_count),
            }
        )

    if any(ch.isdigit() for ch in q):
        sites = search_address(
            conn, q, columns=["ain", "situs_address_full", "owner_key"], limit=SEARCH_LIMIT_PER_KIND
        )
        for row in sites.itertuples():
            results.append(
                {
                    "kind": "address",
                    "label": row.situs_address_full,
                    "ain": row.ain,
                    "cluster_id": cluster_of.get(row.owner_key),
                }
            )
    return jsonify({"results": results})


@app.get("/api/cluster/<cluster_id>")
def cluster_detail(cluster_id: str):
    clusters, edges, _ = _data()
    if cluster_id not in clusters.index:
        return jsonify({"error": "not found"}), 404
    c = clusters.loc[cluster_id]
    owner_keys = list(c["owner_keys"])
    conn = _db()

    members = source.fetch_owner_details(conn, owner_keys)
    parcels = source.fetch_parcels(conn, owner_keys)
    evidence = edges[edges["owner_key"].isin(owner_keys)]

    return jsonify(
        {
            "cluster_id": cluster_id,
            "tier": c["tier"],
            "n_owners": int(c["n_owners"]),
            "n_parcels": int(c["n_parcels"]),
            "total_units": float(c["total_units"]),
            "members": [
                {"owner_key": r.owner_key, "owner_name": r.owner_full_name, "owner_type": r.owner_type}
                for r in members.itertuples()
            ],
            "parcels": [
                {
                    "ain": r.ain,
                    "situs_address": r.situs_address,
                    "lat": None if pd.isna(r.latitude) else float(r.latitude),
                    "lon": None if pd.isna(r.longitude) else float(r.longitude),
                }
                for r in parcels.itertuples()
            ],
            "evidence": [
                {
                    "owner_key": r.owner_key,
                    "key_type": r.key_type,
                    "key_value": r.key_value,
                    "is_person": None if pd.isna(r.is_person) else bool(r.is_person),
                }
                for r in evidence.itertuples()
            ],
        }
    )


if __name__ == "__main__":
    app.run(debug=True)
