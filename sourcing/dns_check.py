"""Step 2: Keep only candidate domains whose DNS points to Shopify."""
import argparse
import asyncio
import csv
import time
from pathlib import Path

import dns.asyncresolver
import dns.exception
import dns.resolver
import pandas as pd

CANDIDATES_FILE = Path("data/candidates_raw.csv")
GOLDEN_FILE = Path("data/golden_set.csv")
RESULTS_FILE = Path("data/dns_results.csv")      # every domain checked (lets us resume)
OUT_FILE = Path("data/candidates_dns.csv")       # only the Shopify ones

SHOPIFY_IP_PREFIX = "23.227.38."
SHOPIFY_CNAME = "myshopify.com."
NAMESERVERS = ["1.1.1.1", "8.8.8.8"]             # Cloudflare + Google public DNS
CONCURRENCY = 30                                 # questions in flight at once (more = timeouts)
BATCH_SIZE = 5000                                # save progress after every batch
DEFAULT_LIMIT = 50000                            # how many top candidates to check
FIELDS = ["domain", "status", "matched_host", "ips", "cname"]


## resolve the dns first

def make_resolver() -> dns.asyncresolver.Resolver:
    resolver = dns.asyncresolver.Resolver(configure=False)
    resolver.nameservers = NAMESERVERS
    resolver.timeout = 2        # seconds per try
    resolver.lifetime = 4       # seconds in total, including retries
    return resolver


async def lookup(resolver, host: str) -> tuple[list[str], str]:
    """Return (IPv4 addresses, final CNAME target) for one hostname."""
    answer = await resolver.resolve(host, "A")
    ips = [record.address for record in answer]
    cname = str(answer.canonical_name)            # same as host if there is no CNAME
    return ips, cname


def looks_like_shopify(ips: list[str], cname: str) -> bool:
    return any(ip.startswith(SHOPIFY_IP_PREFIX) for ip in ips) or cname.endswith(SHOPIFY_CNAME)


## check domain

async def check_domain(resolver, semaphore, domain: str) -> dict:
    """Check domain.com first; if that isn't Shopify, check www.domain.com."""
    hosts = [domain] if domain.startswith("www.") else [domain, f"www.{domain}"]
    status = "no_dns"

    async with semaphore:
        for host in hosts:
            try:
                ips, cname = await lookup(resolver, host)
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
                continue                              # this host doesn't exist, try the next
            except dns.exception.Timeout:
                status = "timeout"
                continue

            if looks_like_shopify(ips, cname):
                return {"domain": domain, "status": "shopify", "matched_host": host,
                        "ips": " ".join(ips), "cname": cname}
            status = "not_shopify"

    return {"domain": domain, "status": status, "matched_host": "", "ips": "", "cname": ""}


async def check_many(domains: list[str]) -> list[dict]:
    resolver = make_resolver()
    semaphore = asyncio.Semaphore(CONCURRENCY)
    tasks = [check_domain(resolver, semaphore, d) for d in domains]
    return await asyncio.gather(*tasks)


def load_in_priority_order() -> list[str]:
    """Most promising first: in both lists, then CrUX by popularity, Tranco-only last."""
    df = pd.read_csv(CANDIDATES_FILE)
    df["priority"] = df["sources"].map({"tranco|crux_in": 0, "crux_in": 1, "tranco": 2})
    df = df.sort_values(["priority", "crux_rank", "tranco_rank"], na_position="last")
    return df["domain"].tolist()


def already_checked() -> set[str]:
    """Domains with a final answer. Timeouts are NOT included, so a rerun retries them."""
    if not RESULTS_FILE.exists():
        return set()
    results = pd.read_csv(RESULTS_FILE, usecols=["domain", "status"])
    results = results.drop_duplicates("domain", keep="last")
    return set(results.loc[results["status"] != "timeout", "domain"])


def append_results(rows: list[dict]):
    is_new = not RESULTS_FILE.exists()
    with RESULTS_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def save_shopify_list():
    results = pd.read_csv(RESULTS_FILE).drop_duplicates("domain", keep="last")
    shopify = results[results["status"] == "shopify"]
    shopify.to_csv(OUT_FILE, index=False)
    print("\nStatus counts (all runs so far):")
    print(results["status"].value_counts())
    print(f"Saved {len(shopify):,} Shopify domains to {OUT_FILE}")
    
    
    
def run_golden():
    """Test mode: check the golden set and compare with the known answers."""
    golden = pd.read_csv(GOLDEN_FILE)
    results = asyncio.run(check_many(golden["domain"].tolist()))
    correct = 0
    for row, result in zip(golden.itertuples(), results):
        expected = row.is_shopify == "yes"
        got = result["status"] == "shopify"
        correct += expected == got
        mark = "OK  " if expected == got else "FAIL"
        print(f"{mark} {row.domain:28} expected={row.is_shopify:3}  got={result['status']:12} {result['matched_host']}")
    print(f"\nGolden set: {correct}/{len(golden)} correct")


def run_full(limit: int):
    candidates = load_in_priority_order()[:limit]
    done = already_checked()
    todo = [d for d in candidates if d not in done]
    print(f"Checking top {len(candidates):,} candidates | already done: {len(candidates) - len(todo):,} | to do: {len(todo):,}")

    start = time.time()
    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i:i + BATCH_SIZE]
        rows = asyncio.run(check_many(batch))
        append_results(rows)

        finished = i + len(batch)
        found = sum(r["status"] == "shopify" for r in rows)
        timeouts = sum(r["status"] == "timeout" for r in rows)
        rate = finished / (time.time() - start)
        print(f"{finished:,}/{len(todo):,} | Shopify: {found} | timeouts: {timeouts} | {rate:.0f} domains/sec")

    save_shopify_list()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", action="store_true", help="only test on the golden set")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="check only the top N candidates")
    args = parser.parse_args()
    if args.golden:
        run_golden()
    else:
        run_full(args.limit)