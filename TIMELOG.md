# Time Log

Rivyou asks: *"Document how long you actually spent."* This file is the record.

**Times marked `~` were logged by Claude from screenshots and chat timestamps — correct them if you remember better.**

**How to use it:** one row per work session. Write the start time when you sit down, the end time when you stop, and 1 line on what got done. Add the total at the bottom when you finish.

| Date | Start | End | Hours | Step | What I did |
|---|---|---|---|---|---|
| 25-09-2026 | ~19:55 | __:__ | | 0 | Read the brief, planned the approach, chose Python, created folders, venv, installed packages |
| 26-09-2026 | __:__ | __:__ | | 0 | Built golden test set: checked 12 stores' `/meta.json` by hand, found edge cases (Kylie ships to IN, Snitch domain move, Fashion Nova blocks meta.json) |
| 26-09-2026 | __:__ | __:__ | | 1a | Wrote `sourcing/tranco.py`: Tranco list L5PZ4 → 9,254 `.in`-family domains |
| 26-09-2026 | ~20:50 | | | 1b | Ran CrUX India query on BigQuery (Aug 2026 data) at 20:52 → 1,000,000 origins; exported CSV via Google Drive (33.4 MB) at ~20:58; wrote `sourcing/crux.py` → 716,973 domains (~21:00) |
| 26-09-2026 | ~21:00 | ~21:11 | | 1c | Wrote `sourcing/merge.py` → 718,855 unique candidates; golden-set recall 20/20. **Step 1 complete.** |

| 27-09-2026 | ~00:00 | ~00:38 | | 2 | Learned DNS check by hand (`Resolve-DnsName`); wrote `sourcing/dns_check.py`; golden 20/20; full run on top 50,000 in ~12 min → **4,160 Shopify domains**. **Step 2 complete.** |

| 27-09-2026 | ~00:40 | ~01:00 | | 3 | Learned robots.txt + politeness rules; wrote `utils/fetcher.py`; golden self-test: 18 pages cached, rerun 0 network hits. **Step 3 complete.** |

| 27-09-2026 | ~01:00 | ~01:50 | | 4 | Wrote `verify/shopify_check.py`; golden 20/20; full run (~35 min) → **4,050 confirmed Shopify, 3,924 with meta.json country = IN** |
| 27-09-2026 | ~02:30 | ~03:20 | | 4 | Found 302 cached 429s; fixed fetcher + wrote `utils/clean_cache.py` (targeted version after full-scan was too slow on Windows); rerun → live 3,966, 429s down to 46. **Step 4 complete.** |
| 27-09-2026 | ~03:22 | ~03:29 | | 5 | Wrote `verify/india_score.py` (score + evidence + verdict + dedupe) → **3,843 unique live Indian Shopify stores**; golden 10/10. **Step 5 complete.** |
| 27-09-2026 | ~03:30 | ~03:45 | | 5 | Quality > quantity: main list = country IN + INR + Indian state only → **3,837**; 9 doubtful stores moved to `edge_cases.csv` with reasons; fixed old state names (Daman and Diu) |

| 27-09-2026 | ~03:45 | ~03:55 | | 6 | Step 6 extractors built + tested by Claude (21 real homepages); written into `extract/` at Sandeepan's request |
| 28-09-2026 | ~19:30 | | | 6 | Resumed: recap of Steps 0–5; committed Step 5 + Step 6 files; trial run on 30 stores (97% contact, 93% logo, 77% socials); found category/throttling/placeholder-email/state issues; decided: full fetch first (+ About page), improve parsing after |

| 28-09-2026 | ~20:25 | ~21:35 | | 6 | Full Step 6 run on 3,837 stores (70 min fetch + 1 min parse). Found Shopify rate-limited almost all extra pages (3,510 stores homepage-only) → need a global speed limit before rerunning |

| 28-09-2026 | ~21:40 | ~23:20 | | 6 | Diagnosed the rate-limiting; counted 1,879 stores already complete on 6/7 fields; added global 4 req/s limit + shared 429 pause + non-blocking cache reads (tested on local fake sites) |

