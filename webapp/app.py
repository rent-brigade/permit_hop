"""Flask API + GUI for the ownership hop-graph.

Every route here is a read against precomputed tables -- see the plan
(.claude/plans/this-dichotomy-is-especially-zippy-ember.md) for why graph
construction stays a batch job (graph/build_graph.py) and never happens
per-request. "Building the graph for a selected property" is, in practice,
an indexed lookup of which precomputed cluster it already belongs to.

Run with:
    (cd graph/pgserver_env && uv run python start_pg.py)   # once per session
    uv run flask --app graph.webapp.app run --debug
"""

from flask import Flask, jsonify, render_template, request

from .db import build_prefix_tsquery, get_pool

app = Flask(__name__)

SEARCH_LIMIT_PER_KIND = 8


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/search")
def search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify({"results": []})

    tsquery = build_prefix_tsquery(q)
    if tsquery is None:
        return jsonify({"results": []})

    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT ain, situs_address, cluster_id
            FROM parcels
            WHERE addr_tsv @@ to_tsquery('simple', %s)
            LIMIT %s
            """,
            (tsquery, SEARCH_LIMIT_PER_KIND),
        )
        address_hits = [
            {"kind": "address", "label": addr, "ain": ain, "cluster_id": cid}
            for ain, addr, cid in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT owner_name_norm, entity_type, cluster_id, n_parcels
            FROM entities
            WHERE name_tsv @@ to_tsquery('simple', %s)
            ORDER BY n_parcels DESC
            LIMIT %s
            """,
            (tsquery, SEARCH_LIMIT_PER_KIND),
        )
        owner_hits = [
            {
                "kind": "owner",
                "label": name,
                "entity_type": etype,
                "cluster_id": cid,
                "n_parcels": n,
            }
            for name, etype, cid, n in cur.fetchall()
        ]

        return jsonify({"results": address_hits + owner_hits})
    finally:
        pool.putconn(conn)


@app.get("/api/cluster/<int:cluster_id>")
def cluster_detail(cluster_id: int):
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT cluster_id, tier, n_distinct_owner_names, n_parcels,
                   total_landlord_units, possible_self_transfer_count
            FROM clusters WHERE cluster_id = %s
            """,
            (cluster_id,),
        )
        row = cur.fetchone()
        if row is None:
            return jsonify({"error": "not found"}), 404
        cid, tier, n_names, n_parcels, total_units, self_transfer_count = row

        cur.execute(
            "SELECT owner_name_norm, entity_type FROM entities WHERE cluster_id = %s ORDER BY owner_name_norm",
            (cluster_id,),
        )
        members = [{"owner_name_norm": n, "entity_type": t} for n, t in cur.fetchall()]

        cur.execute(
            """
            SELECT ain, situs_address, possible_self_transfer, latitude, longitude
            FROM parcels WHERE cluster_id = %s ORDER BY situs_address
            """,
            (cluster_id,),
        )
        parcels = [
            {
                "ain": ain,
                "situs_address": addr,
                "possible_self_transfer": pst,
                "lat": lat,
                "lon": lon,
            }
            for ain, addr, pst, lat, lon in cur.fetchall()
        ]

        member_names = [m["owner_name_norm"] for m in members]
        evidence = []
        if member_names:
            cur.execute(
                """
                SELECT owner_name_norm, key_type, key_value, is_person
                FROM edges WHERE owner_name_norm = ANY(%s)
                """,
                (member_names,),
            )
            evidence = [
                {"owner_name_norm": n, "key_type": kt, "key_value": kv, "is_person": p}
                for n, kt, kv, p in cur.fetchall()
            ]

        return jsonify(
            {
                "cluster_id": cid,
                "tier": tier,
                "n_distinct_owner_names": n_names,
                "n_parcels": n_parcels,
                "total_landlord_units": total_units,
                "possible_self_transfer_count": self_transfer_count,
                "members": members,
                "parcels": parcels,
                "evidence": evidence,
            }
        )
    finally:
        pool.putconn(conn)


if __name__ == "__main__":
    app.run(debug=True)
