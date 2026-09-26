"""Step 1a: Download the Tranco top-1M list and keep Indian-TLD domains."""
import csv
import io
import zipfile
from pathlib import Path

import httpx
import tldextract

TRANCO_URL = "https://tranco-list.eu/top-1m.csv.zip"
TRANCO_ID_URL = "https://tranco-list.eu/top-1m-id"
RAW_DIR = Path("data/raw")
OUT_FILE = Path("data/candidates_tranco.csv")

EXCLUDED_SUFFIXES = {"gov.in", "nic.in", "ac.in", "edu.in", "res.in", "mil.in"}


## filters

def is_indian_commercial(domain: str) -> bool:
    suffix = tldextract.extract(domain).suffix
    is_indian = suffix == "in" or suffix.endswith(".in")
    return is_indian and suffix not in EXCLUDED_SUFFIXES


## downloads


def download_tranco() -> list[tuple[int, str]]:
    resp = httpx.get(TRANCO_URL, follow_redirects=True, timeout=120)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        text = zf.read(zf.namelist()[0]).decode("utf-8")

    rows = []
    for line in text.splitlines():
        if not line:
            continue
        rank, domain = line.split(",", 1)
        rows.append((int(rank), domain.strip().lower()))
    return rows


#saving the list and seeing the final output with how many it generated 
def save_list_id():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    list_id = httpx.get(TRANCO_ID_URL, timeout=30).text.strip()
    (RAW_DIR / "tranco_list_id.txt").write_text(list_id)
    print(f"Tranco list ID: {list_id}")


def main():
    save_list_id()
    rows = download_tranco()
    kept = [(rank, d) for rank, d in rows if is_indian_commercial(d)]

    with OUT_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["domain", "source", "source_rank"])
        for rank, domain in kept:
            writer.writerow([domain, "tranco", rank])

    print(f"Total in Tranco: {len(rows):,}")
    print(f"Kept (.in family): {len(kept):,}")
    print("Sample:", [d for _, d in kept[:10]])


if __name__ == "__main__":
    main()