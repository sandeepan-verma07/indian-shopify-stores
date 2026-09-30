# indian-shopify-stores

Finding Shopify stores that are actually run from India, and pulling out who they are, what they sell and how to reach them.
Built by Sandeepan Verma for the Rivyou SDE Intern assignment.

![stores](https://img.shields.io/badge/stores-1%2C000-2ea44f)
![verified](https://img.shields.io/badge/every%20field-re--checked%20live-2ea44f)
![sources](https://img.shields.io/badge/data%20sources-free%20%26%20public-blue)
![python](https://img.shields.io/badge/python-3.11-blue)

**The data:** [`output/stores.csv`](output/stores.csv) · [`output/stores.json`](output/stores.json) · [download csv](https://raw.githubusercontent.com/sandeepan-verma07/indian-shopify-stores/main/output/stores.csv) · [download json](https://raw.githubusercontent.com/sandeepan-verma07/indian-shopify-stores/main/output/stores.json) · [what each column means](output/README.md)

---

## The short version

I started from 718,855 domains from two public popularity lists, most of them sites that Indian Chrome users visit, kept the ones whose DNS points at Shopify, confirmed each one is a real, live Shopify store, and kept only stores whose own Shopify settings say they are registered in India, price in rupees and sit in an Indian state. Then I read each store's own pages for the seven fields, threw out anything I couldn't trust, and finally went back to the live site for every one of the 1,000 stores I deliver and checked each field again.

```
  718,855  candidate domains            Tranco (.in) + Chrome UX Report, India
   50,000  DNS-checked                  most popular first
    4,160  DNS points to Shopify
    3,966  confirmed live Shopify       at least 2 of 4 independent signals
    3,837  confirmed Indian             country IN + INR + Indian state, deduplicated
    1,614  pass all 12 quality checks   complete, consistent, verified fields
    1,000  delivered                    best-ranked; every field re-checked on the live site
```

Every number above is produced by the code and written to [`reports/funnel.md`](reports/funnel.md), with examples of what got dropped at each stage and why. The live re-check is in [`reports/audit.md`](reports/audit.md): 1,000 of 1,000 stores confirmed.

The brief says 700 clean rows beat 1,500 noisy ones. I took that literally. Around 1,600 stores passed everything; I ranked them and handed over the top 1,000 rather than the biggest number I could reach.

---

## What I mean by "Shopify" and "Indian"

**Shopify.** A domain counts if at least two of these agree: its DNS points at Shopify (`23.227.38.x` or `shops.myshopify.com`), `/meta.json` returns real Shopify JSON, the homepage loads assets from `cdn.shopify.com`, or the response headers carry `powered-by: Shopify` / `x-shopid`. The final list asks for all four. Stores behind a password page, with zero products, or not answering are left out.

**Indian.** I read it from the store's own Shopify settings rather than guessing from the domain name. `/meta.json` must say country `IN`, currency `INR` and give an Indian state or union territory. On top of that, the site itself has to show something Indian: a valid +91 number, a GST number, or an Indian PIN code. "Ships to India" doesn't count; Kylie Cosmetics ships here too.

**The awkward cases the brief asks about:**

- An Indian brand on a `.com` is in. Two thirds of the final list isn't on `.in`, which is why the main source is the Chrome UX Report for India and not a list of `.in` domains.
- A `.in` domain proves nothing on its own. It's only ever a weak hint.
- A brand registered abroad but selling in rupees (blinglane.com, Canada) or registered in India but selling only in dollars (kalkifashion.com, an exporter) is genuinely ambiguous. I didn't guess: those nine stores are in [`data/edge_cases.csv`](data/edge_cases.csv) with the reason, and not in the main list.
- One store on two domains (snitch.co.in and snitch.com) is counted once. Shopify gives every store a unique internal `myshopify_domain`, which is what I deduplicate on, keeping the domain the store itself calls primary.

**The seven fields** all come from the store's own website, copied as-is. If something isn't there it stays empty; nothing is written by me.

---

## How each step works

<details>
<summary><b>1. Finding candidates</b> (free public lists, no scraping of search engines)</summary>

- **Tranco top 1M** (list `L5PZ4`), keeping the `.in` family minus government and education suffixes: 9,254 domains.
- **Chrome UX Report, India**: Google's public dataset of sites Indian Chrome users visit, queried for free on BigQuery (August 2026, 1,000,000 origins with a popularity rank). This is what catches Indian brands on `.com`.
  ```sql
  SELECT DISTINCT origin, experimental.popularity.rank AS source_rank
  FROM `chrome-ux-report.experimental.country`
  WHERE yyyymm = 202608 AND country_code = 'in'
  ```
- Normalised with `tldextract` and merged: 718,855 unique domains. All 20 domains of my hand-made test set ([`data/golden_set.csv`](data/golden_set.csv)) are in it.
</details>

<details>
<summary><b>2. DNS filter</b> (fast, touches no website)</summary>

Every custom-domain Shopify store points its DNS at Shopify. `sourcing/dns_check.py` resolves `domain` and `www.domain` with `dnspython` (30 lookups at a time on public resolvers), most popular candidates first. After the top 50,000 (about 12 minutes) I had 4,160 Shopify domains, four times the target, so I stopped there. Tranco-only domains produced zero hits, which is why they went last.
</details>

<details>
<summary><b>3. A polite fetcher</b> (used by everything that touches a website)</summary>

`utils/fetcher.py` checks robots.txt before every request, sends one request at a time per site with a pause in between, caps the whole crawl at 4 requests per second across all sites, pauses everyone when any site answers 429, retries with back-off, and caches every answer on disk so re-runs never hit a site twice. It identifies itself as `RivyouStoreResearchBot/1.0 (student assignment; polite, cached crawler)`.

The global cap exists because of a mistake I made first: being polite to each store isn't enough, because all Shopify stores share Shopify's servers and are rate-limited per visitor. My first extraction run, polite per site but about 40 requests per second overall, got throttled on nearly every page.
</details>

<details>
<summary><b>4. Is it really Shopify?</b></summary>

`verify/shopify_check.py` collects the four signals described above. 110 domains pointed at Shopify in DNS but nothing else agreed (abandoned or unconfigured stores); they're out. Tata CLiQ answers `/meta.json` with an HTML page and status 200, so the check insists on real JSON with a `myshopify_domain`. Fashion Nova blocks `/meta.json` but is still correctly recognised from its HTML and headers. 3,966 stores are live.
</details>

<details>
<summary><b>5. Is it really Indian?</b></summary>

`verify/india_score.py` reads country, currency and state from `/meta.json`, normalises old state names (Orissa, Pondicherry, Daman and Diu, …), keeps the stores that meet all three conditions (3,837), puts the doubtful ones in `edge_cases.csv`, and removes duplicates. 118 live Shopify stores in the list turned out to be registered outside India (55 in the US, 13 in the UK, 10 in Hong Kong, …).
</details>

<details>
<summary><b>6. Reading the seven fields</b></summary>

For each store I fetch the homepage, `/pages/contact`, `/policies/contact-information`, `/policies/privacy-policy`, `/products.json` and the About page (found by following the store's own menu link).

| Field | Where it comes from |
|---|---|
| Domain URL | the primary domain from `meta.json` |
| Emails | `mailto:` links and visible text; theme placeholders (`info@yourstore.com`), addresses shared by 4+ unrelated stores and malformed links removed |
| Phones | Google's `phonenumbers`, only valid Indian numbers, written as `+91…` |
| Socials | profile links per platform; share buttons, posts and Shopify's own links ignored; the one containing the brand name wins |
| Category | keyword rules over the store's product types, titles and tags (20 categories, plus Men/Women for apparel) |
| Tagline | `meta.json` description, then meta/og description, then the About page, then the homepage title; offer banners rejected |
| Logo | the Organization logo in the page's JSON-LD, else a header image marked as a logo; never the favicon |
| State | `meta.json`, cross-checked against the GST number when the site prints one (the first two digits are the state code) |

Two extra checks came out of looking at the data:

- **Category needed a second opinion.** Keyword rules can't read product names like "Air Force 1 Low", and one bed shop came out as Beauty because its beds were "cream". `extract/ai_category.py` runs a small local embedding model (`all-MiniLM-L6-v2`, CPU only, no API) over each product title and votes. A store keeps its category only when both methods agree. They agreed for 67% of stores; in the sample I checked by hand, every agreement was right.
- **State needed a cross-check.** The GST number confirmed the `meta.json` state for 500 stores and corrected two stores that had left Shopify's first dropdown option ("Andaman and Nicobar Islands") selected. 21 stores whose GST number disagreed are out.

Finally `verify/live_checks.py` checks that each logo URL returns an image (59 didn't) and each email domain can receive mail (25 couldn't).
</details>

<details>
<summary><b>7. Picking the 1,000</b></summary>

`build_final.py` applies 12 checks: all four Shopify signals, agreed category, the store's own email, its own +91 phone, at least one social profile, a logo, a tagline in its own words, a state consistent with its GST number, India proof on the site, a logo that loads, an email domain with mail servers, and a clean final audit. 1,614 stores pass.

They're ranked by a simple score: GST number on the site +3, email on the store's own domain +2, +1 per social profile, a clear category +1, 20+ products +1, an About page +1. Ties go to the more popular store. The top 1,000 are the result.

If I correct something by hand, it goes into [`data/manual_overrides.csv`](data/manual_overrides.csv) and the script applies it, so the fix survives every rebuild and is visible. There's one: linkcart.in (Link Locks Pvt. Ltd.) sells locks, not bags, even though both category methods said Bags & Luggage.

Everything that didn't make it is in [`data/all_stores.csv`](data/all_stores.csv) with a readable reason, e.g. *state conflict: meta.json says Delhi, GSTIN says Haryana*.
</details>

<details>
<summary><b>8. Checking it all again on the live sites</b></summary>

The extraction worked from pages saved days earlier, so `verify/audit.py` downloads every delivered store again and checks each field against what the site shows today. The per-store log with evidence is [`data/audit_log.csv`](data/audit_log.csv).

The first pass confirmed 946 stores. Most of the rest were Shopify rate-limiting the audit itself, so I re-ran those more slowly. What was left were real changes: happilo.com no longer appears to be on Shopify, truebrowns.com's store endpoint now returns 404, four stores had changed their tagline, nine had removed a phone number, and 14 emails were broken `mailto:` links. Stale stores were replaced by the next ones in the ranking (also audited), outdated numbers dropped, emails cleaned. The final pass confirmed 1,000 of 1,000.
</details>

---

## What's missing, and why

| Field | Missing across all 3,837 Indian stores | Missing in the final 1,000 | Usual reason |
|---|---:|---:|---|
| Email | 6.4% | 0% | contact form or WhatsApp chat only |
| Phone | 14.2% | 0% | many small D2C stores publish no number |
| Instagram | 16.5% | 0.5% | no profile linked |
| Facebook | 33.8% | 7.3% | |
| Twitter / X | 78.9% | 67.1% | rarely used by Indian D2C brands |
| LinkedIn | 81.9% | 69.2% | mostly larger companies |
| YouTube | 46.6% | 22.7% | |
| Logo | 4.2% | 0% | logo drawn as text/SVG, or an image not marked as a logo |
| Tagline | 7.6% | 0% | no description anywhere, or only an offer banner |
| State | 0% | 0% | required by the definition of Indian |
| Category ("Other") | 2.3% | 0% | products endpoint blocked or unrecognisable products |

The final 1,000 have no gaps in the required fields because I chose them that way. The 3,837 column is the honest picture of how well extraction works in general.

---

## False positives I ran into

- **DNS says Shopify, but there's no store.** 110 domains. Needing a second signal removed them.
- **Looks like Shopify, isn't.** Tata CLiQ serves HTML where Shopify serves JSON.
- **Shopify, but not Indian.** 118 stores registered abroad, including brands that ship to India. The domain name is never used as proof.
- **Theme leftovers.** 43 placeholder emails from theme templates; one phone number shared by 14 "deals" stores; a dummy toll-free number on 7.
- **Wrong state from a default dropdown.** 99store.biz claimed Andaman and Nicobar; its GST number says Delhi.
- **Wrong category.** Caught by requiring two methods to agree, plus one manual fix.
- **Offer text posing as a tagline.** "Year-End Sale is Live! Extra 10% Off".
- **Things that changed after the crawl.** Dead logos, expired email domains, and two stores that left or broke Shopify, caught by the live checks and the audit.

---

## Limits, and what I'd do at 10× or 100×

This run covers custom-domain stores popular enough to show up in Chrome's data. I only DNS-checked the top 50,000 of 718,855 candidates, and stores that live only on `*.myshopify.com` are mostly invisible to these sources. The state is what the owner entered in Shopify, confirmed by a GST number for 23.5% of the final list; for a few brands it may be the registered office rather than the warehouse. I skipped WHOIS because `.in` records are mostly redacted and the store settings plus GST number are more reliable. And websites change: between crawl and audit, about 1–2% of stores had changed something.

At a bigger scale, a few things would break first:

- **Rate limits.** Shopify limits per visitor across all its stores. At 4 requests per second, 1,000 stores take about half an hour; 100,000 would take about two days from one machine. I'd spread the work over time, fetch only the pages each field needs, and re-check with conditional requests.
- **Storage.** One JSON file per cached page (about 10 GB here). On Windows, antivirus scanning made reading the cache slower than downloading it. At scale I'd use WARC files or SQLite.
- **DNS.** Public resolvers throttle around 30 lookups per second, so 700k domains is about 7 hours. A local caching resolver would fix that.
- **Discovery.** I'd add sources that list Shopify stores directly: Common Crawl's URL index for pages loading `cdn.shopify.com`, certificate transparency logs for `*.myshopify.com`, and reverse-IP data for Shopify's address range.

With more time I'd DNS-check all 718k candidates, train the category model on a few hundred hand-labelled stores, hand-check a larger sample, and wrap the steps in a single `pipeline.py`.

---

## Running it

Python 3.11+, about 15 GB free disk for the page cache, and a free Google Cloud account for the one BigQuery query.

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux / macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Run everything from the project root, in this order:

```bash
python -m sourcing.tranco                  # ~1 min
# run the SQL above on BigQuery, save as data/raw/crux_in.csv
python -m sourcing.crux
python -m sourcing.merge
python -m sourcing.dns_check --limit 50000 # ~12 min   (--golden to test)
python -m verify.shopify_check             # ~35 min   (--golden to test)
python -m verify.india_score               # seconds
python -m extract.run_extract              # ~2.5 h fetch + ~15 min parse  (--limit 30 for a trial)
python -m extract.refine                   # ~5 min
python -m extract.ai_category              # ~7 min, downloads a 90 MB model once
python -m verify.live_checks               # ~8 min
python build_final.py                      # seconds -> output/stores.csv, output/stores.json
python -m verify.audit                     # first run ~2.5 h, then only what isn't confirmed yet
python build_final.py                      # repeat audit + build until it prints "all done"
```

A full run from scratch takes about 6 to 7 hours, nearly all of it deliberately slow waiting on websites. Every step caches or resumes, so it can be stopped and restarted. The page cache, raw downloads and the three large candidate lists aren't committed; the steps above recreate them.

<details>
<summary><b>Where things are</b></summary>

```
output/          the result: stores.csv, stores.json (+ README with every column)
data/            what each step produced (see data/README.md)
reports/         funnel.md and audit.md, both generated by the code
sourcing/        tranco.py, crux.py, merge.py, dns_check.py
utils/           fetcher.py, clean_cache.py
verify/          shopify_check.py, india_score.py, live_checks.py, audit.py
extract/         run_extract.py, one file per field, refine.py, ai_category.py
build_final.py   checks, ranking, final files
```

Output columns: `rank, store_name, domain_url, emails, phones, instagram, facebook, twitter, linkedin, youtube, category, tagline, tagline_source, logo_url, state, city, gstin, india_evidence, quality_score`. Multiple emails and phones are separated by `; ` in the CSV and are lists in the JSON. `twitter` holds Twitter or X links. Phones are in `+91…` form, including toll-free 1800 numbers.
</details>

---

## Time spent

About 23 hours over six days, 25 to 30 September 2026, of which roughly 6 hours were unattended runs.

| Day | Hours | Work |
|---|---:|---|
| 25 Sep | ~2 | read the brief, planned, set up the environment |
| 26 Sep | ~3 | golden test set by hand, Tranco, CrUX on BigQuery, merge |
| 27 Sep | ~4 | DNS filter, fetcher, Shopify verification, India scoring |
| 28 Sep | ~6.5 | field extraction, working out Shopify's rate limits, polite re-crawl |
| 29 Sep | ~6.5 | clean-up, category check, selection and ranking, live checks, audit |
| 30 Sep | ~1 | audit re-checks, write-up |

No paid tools or APIs were used.
