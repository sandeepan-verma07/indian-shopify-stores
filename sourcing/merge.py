"""Step 1c: Merge Tranco and CrUX candidates into one list, one row per domain."""
from pathlib import Path

import pandas as pd

TRANCO_FILE = Path("data/candidates_tranco.csv")
CRUX_FILE = Path("data/candidates_crux.csv")
GOLDEN_FILE = Path("data/golden_set.csv")
OUT_FILE = Path("data/candidates_raw.csv")

## renaming columns 
def load(path: Path, rank_column: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    return df[["domain", "source_rank"]].rename(columns={"source_rank": rank_column})

## merging

def merge_sources(tranco: pd.DataFrame, crux: pd.DataFrame) -> pd.DataFrame:
    df = tranco.merge(crux, on="domain", how="outer")

    in_tranco = df["tranco_rank"].notna()
    in_crux = df["crux_rank"].notna()

    df["sources"] = ""
    df.loc[in_tranco & ~in_crux, "sources"] = "tranco"
    df.loc[in_crux & ~in_tranco, "sources"] = "crux_in"
    df.loc[in_tranco & in_crux, "sources"] = "tranco|crux_in"

    df["tranco_rank"] = df["tranco_rank"].astype("Int64")
    df["crux_rank"] = df["crux_rank"].astype("Int64")
    return df[["domain", "sources", "tranco_rank", "crux_rank"]]


def check_golden(df: pd.DataFrame):
    golden = pd.read_csv(GOLDEN_FILE)
    found = golden["domain"].isin(df["domain"])
    print(f"Golden-set domains found: {found.sum()}/{len(golden)}")
    missing = golden.loc[~found, "domain"].tolist()
    if missing:
        print("Missing:", missing)


def main():
    tranco = load(TRANCO_FILE, "tranco_rank")
    crux = load(CRUX_FILE, "crux_rank")
    df = merge_sources(tranco, crux)
    df.to_csv(OUT_FILE, index=False)

    print(f"Tranco domains: {len(tranco):,}")
    print(f"CrUX domains:   {len(crux):,}")
    print(f"Unique after merge: {len(df):,}")
    print(df["sources"].value_counts())
    check_golden(df)


if __name__ == "__main__":
    main()