"""Final audit: re-check every field of every store in data/stores.csv against the LIVE site.

The pipeline worked from pages saved days earlier. This script downloads each store's pages again
(fresh - the cache is not used or changed) and checks that what we deliver is really there today:

  shopify    /meta.json answers with a myshopify_domain
  indian     meta.json still says country IN and currency INR
  state      meta.json province still matches our state
  email      every email we list appears on the store's pages      (the ones found -> emails_confirmed)
  phone      every phone we list appears on the store's pages      (the ones found -> phones_confirmed)
  instagram  our Instagram link appears on the store's pages
  tagline    the tagline text appears where we say it came from (meta.json / homepage / About page)
  (logo      was already checked live in Part 6 - verify/live_checks.py)

Each result is PASS, FAIL, N/A (field empty) or UNREACHABLE (page could not be fetched, e.g. Shopify's 429).

INCREMENTAL: stores already fully confirmed in data/audit_log.csv are kept and not downloaded again;
only unconfirmed stores (a FAIL / UNREACHABLE, or new in stores.csv) are checked. build_final.py reads the
log: stores with a confirmed failure are replaced by the next-best store, and contacts not found live are dropped.

  python -m verify.audit --limit 20     # trial on the top 20 (nothing saved)
  python -m verify.audit                # only stores not confirmed yet -> data/audit_log.csv + reports/audit.md
  python -m verify.audit --full         # every store again (~2.5 h)
"""
import argparse
import asyncio
import html as html_lib
import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

import utils.fetcher as fetcher_module
from build_final import clean_emails
from extract.contacts import find_emails, find_phones
from extract.refine import same_state
from extract.run_extract import about_url
from utils.fetcher import Page, PoliteFetcher

STORES_FILE = Path("data/stores.csv")
LOG_FILE = Path("data/audit_log.csv")
REPORT_FILE = Path("reports/audit.md")
FIELDS = ["shopify", "indian", "state", "email", "phone", "instagram", "tagline"]
PAGES = {"meta": "/meta.json", "home": "/", "contact": "/pages/contact",
         "info": "/policies/contact-information", "privacy": "/policies/privacy-policy"}
TAGLINE_PREFIX = 60          # compare the first 60 characters (taglines were trimmed to whole sentences)
STORES_AT_ONCE = 12          # a few stores at a time: steady progress, low memory


def split(cell) -> list[str]:
    return [x for x in str(cell).split("; ") if x]


def squash(text: str) -> str:
    """Unescape HTML, lower-case, one space between words - so formatting differences don't matter."""
    return " ".join(html_lib.unescape(str(text)).lower().split())


def confirmed(row) -> bool:
    """Every field PASS (or empty) in the log."""
    return all(row.get(f, "") in ("PASS", "N/A") for f in FIELDS)


async def fetch_fresh(fetcher: PoliteFetcher, url: str) -> Page:
    """Like fetcher.get() but never reads or writes the cache - we want today's version."""
    if not await fetcher.allowed_by_robots(url):
        return Page(url=url, error="blocked by robots.txt")
    return await fetcher.download(url)


def ok(page: Page | None) -> str:
    return page.text if page and page.status == 200 else ""


