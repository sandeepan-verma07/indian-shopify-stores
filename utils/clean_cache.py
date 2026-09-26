"""Delete cached temporary failures (429 / 5xx) for stores Step 4 flagged, so the next run refetches them.

Only looks at the few hundred stores that were not fully OK, instead of opening every file in the cache.
"""
import json

import pandas as pd

from utils.fetcher import RETRY_STATUSES, cache_path

VERIFIED_FILE = "data/shopify_verified.csv"


def urls_to_check() -> list[str]:
    df = pd.read_csv(VERIFIED_FILE)
    flagged = df[(df["store_state"] != "live") | (~df["sig_meta_json"])]
    urls = []
    for domain in flagged["domain"]:
        urls += [f"https://{domain}/", f"https://{domain}/meta.json",
                 f"https://{domain}/robots.txt", f"https://www.{domain}/meta.json"]
    print(f"{len(flagged):,} flagged stores -> {len(urls):,} cached pages to look at")
    return urls


def main():
    checked = removed = 0
    for url in urls_to_check():
        path = cache_path(url)
        if not path.exists():
            continue
        checked += 1
        status = json.loads(path.read_text(encoding="utf-8")).get("status")
        if status in RETRY_STATUSES:
            path.unlink()
            removed += 1
    print(f"Checked {checked:,} cached pages, removed {removed:,} temporary failures (429/5xx)")


if __name__ == "__main__":
    main()