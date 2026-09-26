"""Step 4: Confirm each DNS candidate is a real, live Shopify store using several independent signals."""
import argparse
import asyncio
import json
import time
from pathlib import Path

import pandas as pd

from utils.fetcher import Page, PoliteFetcher

DNS_FILE = Path("data/candidates_dns.csv")
GOLDEN_FILE = Path("data/golden_set.csv")
OUT_FILE = Path("data/shopify_verified.csv")

HTML_MARKERS = ("cdn.shopify.com", "window.Shopify", "Shopify.theme", ".myshopify.com")
META_FIELDS = ["name", "city", "province", "country", "currency", "domain",
               "myshopify_domain", "description", "published_products_count"]
MIN_SIGNALS = 2                 # need at least 2 of the 4 signals to call it Shopify

### ---------- the 4 signals ----------
def parse_meta(page: Page) -> dict | None:
    """meta.json as a dict, but ONLY if it is real Shopify JSON (tatacliq sends HTML with status 200)."""
    if page.status != 200:
        return None
    try:
        data = json.loads(page.text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and data.get("myshopify_domain"):
        return data
    return None


def html_has_shopify(page: Page) -> bool:
    return page.status == 200 and any(marker in page.text for marker in HTML_MARKERS)


def headers_say_shopify(*pages: Page) -> bool:
    for page in pages:
        headers = {k.lower(): v.lower() for k, v in (page.headers or {}).items()}
        if headers.get("powered-by") == "shopify" or "x-shopid" in headers:
            return True
    return False


def store_state(home: Page, meta: dict | None) -> str:
    """Is the store actually open for business?"""
    if "/password" in home.final_url:
        return "password_protected"            # Shopify's "opening soon" lock screen
    if home.status == 200:
        if meta and meta.get("published_products_count") == 0:
            return "no_products"
        return "live"
    if home.status:
        return f"http_{home.status}"
    return "unreachable"


# ---------- check one store ----------
async def check_store(fetcher: PoliteFetcher, domain: str, dns_ok: bool) -> dict:
    meta_page = await fetcher.get(f"https://{domain}/meta.json")
    meta = parse_meta(meta_page)
    if meta is None and not domain.startswith("www."):
        meta = parse_meta(await fetcher.get(f"https://www.{domain}/meta.json"))
    home = await fetcher.get(f"https://{domain}/")

    signals = {
        "sig_dns": dns_ok,
        "sig_meta_json": meta is not None,
        "sig_html": html_has_shopify(home),
        "sig_headers": headers_say_shopify(meta_page, home),
    }
    row = {"domain": domain, **signals, "signal_count": sum(signals.values())}
    row["is_shopify"] = row["signal_count"] >= MIN_SIGNALS
    row["store_state"] = store_state(home, meta)
    row["home_status"] = home.status
    row["final_url"] = home.final_url
    row["fetch_error"] = home.error or meta_page.error
    for field in META_FIELDS:
        row[f"meta_{field}"] = (meta or {}).get(field, "")
    return row


###

async def check_all(domains: list[str], dns_flags: dict[str, bool]) -> list[dict]:
    results = []
    start = time.time()
    async with PoliteFetcher() as fetcher:
        tasks = [check_store(fetcher, d, dns_flags[d]) for d in domains]
        for done, next_result in enumerate(asyncio.as_completed(tasks), start=1):
            results.append(await next_result)
            if done % 250 == 0 or done == len(tasks):
                print(f"{done:,}/{len(tasks):,} stores | {time.time() - start:.0f}s | {fetcher.stats}")
    return results


####
# ---------- modes ----------
def run_golden():
    from sourcing.dns_check import check_many          # reuse Step 2 for the DNS signal

    golden = pd.read_csv(GOLDEN_FILE)
    domains = golden["domain"].tolist()
    dns_rows = asyncio.run(check_many(domains))
    dns_flags = {r["domain"]: r["status"] == "shopify" for r in dns_rows}

    results = {r["domain"]: r for r in asyncio.run(check_all(domains, dns_flags))}
    correct = 0
    print()
    for row in golden.itertuples():
        r = results[row.domain]
        ok = r["is_shopify"] == (row.is_shopify == "yes")
        correct += ok
        signals = "".join("✓" if r[s] else "·" for s in ("sig_dns", "sig_meta_json", "sig_html", "sig_headers"))
        print(f"{'OK  ' if ok else 'FAIL'} {row.domain:26} expected={row.is_shopify:3} "
              f"signals[dns,meta,html,hdr]={signals} state={r['store_state']:18} country={r['meta_country']}")
    print(f"\nGolden set: {correct}/{len(golden)} correct")


def run_full():
    domains = pd.read_csv(DNS_FILE)["domain"].tolist()
    print(f"Checking {len(domains):,} DNS-Shopify candidates (cached pages are reused)\n")
    results = asyncio.run(check_all(domains, {d: True for d in domains}))

    df = pd.DataFrame(results).sort_values("domain")
    df.to_csv(OUT_FILE, index=False)

    print(f"\nSaved {len(df):,} rows to {OUT_FILE}")
    print("\nConfirmed Shopify:", df["is_shopify"].value_counts().to_dict())
    print("\nSignals found (of confirmed):")
    confirmed = df[df["is_shopify"]]
    for s in ("sig_meta_json", "sig_html", "sig_headers"):
        print(f"  {s:14} {confirmed[s].sum():,}")
    print("\nStore state (of confirmed):")
    print(confirmed["store_state"].value_counts().to_string())
    print("\nTop countries in meta.json (preview of Step 5):")
    print(confirmed["meta_country"].replace("", "(no meta.json)").value_counts().head(10).to_string())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", action="store_true", help="only test on the golden set")
    args = parser.parse_args()
    run_golden() if args.golden else run_full()