# ---------- one store ----------
async def audit_store(fetcher: PoliteFetcher, store: dict) -> dict:
    domain = store["domain_url"].removeprefix("https://")
    pages = {key: await fetch_fresh(fetcher, f"https://{domain}{path}") for key, path in PAGES.items()}
    link = about_url(domain, ok(pages["home"]))          # contacts and taglines can come from the About page too
    about_page = await fetch_fresh(fetcher, link) if link else None

    result = {"rank": store["rank"], "domain": domain, "emails_confirmed": "", "phones_confirmed": ""}
    evidence = {}

    # shopify / indian / state - from a fresh meta.json
    try:
        meta = json.loads(ok(pages["meta"])) if ok(pages["meta"]) else None
    except json.JSONDecodeError:
        meta = None
    if meta is None:
        # 429 = Shopify asked us to slow down: we don't know yet (UNREACHABLE); 404 etc. = the page is gone (FAIL)
        verdict = "UNREACHABLE" if pages["meta"].status in (0, 429) else "FAIL"
        for f in ("shopify", "indian", "state"):
            result[f] = verdict
        evidence["shopify"] = f"meta.json status {pages['meta'].status or pages['meta'].error}"
    else:
        result["shopify"] = "PASS" if meta.get("myshopify_domain") else "FAIL"
        evidence["shopify"] = meta.get("myshopify_domain", "no myshopify_domain")
        country, currency = meta.get("country", ""), meta.get("currency", "")
        result["indian"] = "PASS" if (country, currency) == ("IN", "INR") else "FAIL"
        evidence["indian"] = f"{country} / {currency}"
        province = meta.get("province", "") or ""
        result["state"] = "PASS" if same_state(province, store["state"]) else "FAIL"
        evidence["state"] = f"meta.json: {province}"

    # email / phone - every one we list must appear on the store's own pages today
    text_pages = [ok(pages[k]) for k in ("home", "contact", "info", "privacy")] + [ok(about_page)]
    some_page_throttled = any(p.status == 429 for p in pages.values())
    if not any(text_pages):
        for f in ("email", "phone", "instagram", "tagline"):
            result[f] = "UNREACHABLE"
    else:
        # page by page, so the extractors' per-call limits (5 emails / 3 phones) can't hide a match;
        # emails cleaned on both sides ("mailto:x@y.in", "%20x@y.in" -> "x@y.in")
        live_emails = set(clean_emails(e for p in text_pages if p for e in find_emails(p)))
        live_phones = set().union(*(find_phones(p) for p in text_pages if p))
        for field, ours, live in (("email", clean_emails(split(store["emails"])), live_emails),
                                  ("phone", split(store["phones"]), live_phones)):
            found = [x for x in ours if x in live]
            result[f"{field}s_confirmed"] = "; ".join(found)
            if not ours:
                result[field] = "N/A"
            elif len(found) == len(ours):
                result[field] = "PASS"
            else:   # a missing contact on a throttled page may just not have been seen
                result[field] = "UNREACHABLE" if some_page_throttled else "FAIL"
            evidence[field] = f"{len(found)}/{len(ours)} found" + (
                f"; missing {', '.join(x for x in ours if x not in live)}" if len(found) < len(ours) else "")

        insta = store["instagram"].lower().split("instagram.com/")[-1].strip("/")
        all_html = " ".join(t.lower() for t in text_pages)
        if not store["instagram"]:
            result["instagram"] = "N/A"
        elif f"instagram.com/{insta}" in all_html:
            result["instagram"] = "PASS"
        else:
            result["instagram"] = "UNREACHABLE" if some_page_throttled else "FAIL"
        evidence["instagram"] = f"instagram.com/{insta}" if store["instagram"] else ""

        # tagline - look in the page it came from
        source = store["tagline_source"]
        if source == "meta_json":
            where = (meta or {}).get("description", "") or ""
        elif source.startswith("about_"):
            where = ok(about_page)
        else:                                   # meta_description / og_description / home_title
            where = ok(pages["home"])
        want = squash(store["tagline"])[:TAGLINE_PREFIX]
        result["tagline"] = "PASS" if want and want in squash(where) else "FAIL" if where else "UNREACHABLE"
        evidence["tagline"] = f"source {source}"

    result.update({f"{k}_evidence": v for k, v in evidence.items()})
    result["page_status"] = " ".join(f"{k}:{p.status or p.error}" for k, p in pages.items())
    result["audited_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return result


# ---------- report ----------
def write_report(log: pd.DataFrame, minutes: float, checked_now: int):
    n = len(log)
    lines = ["# Final audit: every delivered field re-checked on the live site", "",
             f"_Generated by `verify/audit.py` - the {n:,} stores currently in `data/stores.csv`, pages downloaded fresh "
             f"(not from the cache). Last run re-checked {checked_now:,} stores in {minutes:.0f} min. "
             f"Full per-store log: `data/audit_log.csv`._", "",
             "| Field | PASS | FAIL | N/A (field empty) | Unreachable | Confirmed |", "|---|---:|---:|---:|---:|---:|"]
    for f in FIELDS:
        c = log[f].value_counts()
        p, fl = c.get("PASS", 0), c.get("FAIL", 0)
        rate = f"{p / (p + fl):.1%}" if p + fl else "-"
        lines.append(f"| {f} | {p:,} | {fl:,} | {c.get('N/A', 0):,} | {c.get('UNREACHABLE', 0):,} | {rate} |")
    clean = log.apply(confirmed, axis=1)
    lines += ["", f"**Stores with every field confirmed: {clean.sum():,} / {n:,}**", "",
              "Logo URLs were checked live separately (Part 6, `verify/live_checks.py`).", ""]

    failed = log[~clean]
    if len(failed):
        lines += ["## Stores with a FAIL or UNREACHABLE field", "", "| Rank | Store | Field | Evidence |", "|---:|---|---|---|"]
        for _, r in failed.iterrows():
            for f in FIELDS:
                if r[f] in ("FAIL", "UNREACHABLE"):
                    lines.append(f"| {r['rank']} | {r['domain']} | {f}: {r[f]} | {r.get(f + '_evidence', '') or r['page_status']} |")
    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


async def run(stores: list[dict]) -> pd.DataFrame:
    start, done = time.time(), 0
    slots = asyncio.Semaphore(STORES_AT_ONCE)
    async with PoliteFetcher() as fetcher:
        async def one(store):
            nonlocal done
            try:
                async with slots:
                    r = await audit_store(fetcher, store)
            except Exception as e:                      # one broken store must not stop the audit
                r = {"rank": store["rank"], "domain": store["domain_url"].removeprefix("https://"),
                     **{f: "UNREACHABLE" for f in FIELDS}, "page_status": f"error {type(e).__name__}"}
            done += 1
            if done % 25 == 0 or done == len(stores):
                el = time.time() - start
                print(f"  audited {done:,}/{len(stores):,} | {el / 60:.0f} min | ~{el / done * (len(stores) - done) / 60:.0f} min left")
            return r
        rows = await asyncio.gather(*(one(s) for s in stores))
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="trial: only the top N stores (nothing saved)")
    parser.add_argument("--full", action="store_true", help="re-check every store, not only unconfirmed ones")
    parser.add_argument("--rate", type=float, default=2.0, help="requests per second (default 2 - gentler, fewer 429s)")
    args = parser.parse_args()
    fetcher_module.MAX_REQUESTS_PER_SEC = args.rate     # the fetcher reads this global for its speed limit

    # keep_default_na=False: otherwise pandas reads our "N/A" results back as blank values
    stores = pd.read_csv(STORES_FILE, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    stores["rank"] = stores["rank"].astype(int)
    stores["domain"] = stores["domain_url"].str.removeprefix("https://")

    old = (pd.read_csv(LOG_FILE, encoding="utf-8-sig", dtype=str, keep_default_na=False)
           if LOG_FILE.exists() and not args.full else pd.DataFrame())
    done_ok = set(old.loc[old.apply(confirmed, axis=1), "domain"]) if len(old) else set()
    todo = stores if args.limit or args.full else stores[~stores["domain"].isin(done_ok)]
    if args.limit:
        todo = todo.head(args.limit)
    print(f"{len(stores):,} stores in stores.csv | already confirmed: {len(done_ok & set(stores['domain'])):,} | "
          f"checking now: {len(todo):,} (fresh downloads, {args.rate:g} requests/sec)")
    if not len(todo):
        print("Nothing to check - every store in stores.csv is confirmed.")
    start = time.time()
    new = asyncio.run(run(todo.to_dict("records"))) if len(todo) else pd.DataFrame()

    if args.limit:
        print(new[["rank", "domain"] + FIELDS].to_string(index=False))
        print("\n(trial - nothing saved)")
        return
    # keep every earlier row (also stores that were dropped - build_final needs their result), newest wins
    log = pd.concat([old, new], ignore_index=True) if len(old) else new
    log = log.drop_duplicates("domain", keep="last").fillna("")
    log.to_csv(LOG_FILE, index=False, encoding="utf-8-sig")

    current = log[log["domain"].isin(stores["domain"])].copy()
    current["rank"] = current["domain"].map(stores.set_index("domain")["rank"])
    current = current.sort_values("rank")
    lines = write_report(current, (time.time() - start) / 60, len(todo))
    print("\n".join(lines[:16]))
    print(f"\nSaved {LOG_FILE} and {REPORT_FILE}")


if __name__ == "__main__":
    main()
