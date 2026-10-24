"""The graph step on synthetic owners. No database and no real data."""

import pandas as pd

from hopgraph import config
from hopgraph.build_graph import cluster_id_for, run


def owners(rows):
    frame = pd.DataFrame(rows, columns=["owner_key", "mail_key", "contact"])
    frame["owner_full_name"] = "OWNER " + frame["owner_key"]
    frame["owner_type"] = "corporation"
    frame["parcel_count"] = 1
    frame["total_units"] = 2
    return frame


def clusters_by_members(out):
    return {tuple(c.owner_keys): c for c in out["clusters"].itertuples()}


def test_shared_address_links_owners():
    out = run(owners([("a", "1 MAIN", None), ("b", "1 MAIN", None), ("c", "9 OAK", None)]))
    found = clusters_by_members(out)
    assert found[("a", "b")].tier == "tier2"
    assert found[("a", "b")].n_parcels == 2
    assert found[("a", "b")].total_units == 4
    assert found[("c",)].tier == "single"


def test_address_plus_person_contact_is_tier1():
    out = run(owners([("a", "1 MAIN", "C/O JANE ROE"), ("b", "1 MAIN", "JANE  ROE")]))
    assert clusters_by_members(out)[("a", "b")].tier == "tier1"
    contact_edges = out["edges"].query("key_type == 'contact'")
    assert set(contact_edges["key_value"]) == {"JANE ROE"}
    assert contact_edges["is_person"].all()


def test_company_contact_is_not_a_person():
    out = run(owners([("a", None, "ACME MANAGEMENT"), ("b", None, "ACME MANAGEMENT")]))
    assert clusters_by_members(out)[("a", "b")].tier == "tier2"
    assert not out["edges"]["is_person"].any()


def test_hub_key_is_weak_link_not_edge():
    n = config.HUB_DEGREE_THRESHOLD + 1
    out = run(owners([(f"o{i}", "HUB ST", None) for i in range(n)]))
    assert len(out["clusters"]) == n
    assert set(out["clusters"]["tier"]) == {"single"}
    assert out["edges"].empty
    weak = out["weak_links"].iloc[0]
    assert (weak.key_type, weak.key_value, weak.degree) == ("address", "HUB ST", n)


def test_oversized_cluster_is_flagged():
    n = config.MAX_PLAUSIBLE_CLUSTER_SIZE + 1
    # A chain: owners 2j and 2j+1 share an address, owners 2j+1 and 2j+2 share a contact.
    rows = [
        (f"o{i}", f"ADDR{i // 2}", f"CONTACT{(i + 1) // 2}") for i in range(n)
    ]
    out = run(owners(rows))
    assert len(out["clusters"]) == 1
    assert out["clusters"].iloc[0].tier == "oversized_needs_review"
    assert out["clusters"].iloc[0].n_owners == n


def test_financial_services_owner_excluded():
    frame = owners([("a", "1 MAIN", None), ("b", "1 MAIN", None)])
    frame.loc[0, "owner_full_name"] = "CARRINGTON MORTGAGE SERVICES LLC"
    out = run(frame)
    assert clusters_by_members(out) == {("b",): clusters_by_members(out)[("b",)]}


def test_cluster_id_is_stable_and_order_free():
    assert cluster_id_for(["b", "a"]) == cluster_id_for(["a", "b"])
    assert cluster_id_for(["a"]) != cluster_id_for(["a", "b"])