| 28–29-09-2026 | ~23:25 | ~02:05 | | 6 | Gentle rerun (4 req/s): 17k requests, 491 throttles, 11 errors → contacts 96%, independent India proof 87%, 2,626 stores with 6/7 fields |
| 29-09-2026 | ~02:05 | ~02:35 | | 6R | Refine Parts 1–3 in `extract/refine.py`: placeholder/shared contacts, GSTIN state cross-check (21 conflicts), taglines from About pages → 3,547 (92%); ~21 doubtful taglines to be excluded at the final gate |
| 29-09-2026 | ~02:35 | ~02:45 | | 6R | Part 5: installed sentence-transformers; wrote `extract/ai_category.py`; trial on 40 stores → 50% agree, all agreed correct on hand check; full run started |
| 29-09-2026 | ~02:45 | ~03:05 | | 6R/7 | AI full run: 2,589 / 3,837 agree (67%); wrote `build_final.py` (checks, ranking, funnel report) → 1,703 pass all checks → best 1,000 → Sandeepan ran it: 1,703 / 1,000 confirmed |
| 29-09-2026 | ~03:45 | ~03:55 | | 6 | Wrote `verify/live_checks.py` (logo loads + email MX), tested on fake server |
| 29-09-2026 | ~19:00 | ~19:30 | | 6/7 | Live checks run: logos 1,644/1,703, MX 1,678/1,703 (83 failed) → rebuild: 1,620 pass all 11 checks → final 1,000. |

**Total so far:** __ hours

---

## Notes per session

Short notes on problems hit and how they were solved. These become the "what I learned / limitations" part of the README.

### 25-09-2026
- Chose Python: network-bound work, good libraries (httpx, dnspython, tldextract, phonenumbers).

### 26-09-2026
- `/meta.json` gives state for Indian Shopify stores directly (10/10 test stores).
- `ships_to_countries` can't be used to decide "Indian" — Kylie Cosmetics (US) ships to IN.
- Snitch moved snitch.co.in → snitch.com → dedupe on `myshopify_domain`.
- fashionnova.com is on Shopify DNS but `/meta.json` is 404 → need multiple Shopify signals.
- Left thewholetruthfoods.com and damensch.com out of the test set (unsure — likely not standard Shopify).
- Tranco `.in` gave only 9,254 domains (mostly big non-store sites) → added CrUX India (BigQuery) for Indian brands on `.com`.
- Merged candidates: 718,855 domains; all 20 golden-set domains present (recall 20/20).

### 27-09-2026
- Public DNS servers throttle at ~30 domains/sec; pushing more at once only creates timeouts → kept it gentle (30 at once).
- Checking all 718k would take ~6.6 h → check most promising first, stop at 50,000.
- Tranco-only `.in` domains gave 0 Shopify stores (ad/parked/infra sites) → moved to the end of the queue.

### 28-09-2026
- Trial on 30 stores showed keyword rules can't categorise stores whose products use model names ("Air Max 90" → not "shoe") → plan: semantic (embedding) model.
- GSTIN on a store's site contradicted its meta.json state (99store.biz: "Andaman and Nicobar" vs GST code 07 = Delhi) → independent evidence matters.
- Shopify throttles `/products.json` harder than other pages.
- Being polite per site is not enough: all stores share Shopify's servers, which rate-limit per visitor. ~40 requests/sec across 3,800 stores → HTTP 429 on nearly every extra page. Need a global cap (~3/s) and a shared pause on 429.
- Reading 3 GB of cached homepages synchronously blocked the async loop for ~30 min and held ~6 GB RAM.

### 29-09-2026
- With a global limit of 4 req/s + shared pause on 429, the same crawl worked: 491 throttles total instead of ~50k failed retries.
- Parsing ~10 GB of cached JSON on Windows took 15 min because Defender scanned every file (83% CPU) — at scale, store pages compressed / in one database file.
- Some Shopify themes ship placeholder contacts (info@yourstore.com, contact@company.com) that stores never replace → must be filtered.
- All Shopify stores share Shopify's servers → Shopify throttled us (429) on 302 homepages. Fetcher had cached those failures → fixed so temporary failures are never cached.
- Scanning a 3 GB cache on Windows is very slow (antivirus scans each file) → cleanup now targets only flagged stores.
