"""Step 1b: Turn the CrUX India origin list into clean registered domains."""
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import tldextract

from sourcing.tranco import EXCLUDED_SUFFIXES

IN_FILE = Path("data/raw/crux_in.csv")
OUT_FILE = Path("data/candidates_crux.csv")


## convert www to just domains 

def origin_to_domain(origin: str) -> str | None:
    host = urlparse(origin).hostname        
    if not host:
        return None

    if host.endswith(".myshopify.com"):
        return host                         

    ext = tldextract.extract(host)
    if not ext.domain or not ext.suffix:    
        return None
    if ext.suffix in EXCLUDED_SUFFIXES:      
        return None

    return f"{ext.domain}.{ext.suffix}"      


## processes all the rows around  1 million from crux
def main():
    df = pd.read_csv(IN_FILE)
    print(f"Origins in CrUX India: {len(df):,}")

    df["domain"] = df["origin"].apply(origin_to_domain)
    df = df.dropna(subset=["domain"])

    # Many origins can become the same domain; keep one row, with the best rank
    df = df.groupby("domain", as_index=False)["source_rank"].min()
    df["source"] = "crux_in"
    df = df[["domain", "source", "source_rank"]].sort_values("source_rank")

    df.to_csv(OUT_FILE, index=False)
    print(f"Unique domains kept: {len(df):,}")
    print("Domains per rank band:")
    print(df["source_rank"].value_counts().sort_index())
    print("Sample:", df["domain"].head(10).tolist())


if __name__ == "__main__":
    main()