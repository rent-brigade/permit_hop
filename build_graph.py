"""Build the ownership hop-graph.

A small bipartite graph over {entity, address, contact} nodes (entity =
distinct owner_name_norm string). Degree-based hub filtering on address and
contact nodes -- computed as the number of *distinct entity names* touching
that key, not the number of parcels -- is the primary defense against false
hops through a shared property manager, registered agent, or institutional
department name (see ASSESSOR_FIELD_NOTES.md and the plan for why the
person/company keyword heuristic alone isn't a safe filter). Connected
components over entity+key nodes, projected back to entity names, give
candidate one-beneficial-owner clusters; parcels are attached by looking up
every AIN whose owner_name_norm falls in the cluster.
"""

from pathlib import Path

import networkx as nx
import pandas as pd

from . import config

DATA_DIR = Path(__file__).parent / "data"


def _surviving_key_groups(
    df: pd.DataFrame, key_col: str
) -> tuple[dict[str, set[str]], dict[str, dict]]:
    """Group by key_col (non-null), split into surviving (non-hub) vs hub.

    A key touching only one distinct entity name isn't a linking key at all
    (nothing to link), so those are dropped rather than counted as either.
    """
    sub = df[[key_col, "owner_name_norm"]].dropna(subset=[key_col])
    grouped = sub.groupby(key_col)["owner_name_norm"].apply(set)

    surviving: dict[str, set[str]] = {}
    hub: dict[str, dict] = {}
    for key_value, names in grouped.items():
        if len(names) < 2:
            continue
        if len(names) > config.HUB_DEGREE_THRESHOLD:
            hub[key_value] = {"degree": len(names), "owner_names": sorted(names)}
        else:
            surviving[key_value] = names
    return surviving, hub


def build_graph(df: pd.DataFrame):
    address_survive, address_hub = _surviving_key_groups(df, "mail_addr_key")
    contact_survive, contact_hub = _surviving_key_groups(df, "co_name_clean")

    # Per-key person/company tag for confidence tiering (majority vote across
    # rows sharing that co_name_clean -- should be unanimous in practice since
    # it's a pure function of the string itself).
    co_is_person_by_key: dict[str, bool] = {}
    if contact_survive:
        person_lookup = df.dropna(subset=["co_name_clean"]).drop_duplicates(
            "co_name_clean"
        )
        co_is_person_by_key = dict(
            zip(person_lookup["co_name_clean"], person_lookup["co_is_person"])
        )

    G = nx.Graph()
    all_entities = set(df["owner_name_norm"].dropna().unique())
    G.add_nodes_from(all_entities, kind="entity")

    for key_value, names in address_survive.items():
        node = ("address", key_value)
        G.add_node(node, kind="address", key_value=key_value)
        for name in names:
            G.add_edge(node, name, key_type="address")

    for key_value, names in contact_survive.items():
        node = ("contact", key_value)
        is_person = bool(co_is_person_by_key.get(key_value, False))
        G.add_node(node, kind="contact", key_value=key_value, is_person=is_person)
        for name in names:
            G.add_edge(node, name, key_type="contact", is_person=is_person)

    return G, address_hub, contact_hub


def _cluster_tier(G: nx.Graph, component: set) -> str:
    """Tier 1: both an address edge and a person-contact edge present in the
    cluster. Tier 2: exactly one non-hub key type present. 'single': no
    linking key at all (isolated entity, just that owner's own parcels).
    'oversized_needs_review': safety net independent of the government-entity
    filter -- catches any residual transitive-chaining blowup regardless of
    cause (see config.MAX_PLAUSIBLE_CLUSTER_SIZE). A cluster containing a
    manually-verified key (config.VERIFIED_LARGE_CLUSTER_EXCEPTIONS) skips
    the size check entirely -- see that config for why size/topology alone
    can't safely distinguish a real large portfolio from a shared-vendor
    chaining artifact."""
    entity_names = [n for n in component if isinstance(n, str)]
    key_nodes = [n for n in component if isinstance(n, tuple)]

    is_verified = any(n in config.VERIFIED_LARGE_CLUSTER_EXCEPTIONS for n in key_nodes)
    if not is_verified and len(entity_names) > config.MAX_PLAUSIBLE_CLUSTER_SIZE:
        return "oversized_needs_review"

    has_address = any(n[0] == "address" for n in key_nodes)
    has_person_contact = any(
        n[0] == "contact" and G.nodes[n].get("is_person") for n in key_nodes
    )
    has_company_contact = any(
        n[0] == "contact" and not G.nodes[n].get("is_person") for n in key_nodes
    )
    if not key_nodes:
        return "single"
    if has_address and has_person_contact:
        return "tier1"
    if has_address or has_person_contact or has_company_contact:
        return "tier2"
    return "single"


