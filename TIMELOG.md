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
