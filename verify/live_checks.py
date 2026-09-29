"""Part 6: live checks on the stores that passed every other check.

Finding a logo URL or an email address is not the same as it working. For each candidate store:
  1. logo loads      - the logo URL answers 200 with an image (only the headers are read, the image is not downloaded)
  2. email domain MX - the domain of the store's own email has mail servers (a DNS question; no email is ever sent)

Candidates = stores in data/all_stores.csv that pass all the non-live checks (written by build_final.py).
Writes data/live_checks.csv; rerun `python build_final.py` afterwards and it adds these 2 checks.

  python -m verify.live_checks --limit 20    # trial on 20 stores
  python -m verify.live_checks               # all candidates (~10 min)
"""
import argparse
import asyncio
import time
from pathlib import Path

import dns.asyncresolver
import dns.exception
import dns.resolver
import httpx
import pandas as pd

from sourcing.dns_check import make_resolver
from utils.fetcher import BACKOFF_SECONDS, MAX_REQUESTS_PER_SEC, RETRY_STATUSES, TIMEOUT, USER_AGENT

IN_FILE = Path("data/all_stores.csv")
OUT_FILE = Path("data/live_checks.csv")
LIVE_CHECK_COLUMNS = {"chk_logo_loads", "chk_email_domain_mx"}   # added by build_final once this file exists
LOGO_PARALLEL = 8
DNS_PARALLEL = 20


def candidates() -> pd.DataFrame:
    """Stores that pass every check except the live ones (so a rerun checks the same set)."""
    df = pd.read_csv(IN_FILE, low_memory=False).fillna("")
    checks = [c for c in df.columns if c.startswith("chk_") and c not in LIVE_CHECK_COLUMNS]
    passed = df[checks].astype(str).eq("True").all(axis=1)
    return df.loc[passed, ["domain", "logo_url", "own_email"]].reset_index(drop=True)


# ---------- 1. logo loads ----------
class RateLimit:
    """Same global speed limit as the fetcher: at most MAX_REQUESTS_PER_SEC requests, shared by everyone."""
    def __init__(self):
        self.lock, self.next_slot = asyncio.Lock(), 0.0

    async def wait(self):
        async with self.lock:
            delay = self.next_slot - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self.next_slot = time.monotonic() + 1 / MAX_REQUESTS_PER_SEC


async def check_logo(client, limit, semaphore, url: str) -> tuple[bool, str]:
    """(loads?, what we saw) e.g. (True, '200 image/png') or (False, '404')."""
    async with semaphore:
        for attempt in range(len(BACKOFF_SECONDS) + 1):
            await limit.wait()
            try:
                async with client.stream("GET", url) as r:          # headers only - the body is never read
                    kind = r.headers.get("content-type", "").split(";")[0].strip()
                    if r.status_code in RETRY_STATUSES and attempt < len(BACKOFF_SECONDS):
                        await asyncio.sleep(BACKOFF_SECONDS[attempt])
                        continue
                    ok = r.status_code == 200 and kind.startswith("image/")
                    return ok, f"{r.status_code} {kind}".strip()
            except httpx.HTTPError as e:
                if attempt == len(BACKOFF_SECONDS):
                    return False, f"error {type(e).__name__}"
                await asyncio.sleep(BACKOFF_SECONDS[attempt])
    return False, "gave up"


async def check_logos(urls: list[str]) -> list[tuple[bool, str]]:
    limit, semaphore = RateLimit(), asyncio.Semaphore(LOGO_PARALLEL)
    headers = {"User-Agent": USER_AGENT}
    start, done = time.time(), 0

    async def one(client, url):
        nonlocal done
        result = await check_logo(client, limit, semaphore, url)
        done += 1
        if done % 200 == 0 or done == len(urls):
            print(f"  logos checked {done:,}/{len(urls):,} | {time.time() - start:.0f}s")
        return result

    async with httpx.AsyncClient(headers=headers, timeout=TIMEOUT, follow_redirects=True) as client:
        return await asyncio.gather(*(one(client, u) for u in urls))   # results stay in the same order as urls


# ---------- 2. email domain has mail servers ----------
async def has_mx(resolver, semaphore, domain: str) -> tuple[bool, str]:
    async with semaphore:
        for _ in range(3):                                          # public DNS sometimes times out
            try:
                answer = await resolver.resolve(domain, "MX")
                hosts = sorted(str(r.exchange).rstrip(".") for r in answer)
                return bool(hosts), hosts[0] if hosts else "empty"
            except dns.resolver.NXDOMAIN:
                return False, "domain does not exist"
            except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
                return False, "no MX record"
            except dns.exception.Timeout:
                continue
        return False, "timeout"


async def check_email_domains(domains: list[str]) -> dict[str, tuple[bool, str]]:
    resolver, semaphore = make_resolver(), asyncio.Semaphore(DNS_PARALLEL)
    unique = sorted(set(d for d in domains if d))
    answers = await asyncio.gather(*(has_mx(resolver, semaphore, d) for d in unique))
    return dict(zip(unique, answers))


# ---------- main ----------
async def run(stores: pd.DataFrame) -> pd.DataFrame:
    start = time.time()
    email_domains = stores["own_email"].str.split("@").str[-1].str.lower()
    print(f"Checking mail servers for {email_domains.nunique():,} email domains...")
    mx = await check_email_domains(email_domains.tolist())
    print(f"  done in {time.time() - start:.0f}s")

    print(f"Checking {len(stores):,} logos (max {MAX_REQUESTS_PER_SEC:g} requests/sec)...")
    logos = await check_logos(stores["logo_url"].tolist())

    return pd.DataFrame({
        "domain": stores["domain"],
        "logo_loads": [ok for ok, _ in logos],
        "logo_status": [seen for _, seen in logos],
        "email_domain": email_domains,
        "email_domain_mx": [mx.get(d, (False, ""))[0] for d in email_domains],
        "mx_status": [mx.get(d, (False, ""))[1] for d in email_domains],
    })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="trial: only the first N candidates, nothing saved")
    args = parser.parse_args()

    stores = candidates()
    print(f"Candidates (pass all other checks): {len(stores):,}")
    if args.limit:
        stores = stores.head(args.limit)
    out = asyncio.run(run(stores))

    print(f"\nLogo loads:        {out['logo_loads'].sum():,} / {len(out):,}")
    print(f"Email domain (MX): {out['email_domain_mx'].sum():,} / {len(out):,}")
    failed = out[~out["logo_loads"] | ~out["email_domain_mx"]]
    if len(failed):
        print(f"\nFailed ({len(failed)}), first 15:")
        print(failed[["domain", "logo_status", "email_domain", "mx_status"]].head(15).to_string(index=False))
    if args.limit:
        print("\n(trial - nothing saved)")
    else:
        out.to_csv(OUT_FILE, index=False)
        print(f"\nSaved {OUT_FILE} - now rerun: python build_final.py")


if __name__ == "__main__":
    main()