def extract_clusters(G: nx.Graph, df: pd.DataFrame) -> pd.DataFrame:
    name_to_ains = df.groupby("owner_name_norm")["ain"].apply(list).to_dict()
    units_by_ain = df.set_index("ain")["landlord_units_clean"]
    self_transfer_by_ain = df.set_index("ain")["possible_self_transfer"]

    rows = []
    for cluster_id, component in enumerate(nx.connected_components(G)):
        entity_names = sorted(n for n in component if isinstance(n, str))
        if not entity_names:
            continue

        ains: list[str] = []
        for name in entity_names:
            ains.extend(name_to_ains.get(name, []))

        total_units = units_by_ain.reindex(ains).sum(skipna=True)
        self_transfer_count = int(self_transfer_by_ain.reindex(ains).fillna(False).sum())

        n_keys = sum(1 for n in component if isinstance(n, tuple))
        # Review-priority signal for the oversized_needs_review bucket (see
        # config.VERIFIED_LARGE_CLUSTER_EXCEPTIONS for why this can rank but
        # not auto-decide): a low ratio (few reused keys relative to cluster
        # size) is more consistent with a real single-operator portfolio; a
        # high ratio (many single-use bridging keys) is more consistent with
        # institutional/vendor chaining. Doesn't apply to singleton clusters.
        keys_per_owner_name = (n_keys / len(entity_names)) if len(entity_names) > 1 else None

        rows.append(
            {
                "cluster_id": cluster_id,
                "tier": _cluster_tier(G, component),
                "n_distinct_owner_names": len(entity_names),
                "owner_names": entity_names,
                "n_parcels": len(ains),
                "ains": ains,
                "total_landlord_units": total_units,
                "possible_self_transfer_count": self_transfer_count,
                "keys_per_owner_name": keys_per_owner_name,
            }
        )

    return pd.DataFrame(rows)


def build_weak_links(address_hub: dict, contact_hub: dict) -> pd.DataFrame:
    rows = []
    for key_value, info in address_hub.items():
        rows.append(
            {
                "key_type": "address",
                "key_value": key_value,
                "degree": info["degree"],
                "owner_names": info["owner_names"],
            }
        )
    for key_value, info in contact_hub.items():
        rows.append(
            {
                "key_type": "contact",
                "key_value": key_value,
                "degree": info["degree"],
                "owner_names": info["owner_names"],
            }
        )
    return pd.DataFrame(rows)


def build_edges(G: nx.Graph) -> pd.DataFrame:
    """Per-parcel-owning-entity evidence: which non-hub key ties it into its
    cluster. One row per (entity, key) edge -- the actual citation unit for a
    future query agent."""
    rows = []
    for u, v, data in G.edges(data=True):
        entity, key_node = (u, v) if isinstance(u, str) else (v, u)
        rows.append(
            {
                "owner_name": entity,
                "key_type": data["key_type"],
                "key_value": key_node[1],
                "is_person": data.get("is_person"),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    from . import annotate, normalize

    raw = pd.read_parquet(DATA_DIR / "parcels_raw.parquet")
    df = normalize.normalize(raw)
    df = annotate.add_self_transfer_flag(df)

    n_before = len(df)
    n_gov = int(df["is_government"].sum())
    n_fin = int(df["is_financial_services"].sum())
    df = df[~(df["is_government"] | df["is_financial_services"])].copy()
    print(
        f"Excluded {n_gov} government/public-entity rows and {n_fin} "
        f"financial-services/loan-servicer rows out of {n_before}"
    )

    G, address_hub, contact_hub = build_graph(df)
    clusters = extract_clusters(G, df)
    weak_links = build_weak_links(address_hub, contact_hub)
    edges = build_edges(G)

    clusters.to_parquet(DATA_DIR / "clusters.parquet", index=False)
    edges.to_parquet(DATA_DIR / "edges.parquet", index=False)
    weak_links.to_parquet(DATA_DIR / "weak_links.parquet", index=False)

    multi = clusters[clusters["n_distinct_owner_names"] > 1]
    print(f"{len(clusters)} total clusters, {len(multi)} multi-name (linked) clusters")
    print(f"{len(weak_links)} hub-flagged keys recorded as weak links")


if __name__ == "__main__":
    main()
