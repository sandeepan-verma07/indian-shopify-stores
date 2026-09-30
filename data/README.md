# data/ — what each pipeline step produced

**Looking for the result? It's in [`../output/stores.csv`](../output/stores.csv) (and `stores.json`).**

The files here are the output of each step, kept so every number in the main README can be checked and any step can be re-run without redoing the ones before it (the full crawl takes hours).

| File | Made by | Rows | What it is |
|---|---|---:|---|
| `golden_set.csv` | by hand | 20 | test set with known answers (Indian Shopify / foreign Shopify / Indian non-Shopify) |
| `dns_results.csv` | `sourcing/dns_check.py` | 50,000 | DNS answer for each checked candidate domain |
| `candidates_dns.csv` | `sourcing/dns_check.py` | 4,160 | domains whose DNS points to Shopify |
| `shopify_verified.csv` | `verify/shopify_check.py` | 4,160 | the 4 Shopify signals, store state, and the store's `meta.json` fields |
| `indian_stores.csv` | `verify/india_score.py` | 3,837 | high-confidence Indian stores (IN + INR + Indian state), deduplicated |
| `edge_cases.csv` | `verify/india_score.py` | 9 | doubtful stores kept out, with the reason (e.g. registered abroad but prices in ₹) |
| `stores_enriched.csv` | `extract/run_extract.py` | 3,837 | fields as first extracted from each store's pages |
| `stores_refined.csv` | `extract/refine.py` | 3,837 | cleaned contacts, GST-checked state, taglines from About pages |
| `ai_categories.csv` | `extract/ai_category.py` | 3,837 | keyword category vs embedding-model category, and whether they agree |
| `live_checks.csv` | `verify/live_checks.py` | 1,703 | does the logo load, does the email domain receive mail |
| `manual_overrides.csv` | by hand | 1 | human corrections, applied by `build_final.py` (never edit the output directly) |
| `all_stores.csv` | `build_final.py` | 3,837 | every store, every field, a pass/fail column per check, `excluded_reason`, `in_final_1000` |
| `audit_log.csv` | `verify/audit.py` | 1,006 | live re-check of every delivered field, with evidence (includes the 6 stores that failed and were replaced) |

Not in the repo (large, and re-created by the steps): `cache/` (saved web pages, ~10 GB), `raw/` (downloaded source lists) and `candidates_{tranco,crux,raw}.csv` (718,855 candidate domains).
