"""Step 3: A polite, cached, parallel web fetcher shared by every later step.

Rules it enforces:
  1. robots.txt is checked before every request.
  2. One request at a time per site, with a pause between them.
  3. 429 / 5xx answers are retried with growing waits; then we give up.
  4. Every answer is saved to data/cache/, so reruns never hit the site again.
  5. A GLOBAL speed limit (MAX_REQUESTS_PER_SEC) across all sites: every Shopify store
     sits on Shopify's shared servers, which rate-limit per visitor, not per store.
  6. When any site says 429 "too many requests", EVERYONE pauses, not just that site.
Many sites are fetched in parallel (MAX_PARALLEL), but no single site is flooded.
"""
import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

CACHE_DIR = Path("data/cache")
USER_AGENT = "RivyouStoreResearchBot/1.0 (student assignment; polite, cached crawler)"
MAX_PARALLEL = 12          # requests in flight across ALL sites
MAX_REQUESTS_PER_SEC = 4.0 # global speed limit across ALL sites (Shopify limits per visitor)
PER_SITE_DELAY = 1.0       # seconds between two requests to the same site
TIMEOUT = 15               # seconds per request
MAX_RETRIES = 3            # extra tries after a 429 / 5xx
MAX_BODY_CHARS = 2_000_000 # don't store giant pages
RETRY_STATUSES = {429, 500, 502, 503, 504}
BACKOFF_SECONDS = (10, 30, 60)   # waits after a 429 / 5xx when the site gives no Retry-After


## making record and temporary cache so that if reruns then not redudant reruns



@dataclass
class Page:
    url: str
    final_url: str = ""
    status: int = 0           # 0 = never got an answer (network error / blocked by robots)
    headers: dict | None = None
    text: str = ""
    error: str = ""
    from_cache: bool = False


def cache_path(url: str) -> Path:
    host = (urlparse(url).hostname or "unknown").replace(":", "_")
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    return CACHE_DIR / host / f"{key}.json"


def read_cache(url: str) -> Page | None:
    path = cache_path(url)
    if not path.exists():
        return None
    page = Page(**json.loads(path.read_text(encoding="utf-8")))
    page.from_cache = True
    return page


def write_cache(page: Page):
    path = cache_path(page.url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(page), ensure_ascii=False), encoding="utf-8")



## async fetches parallel



class PoliteFetcher:
    """Use as:  async with PoliteFetcher() as f:  page = await f.get(url)"""

    def __init__(self):
        self.client = None
        self.parallel = asyncio.Semaphore(MAX_PARALLEL)
        self.site_locks: dict[str, asyncio.Lock] = {}
        self.last_hit: dict[str, float] = {}
        self.robots: dict[str, RobotFileParser] = {}
        self.robots_locks: dict[str, asyncio.Lock] = {}
        self.rate_lock = asyncio.Lock()          # global speed limit
        self.next_slot = 0.0                     # earliest time the next request may start
        self.paused_until = 0.0                  # shared pause after a 429
        self.stats = {"network": 0, "cache": 0, "robots_blocked": 0, "errors": 0, "throttled": 0}

    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *exc):
        await self.client.aclose()


    async def get(self, url: str) -> Page:
        cached = await asyncio.to_thread(read_cache, url)   # file reading off the main loop
        if cached:
            self.stats["cache"] += 1
            return cached

        if not await self.allowed_by_robots(url):
            self.stats["robots_blocked"] += 1
            return Page(url=url, error="blocked by robots.txt")

        page = await self.download(url)
        if page.status and page.status not in RETRY_STATUSES:                    # got a real answer (even 404) -> remember it
            await asyncio.to_thread(write_cache, page)
        return page


### robots.txt fetching

    async def allowed_by_robots(self, url: str) -> bool:
        parts = urlparse(url)
        host = parts.netloc
        lock = self.robots_locks.setdefault(host, asyncio.Lock())
        async with lock:                      # only the first caller downloads robots.txt
            if host not in self.robots:
                robots_url = f"{parts.scheme}://{host}/robots.txt"
                page = await asyncio.to_thread(read_cache, robots_url) or await self.download(robots_url)
                if page.status and page.status not in RETRY_STATUSES:
                    await asyncio.to_thread(write_cache, page)
                parser = RobotFileParser()
                if page.status == 200:
                    parser.parse(page.text.splitlines())
                elif page.status in (401, 403):
                    parser.disallow_all = True    # site forbids bots entirely
                else:
                    parser.allow_all = True       # no robots.txt -> everything allowed
                self.robots[host] = parser
        return self.robots[host].can_fetch(USER_AGENT, url)



## network calls
    async def download(self, url: str) -> Page:
        host = urlparse(url).netloc
        lock = self.site_locks.setdefault(host, asyncio.Lock())

        async with lock:                      # rule 2: one request at a time per site
            for attempt in range(MAX_RETRIES + 1):
                await self.wait_for_turn(host)
                await self.wait_global_turn()
                async with self.parallel:     # cap on total requests in flight
                    try:
                        resp = await self.client.get(url)
                    except httpx.HTTPError as e:
                        self.stats["errors"] += 1
                        return Page(url=url, error=type(e).__name__)
                self.stats["network"] += 1

                if resp.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
                    wait = self.backoff_seconds(resp, attempt)
                    if resp.status_code == 429:                                # rule 6: everyone pauses
                        self.stats["throttled"] += 1
                        self.paused_until = max(self.paused_until, time.monotonic() + wait)
                    await asyncio.sleep(wait)                                  # rule 3
                    continue

                keep = ("content-type", "server", "x-shopid", "powered-by", "x-shopify-stage")
                return Page(
                    url=url,
                    final_url=str(resp.url),
                    status=resp.status_code,
                    headers={k: v for k, v in resp.headers.items() if k.lower() in keep},
                    text=resp.text[:MAX_BODY_CHARS],
                )

    async def wait_for_turn(self, host: str):
        elapsed = time.monotonic() - self.last_hit.get(host, 0)
        if elapsed < PER_SITE_DELAY:
            await asyncio.sleep(PER_SITE_DELAY - elapsed)
        self.last_hit[host] = time.monotonic()

    async def wait_global_turn(self):
        """Rule 5 + 6: at most MAX_REQUESTS_PER_SEC requests start per second, and nobody
        starts while a shared 429-pause is running. Requests queue up in order."""
        async with self.rate_lock:
            wait = max(self.next_slot, self.paused_until) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self.next_slot = time.monotonic() + 1 / MAX_REQUESTS_PER_SEC

    @staticmethod
    def backoff_seconds(resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("retry-after", "")
        if retry_after.isdigit():
            return min(int(retry_after), 120)
        return BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]   # 10s, 30s, 60s


## test on trial set of golden set
async def self_test():
    import pandas as pd
    domains = pd.read_csv("data/golden_set.csv")["domain"].tolist()
    urls = [f"https://{d}/meta.json" for d in domains]

    for run in (1, 2):
        start = time.time()
        async with PoliteFetcher() as fetcher:
            pages = await asyncio.gather(*(fetcher.get(u) for u in urls))
        print(f"\nRun {run}: {time.time() - start:.1f}s  stats={fetcher.stats}")
        if run == 1:
            for p in pages:
                print(f"  {p.status:>3} {p.url:45} {p.error}")


if __name__ == "__main__":
    asyncio.run(self_test())
