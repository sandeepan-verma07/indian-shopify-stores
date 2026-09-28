"""Step 5: Decide which confirmed Shopify stores are Indian, with a score and a written reason for each.

Uses only data/shopify_verified.csv (no new downloads), so it runs in seconds.
"Indian" = the store's own registered country (meta.json) is India.
Only HIGH-confidence stores go to indian_stores.csv: country=IN AND currency=INR AND an Indian state.
Everything less certain (exports in USD, missing state, registered abroad but INR) goes to edge_cases.csv.
"""
from pathlib import Path

import pandas as pd

VERIFIED_FILE = Path("data/shopify_verified.csv")
GOLDEN_FILE = Path("data/golden_set.csv")
OUT_FILE = Path("data/indian_stores.csv")
EDGE_FILE = Path("data/edge_cases.csv")

INDIAN_STATES = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa", "gujarat",
    "haryana", "himachal pradesh", "jharkhand", "karnataka", "kerala", "madhya pradesh",
    "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland", "odisha", "punjab", "rajasthan",
    "sikkim", "tamil nadu", "telangana", "tripura", "uttar pradesh", "uttarakhand", "west bengal",
    "andaman and nicobar islands", "chandigarh", "dadra and nagar haveli and daman and diu",
    "delhi", "jammu and kashmir", "ladakh", "lakshadweep", "puducherry",
}

# older or informal names that still appear in store settings
STATE_ALIASES = {
    "daman and diu": "dadra and nagar haveli and daman and diu",
    "dadra and nagar haveli": "dadra and nagar haveli and daman and diu",
    "orissa": "odisha", "pondicherry": "puducherry", "new delhi": "delhi",
    "nct of delhi": "delhi", "uttaranchal": "uttarakhand",
}

# how much each clue is worth
WEIGHTS = {"country_in": 3, "currency_inr": 2, "indian_state": 1, "in_domain": 1}


def india_clues(row) -> dict[str, bool]:
    province = str(row["meta_province"]).strip().lower()
    province = STATE_ALIASES.get(province, province)
    return {
        "country_in": row["meta_country"] == "IN",
        "currency_inr": row["meta_currency"] == "INR",
        "indian_state": province in INDIAN_STATES,
        "in_domain": row["domain"].endswith(".in"),
    }


def evidence_text(row, clues: dict[str, bool]) -> str:
    parts = []
    if clues["country_in"]:
        parts.append("meta.json country=IN")
    if clues["currency_inr"]:
        parts.append("currency=INR")
    if clues["indian_state"]:
        parts.append(f"state={row['meta_province']}")
    if clues["in_domain"]:
        parts.append(".in domain")
    if not clues["country_in"] and pd.notna(row["meta_country"]):
        parts.append(f"registered in {row['meta_country']}")
    return "; ".join(parts)


def verdict(clues: dict[str, bool]) -> str:
    if clues["country_in"]:
        return "indian"
    if clues["currency_inr"] or clues["indian_state"]:
        return "borderline"          # e.g. registered in Canada but sells in rupees
    return "not_indian"


def edge_reason(row) -> str:
    """Why a store is NOT in the high-confidence list (empty = high confidence)."""
    if row["india_verdict"] == "borderline":
        return f"registered in {row['meta_country']} but sells in INR"
    if row["india_verdict"] == "indian" and row["meta_currency"] != "INR":
        return f"registered in India but sells in {row['meta_currency']} (likely exports)"
    if row["india_verdict"] == "indian" and "state=" not in row["india_evidence"]:
        return "registered in India but no Indian state in meta.json"
    return ""


def primary_domain(row) -> str:
    """The store's own main domain from meta.json (e.g. gocolors.in -> gocolors.com)."""
    main = row["meta_domain"] if pd.notna(row["meta_domain"]) else row["domain"]
    return str(main).lower().removeprefix("www.")


def score_all() -> pd.DataFrame:
    df = pd.read_csv(VERIFIED_FILE)
    df = df[df["is_shopify"]].copy()

    clues = df.apply(india_clues, axis=1)
    df["india_score"] = [sum(WEIGHTS[k] for k, v in c.items() if v) for c in clues]
    df["india_verdict"] = [verdict(c) for c in clues]
    df["india_evidence"] = [evidence_text(row, c) for (_, row), c in zip(df.iterrows(), clues)]
    df["primary_domain"] = df.apply(primary_domain, axis=1)
    df["edge_reason"] = df.apply(edge_reason, axis=1)
    return df


def check_golden(df: pd.DataFrame):
    golden = pd.read_csv(GOLDEN_FILE)
    golden = golden[golden["is_shopify"] == "yes"]
    found = df.set_index("domain")
    correct = checked = 0
    for row in golden.itertuples():
        if row.domain not in found.index:
            print(f"  SKIP {row.domain:26} (not in the checked top 50k)")
            continue
        got = found.loc[row.domain, "india_verdict"] == "indian"
        ok = got == (row.is_indian == "yes")
        checked += 1
        correct += ok
        print(f"  {'OK  ' if ok else 'FAIL'} {row.domain:26} expected={row.is_indian:3} got={found.loc[row.domain, 'india_verdict']}")
    print(f"Golden set: {correct}/{checked} correct\n")


def main():
    df = score_all()
    print("India verdicts (all confirmed Shopify):")
    print(df["india_verdict"].value_counts().to_string(), "\n")
    check_golden(df)

    live = df[df["store_state"] == "live"]
    edge = live[live["edge_reason"] != ""]
    high = live[(live["india_verdict"] == "indian") & (live["edge_reason"] == "")]

    before = len(high)
    # same store under two domains (gocolors.in + gocolors.com): keep one row per myshopify_domain,
    # preferring the row whose domain IS the store's primary domain
    high = high.assign(is_primary=high["domain"] == high["primary_domain"])
    high = high.sort_values("is_primary", ascending=False).drop_duplicates("meta_myshopify_domain")
    high = high.drop(columns=["is_primary", "edge_reason"]).sort_values("primary_domain")

    high.to_csv(OUT_FILE, index=False)
    edge.to_csv(EDGE_FILE, index=False)

    print(f"High-confidence Indian + live: {before:,} rows -> {len(high):,} unique stores")
    print(f"Saved {OUT_FILE} ({len(high):,}) and {EDGE_FILE} ({len(edge):,})")
    print("\nEdge cases (kept aside, documented in README):")
    print(edge[["primary_domain", "meta_country", "meta_currency", "edge_reason"]].to_string(index=False))


if __name__ == "__main__":
    main()
