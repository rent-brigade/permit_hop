"""Tunable knobs for the owner-network graph.

Cleaning is not configured here: the parcel database already provides owner_key,
owner_type and the mailing-address keys.
"""

# A non-parcel node (address, contact, or entity-name) touching more than this
# many *distinct owners (owner_key)* is treated as a hub: recorded as a weak
# link but excluded from connected-components clustering. This is the primary
# defense against false hops through a shared property manager, registered
# agent, or institutional department name.
HUB_DEGREE_THRESHOLD = 5

# Only a special-name field with this legend is a care-of contact; other legends (for
# example DBA) are not linking evidence. Check the values present with
# SELECT special_name_legend, count(*) FROM api.owner_summary GROUP BY 1.
CONTACT_LEGEND = "C/O"

# Keywords marking a `special name assessee` (C/O) string as company/
# institutional rather than a person. This only affects confidence tiering,
# not inclusion/exclusion -- HUB_DEGREE_THRESHOLD is the real safety net,
# since role/department words like "REAL ESTATE DIVISION" or "BUREAU OF
# ENGINEERING" don't match typical company keywords and would otherwise slip
# through as "person-like".
COMPANY_KEYWORDS = (
    r"MANAGEMENT|MGMT|PROPERTIES|PROPERTY|REALTY|INVESTMENT|GROUP|HOLDINGS|"
    r"CAPITAL|PARTNERS|LLC|INC|CORP|CO\b|ASSET|ADVISORS|ADVISOR|ENTERPRISES|"
    r"DEPARTMENT|DIVISION|DEPT|BUREAU|OFFICE|ATTORNEY|MANAGER|ADMINISTRATOR|"
    r"ACQUISITION"
)

# Post-hoc safety net, independent of the owner_type = 'public' filter: any
# cluster with more distinct owner names than this is flagged for manual
# review rather than presented as a confirmed portfolio. Chosen well above
# the largest legitimate cluster seen during validation (6 distinct names)
# and well below the size of the chaining-artifact cluster this caught (469).
#
# This threshold cannot safely be raised as a single number: a topology check
# (keys-per-owner-name ratio) run against all 10 oversized clusters found
# during review showed that a real portfolio (29 distinct LLC names, tied
# together by a repeated named individual as C/O contact) is statistically
# indistinguishable from a shared property manager/investment advisor
# chaining together many unrelated clients' LLCs (21 and 27 distinct names,
# same shape) -- a repeated person's name as C/O looks identical whether
# that person owns the LLCs themselves or just manages them for others. This
# is a real limit of what the assessor data can tell us, not a bug to patch.
#
# So verified-legitimate large clusters are hardcoded here by their specific
# linking key instead of by raising the size cap globally. Add an entry only
# after manually confirming (e.g. via public records, news, CPRA request)
# that the named individual/address genuinely is the beneficial owner across
# the whole cluster, not a paid intermediary. Use CLUSTER_SIZE_RANKING_COLUMN
# (keys_per_owner_name, in clusters.parquet) to prioritize which
# oversized_needs_review clusters to investigate next -- low ratio (tight,
# few reused keys) is more likely a real single-operator portfolio; high
# ratio (loose, many single-use bridges) is more likely institutional/vendor
# chaining and safe to deprioritize.
MAX_PLAUSIBLE_CLUSTER_SIZE = 20

# Found via a real leak: mortgage servicers/securitization trustees/REO
# investors (e.g. "CARRINGTON MORTGAGE SERVICES LLC", "US BANK TRUST
# NATIONAL ASSN TR") chained together unrelated homeowners into a CONFIRMED
# tier1 cluster, undetected, because the cluster was small enough (20 names)
# to fall under MAX_PLAUSIBLE_CLUSTER_SIZE. Unlike GOVERNMENT_NAME_PATTERN,
# this is NOT restricted to entity_type == "individual" -- these entities
# almost always carry an LLC/Inc/Assn suffix already (that's what let them
# through the government filter's guard), so the entity-type restriction
# that protects real private LLCs from the government filter would defeat
# the purpose here. The curated names below are necessarily incomplete --
# see the note on VERIFIED_LARGE_CLUSTER_EXCEPTIONS and ASSESSOR_FIELD_NOTES.md
# for why the citation-grounded query agent, not this list, is the real
# backstop against residual leaks like this.
FINANCIAL_SERVICES_PATTERN = (
    r"\bOCWEN\b|\bCARRINGTON MORTGAGE|\bFAY SERVICING\b|\bNATIONSTAR\b|"
    r"\bMR COOPER\b|\bSPECIALIZED LOAN SERVICING\b|"
    r"\bSELECT PORTFOLIO SERVICING\b|\bSHELLPOINT\b|\bPENNYMAC\b|"
    r"\bRUSHMORE LOAN\b|\bFREEDOM MORTGAGE\b|\bMORGAN STANLEY MORTGAGE|"
    r"\bGOLDMAN SACHS MORTGAGE|\bWELLS FARGO BANK\b|\bBANK OF AMERICA\b|"
    r"\bJPMORGAN CHASE\b|\bDEUTSCHE BANK\b|\bU\.?\s*S\.?\s*BANK\b|"
    r"\bWILMINGTON TRUST\b|\bWILMINGTON SAVINGS\b|\bHSBC BANK\b|"
    r"\bCITIMORTGAGE\b|\bCHRISTIANA TRUST\b|\bMORTGAGE SERVIC|"
    r"\bLOAN SERVIC|\bMORTGAGE CAPITAL\b|\bMORTGAGE TRUST\b|"
    r"\bNATIONAL ASSN TR\b|\bTRUST NATIONAL ASSN\b|\bBANK TRUST CO\b|"
    r"\bSECURITIZ|\bASSET BACKED\b|\bREO\b"
)

VERIFIED_LARGE_CLUSTER_EXCEPTIONS = {
    # Reviewed 2026-09-06: 29 distinct LLC names / 71 parcels / 134 units,
    # all address-derived shell names (e.g. "5005 RUBIO LLC", "7125 LA
    # CIENEGA LLC") tied together by this repeated C/O contact. Judged
    # likely-legitimate from the naming pattern during this session's manual
    # review -- NOT independently confirmed against an outside source (news,
    # CPRA request, DRE license lookup). Treat as a working assumption, not
    # a verified fact, until actually checked against something external.
    ("contact", "DORON BENSHALOM"),
}
