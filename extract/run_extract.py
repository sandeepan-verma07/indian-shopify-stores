"""Step 6: Collect contacts, socials, tagline, logo, category and on-site India proof for every store.

Two phases, so each can be rerun on its own:
  1. FETCH  (network, polite)  - download the few extra pages per store into the cache.
  2. PARSE  (CPU, all cores)   - read pages from the cache and extract the fields.

  python -m extract.run_extract --limit 30      # small trial run
  python -m extract.run_extract                 # all stores
  python -m extract.run_extract --skip-fetch    # only re-parse (after tweaking an extractor)
"""
import argparse
import asyncio
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from extract.category import find_category
from extract.contacts import find_emails, find_phones
from extract.html_text import parse
from extract.india_evidence import find_gstin, find_pincode, independent_evidence
from extract.logo import find_logo
from extract.socials import find_socials
from extract.tagline import find_tagline
from utils.fetcher import PoliteFetcher, cache_path, read_cache

STORES_FILE = Path("data/indian_stores.csv")
OUT_FILE = Path("data/stores_enriched.csv")

PAGES = {                                    # the homepage is already cached from Step 4
    "home": "/",
    "contact": "/pages/contact",
    "contact_info": "/policies/contact-information",
    "privacy": "/policies/privacy-policy",
    "products": "/products.json?limit=30",
}


# the About page has no fixed address (/pages/about-us, /pages/about, /pages/our-story ...),
# so we follow the link the store itself puts on its homepage
ABOUT_WORDS = ("about", "our-story", "who-we-are", "our-journey", "story")


def page_url(domain: str, key: str) -> str:
    return f"https://{domain}{PAGES[key]}"


def about_url(domain: str, home_html: str) -> str:
    """The store's own About page link from its homepage menu/footer ('' if it has none)."""
    for a in parse(home_html).css("a[href]"):
        link = urlparse(a.attributes.get("href") or "")
        if link.netloc and link.netloc.removeprefix("www.") != domain.removeprefix("www."):
            continue                                   # a link to some other website
        path = link.path.rstrip("/")
        if path.startswith("/pages/") and any(word in path.lower() for word in ABOUT_WORDS):
            return f"https://{domain}{path}"
    return ""


# ---------- phase 1: fetch ----------
def about_url_from_cache(domain: str) -> str:
    """Read the saved homepage, return only the About link (the big page is not kept in memory)."""
    return about_url(domain, _text(page_url(domain, "home")))


async def fetch_store(fetcher: PoliteFetcher, domain: str):
    for key in PAGES:
        url = page_url(domain, key)
        if not cache_path(url).exists():          # already saved -> skip without even opening it
            await fetcher.get(url)
    about = await asyncio.to_thread(about_url_from_cache, domain)   # file reading off the main loop
    if about and not cache_path(about).exists():
        await fetcher.get(about)


async def fetch_all(domains: list[str]):
    start = time.time()
    async with PoliteFetcher() as fetcher:
        tasks = [fetch_store(fetcher, d) for d in domains]
        for done, task in enumerate(asyncio.as_completed(tasks), start=1):
            await task
            if done % 100 == 0 or done == len(tasks):
                elapsed = time.time() - start
                eta_min = elapsed / done * (len(tasks) - done) / 60
                print(f"  fetched {done:,}/{len(tasks):,} stores | {elapsed / 60:.0f} min | "
                      f"~{eta_min:.0f} min left | {fetcher.stats}")


# ---------- phase 2: parse (runs in several processes at once) ----------
def _text(url: str) -> str:
    page = read_cache(url) if url else None
    return page.text if page and page.status == 200 else ""


def extract_store(store: dict) -> dict:
    domain = store["domain"]
    home, contact, info, privacy, products = (_text(page_url(domain, k)) for k in PAGES)
    about = _text(about_url(domain, home))
    base = f"https://{domain}/"
    text_pages = (home, contact, info, privacy, about)

    emails = find_emails(*text_pages)
    phones = find_phones(contact, info, home, privacy, about)
    socials = find_socials(home, contact, base=base, brand=domain.split(".")[0].split("-")[0][:6])
    logo, logo_source = find_logo(home, base)
    tagline, tagline_source = find_tagline(store["meta_description"], home, str(store["meta_name"]))
    category, category_source, product_types = find_category(products, f"{tagline} {store['meta_name']}")
    gstin, gstin_state = find_gstin(info, contact, privacy, about, home)
    pincode = find_pincode(info, contact, privacy, about, home)

    return {
        "domain": domain,
        "emails": "; ".join(emails),
        "phones": "; ".join(phones),
        **{f"{name}": url for name, url in socials.items()},
        "logo_url": logo, "logo_source": logo_source,
        "tagline": tagline, "tagline_source": tagline_source,
        "category": category, "category_source": category_source, "top_product_types": product_types,
        "gstin": gstin, "gstin_state": gstin_state, "pincode": pincode,
        "independent_india_evidence": independent_evidence(gstin, phones, pincode),
        "has_about_page": bool(about),
        "pages_found": sum(bool(p) for p in (home, contact, info, privacy, products, about)),
    }


def parse_all(stores: pd.DataFrame) -> pd.DataFrame:
    start = time.time()
    records = stores[["domain", "meta_description", "meta_name"]].to_dict("records")
    workers = max(1, (os.cpu_count() or 2) - 1)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(extract_store, records, chunksize=20))
    print(f"  parsed {len(rows):,} stores with {workers} processes in {time.time() - start:.0f}s")
    return stores.merge(pd.DataFrame(rows), on="domain", how="left")


def coverage_report(df: pd.DataFrame):
    print(f"\nField coverage ({len(df):,} stores):")
    checks = {
        "email": df["emails"] != "", "phone": df["phones"] != "",
        "any contact": (df["emails"] != "") | (df["phones"] != ""),
        "instagram": df["instagram"] != "", "facebook": df["facebook"] != "",
        "any social": df[["instagram", "facebook", "twitter", "linkedin", "youtube"]].ne("").any(axis=1),
        "logo": df["logo_url"] != "", "tagline": df["tagline"] != "",
        "category (not Other)": df["category"] != "Other", "state": df["meta_province"] != "",
        "GSTIN on site": df["gstin"] != "", "independent India proof": df["independent_india_evidence"] != "",
    }
    for name, mask in checks.items():
        print(f"  {name:24} {mask.sum():>5,}  ({mask.mean():.0%})")
    print("\nTop categories:")
    print(df["category"].value_counts().head(12).to_string())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="only the first N stores (trial run)")
    parser.add_argument("--skip-fetch", action="store_true", help="only re-parse from the cache")
    args = parser.parse_args()

    stores = pd.read_csv(STORES_FILE)
    if args.limit:
        stores = stores.head(args.limit)
    print(f"Step 6 on {len(stores):,} stores")

    if not args.skip_fetch:
        print("Phase 1: fetching pages (cached pages are reused)")
        asyncio.run(fetch_all(stores["domain"].tolist()))

    print("Phase 2: extracting fields")
    df = parse_all(stores).fillna({"emails": "", "phones": ""}).fillna("")
    df.to_csv(OUT_FILE, index=False)
    print(f"Saved {OUT_FILE}")
    coverage_report(df)


if __name__ == "__main__":
    main()
