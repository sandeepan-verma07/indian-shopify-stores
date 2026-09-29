"""Step 7: pick the best 1,000 stores and write the report that shows how we got there.

Reads (nothing here downloads anything):
  data/stores_refined.csv     all 3,837 high-confidence Indian Shopify stores with their fields (extract/refine.py)
  data/ai_categories.csv      keyword vs AI category (extract/ai_category.py)
  data/live_checks.csv        optional - logo loads / email domain has MX (added in Part 6)
  earlier step files          only to count the funnel (candidates -> DNS -> Shopify -> Indian)

Writes:
  data/all_stores.csv         every store, every field, one pass/fail column per check + why it was left out
  data/stores.csv / .json     the final 1,000, ranked (the deliverable)
  reports/funnel.md           the whole funnel, each check, missing-field rates, examples - generated, so numbers always match

  python build_final.py
"""
import json
import re
from pathlib import Path

import pandas as pd

DATA, REPORTS = Path("data"), Path("reports")
FINAL_SIZE = 1000
SOCIALS = ["instagram", "facebook", "twitter", "linkedin", "youtube"]
FREE_MAIL = {"gmail.com", "yahoo.com", "yahoo.in", "yahoo.co.in", "outlook.com", "hotmail.com",
             "rediffmail.com", "icloud.com", "live.com", "protonmail.com", "zoho.com", "aol.com"}

# offer text / banners that are not a description of the store (found while checking Part 3)
PROMO_TEXT = re.compile(
    r"\d+\s?%\s?off|\buse code\b|\bcoupon\b|discount code|\bsale is live\b|limited time offer|\bflat \d|"
    r"your inbox|billed in|bulk orders|lorem|(?:shop for|orders above|purchase of)\s?(?:₹|rs)|"
    r"sign up (?:today|and|for)|\bcode\s*:", re.I)
TITLE_JUNK = re.compile(r"welcome|official|online store|home page|\bshop\b", re.I)


def split(cell) -> list[str]:
    return [x for x in str(cell).split("; ") if x]


def rows(path: Path):
    """Number of rows in a CSV, or None if the file isn't there (big intermediates are not in the repo)."""
    return len(pd.read_csv(path, usecols=[0])) if path.exists() else None


# ---------- checks ----------
def title_tagline_ok(tagline: str, store_name: str) -> bool:
    """A homepage-title tagline must still say something once the brand's own words are removed."""
    squash = "".join(ch for ch in store_name.lower() if ch.isalnum())
    rest = [w for w in re.findall(r"[A-Za-z]+", tagline) if not (len(w) >= 3 and w.lower() in squash)]
    shouting = sum(c.isupper() for c in tagline) > 0.6 * sum(c.isalpha() for c in tagline)
    return len(rest) >= 4 and not shouting and not TITLE_JUNK.search(tagline)


def tagline_ok(row) -> bool:
    text = row["tagline"]
    if not text or PROMO_TEXT.search(text):
        return False
    return row["tagline_source"] != "home_title" or title_tagline_ok(text, str(row["meta_name"]))


def own_domain_email(email: str, domain: str) -> bool:
    """support@chicco.in for chicco.in -> True; chiccoindia@gmail.com -> False."""
    host = email.split("@")[-1].lower()
    brand = domain.lower().removeprefix("www.").split(".")[0]
    return bool(email) and host not in FREE_MAIL and (host == domain or brand in host.split("."))


# name -> (what it means, how it's computed). Order = order in the funnel report.
CHECKS = {
    "shopify_4_signals": ("all 4 Shopify signals (DNS, meta.json, HTML, headers)", lambda d: d["signal_count"] == 4),
    "category_agreed": ("keyword category confirmed by the AI model", lambda d: d["category_agreed"] == True),
    "own_email": ("store's own email (no placeholder, not shared by 4+ stores)", lambda d: d["own_email"] != ""),
    "own_phone": ("store's own valid +91 phone (not shared)", lambda d: d["own_phone"] != ""),
    "social": ("at least one social profile", lambda d: d[SOCIALS].ne("").any(axis=1)),
    "logo": ("logo found (not the favicon)", lambda d: d["logo_url"] != ""),
    "tagline": ("tagline in the store's own words, not an offer/banner", lambda d: d.apply(tagline_ok, axis=1)),
    "state_consistent": ("meta.json state does not contradict the GST number", lambda d: ~d["state_conflict"].str.startswith("meta.json says")),
    "india_proof_on_site": ("India proof on the site itself (+91 phone / GSTIN / PIN code)", lambda d: d["independent_india_evidence"] != ""),
}
LIVE_CHECKS = {   # only used once data/live_checks.csv exists (Part 6)
    "logo_loads": ("logo URL returns an image", lambda d: d["logo_loads"] == True),
    "email_domain_mx": ("email domain can receive mail (MX record)", lambda d: d["email_domain_mx"] == True),
}


def exclusion_detail(row, check: str) -> str:
    """Human-readable reason, e.g. 'category disagreement: keywords Apparel & Fashion, AI Footwear'."""
    if check == "category_agreed":
        return f"category disagreement: keywords {row['category']}, AI {row['ai_category'] or 'nothing'}"
    if check == "state_consistent":
        return f"state conflict: {row['state_conflict']}"
    if check == "tagline":
        return f"tagline rejected: {row['tagline'][:80]!r}" if row["tagline"] else "no tagline"
    if check == "own_email" and row["shared_contacts"]:
        return f"no own email (shared: {row['shared_contacts']})"
    return f"failed: {ALL_CHECKS[check][0]}"


ALL_CHECKS = dict(CHECKS)


# ---------- ranking ----------
def quality_score(d: pd.DataFrame) -> pd.Series:
    """Every store here already passed all checks; points reward extra certainty and richer data."""
    return (3 * (d["gstin"] != "")                                                   # strongest India proof
            + 2 * d.apply(lambda r: own_domain_email(r["own_email"], r["domain"]), axis=1)
            + d[SOCIALS].ne("").sum(axis=1)                                          # 1 per social profile
            + (d["ai_vote_share"] >= 0.6)                                            # clearly one kind of store
            + (d["meta_published_products_count"] >= 20)                             # a real catalogue
            + (d["has_about_page"].astype(str) == "True"))                           # tells its own story


# ---------- report ----------
def pct(n, total):
    return f"{n:,} ({n / total:.1%})" if total else "0"


def funnel_counts() -> list[tuple[str, object, str]]:
    verified = pd.read_csv(DATA / "shopify_verified.csv", low_memory=False)
    live = verified[verified["is_shopify"] & (verified["store_state"] == "live")]
    return [
        ("Candidate domains (Tranco .in + CrUX India)", rows(DATA / "candidates_raw.csv"), "sourcing/tranco.py, crux.py, merge.py"),
        ("DNS-checked (most promising first)", rows(DATA / "dns_results.csv"), "sourcing/dns_check.py"),
        ("Point to Shopify in DNS", rows(DATA / "candidates_dns.csv"), "sourcing/dns_check.py"),
        ("Confirmed Shopify (2+ of 4 signals)", int(verified["is_shopify"].sum()), "verify/shopify_check.py"),
        ("Live storefront", len(live), "verify/shopify_check.py"),
        ("meta.json country = India", int((live["meta_country"] == "IN").sum()), "verify/shopify_check.py"),
        ("High-confidence Indian (IN + INR + Indian state, deduplicated)", rows(DATA / "indian_stores.csv"), "verify/india_score.py"),
    ]


def write_report(df: pd.DataFrame, checks: dict, final: pd.DataFrame):
    total = len(df)
    lines = ["# How we got to the final 1,000", "",
             "_Generated by `build_final.py` from the data files - rerun it and these numbers update._", "",
             "## 1. Finding Indian Shopify stores", "", "| Stage | Stores | Code |", "|---|---:|---|"]
    for stage, n, code in funnel_counts():
        lines.append(f"| {stage} | {n:,} | `{code}` |" if n is not None else f"| {stage} | (file not in repo) | `{code}` |")
    edge = rows(DATA / "edge_cases.csv")
    lines += ["", f"Doubtful stores ({edge} - e.g. USD pricing or missing state) are kept apart in `data/edge_cases.csv`.", "",
              "## 2. Quality checks on the high-confidence stores", "",
              "Each check is applied on top of the ones above it. A store must pass all of them to be considered.", "",
              "| Check | Fails on its own | Still passing |", "|---|---:|---:|", f"| (start) | | {total:,} |"]
    passing = pd.Series(True, index=df.index)
    for name, (meaning, _) in checks.items():
        ok = df[f"chk_{name}"]
        passing &= ok
        if name in LIVE_CHECKS:      # live checks only ran on the stores that passed everything above
            checked = df["live_checked"]
            lines.append(f"| {meaning} (live, on the {checked.sum():,} candidates) | {(~ok & checked).sum():,} | {passing.sum():,} |")
        else:
            lines.append(f"| {meaning} | {(~ok).sum():,} | {passing.sum():,} |")
    lines += ["", f"**{passing.sum():,} stores pass every check.** They are ranked by a quality score and the top "
              f"{FINAL_SIZE:,} become `data/stores.csv` / `data/stores.json`.", "",
              "Quality score (max 13): GSTIN on site +3 · email on the store's own domain +2 · +1 per social profile · "
              "AI vote share >= 60% +1 · 20+ products +1 · About page +1. Ties: more popular first (CrUX India rank), then AI vote share.", ""]
    if len(final):
        lines.append(f"Score of the last store that made the cut: {final['quality_score'].min()} "
                     f"(passing stores left out: {passing.sum() - len(final):,}).")

    lines += ["", "## 3. How often each field was missing", "",
              f"| Field | Missing in all {total:,} Indian stores | Missing in final {len(final):,} |", "|---|---:|---:|"]
    fields = {"Email": "emails", "Phone": "phones", **{s.title() if s != "linkedin" else "LinkedIn": s for s in SOCIALS},
              "Logo": "logo_url", "Tagline": "tagline", "State": "state", "GSTIN": "gstin"}
    for label, col in fields.items():
        lines.append(f"| {label} | {pct((df[col] == '').sum(), total)} | {pct((final[col] == '').sum(), len(final))} |")
    lines.append(f"| Category (\"Other\") | {pct((df['category'] == 'Other').sum(), total)} | "
                 f"{pct((final['category'] == 'Other').sum(), len(final))} |")

    lines += ["", "## 4. Why stores were left out (first failed check, with examples)", "", "| Reason | Stores | Examples |", "|---|---:|---|"]
    out = df[df["excluded_reason"] != ""]
    first = out["first_failed_check"].value_counts()
    for name, n in first.items():
        ex = out[out["first_failed_check"] == name].head(3)
        examples = "<br>".join(f"{d}: {r}" for d, r in zip(ex["domain"], ex["excluded_reason"]))
        lines.append(f"| {checks[name][0]} | {n:,} | {examples} |")

    lines += ["", "## 5. Final 1,000 at a glance", "", "**By category**", "", "| Category | Stores |", "|---|---:|"]
    lines += [f"| {c} | {n} |" for c, n in final["category"].value_counts().items()]
    lines += ["", "**By state (top 12)**", "", "| State | Stores |", "|---|---:|"]
    lines += [f"| {s} | {n} |" for s, n in final["state"].value_counts().head(12).items()]

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "funnel.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------- main ----------
def main():
    df = pd.read_csv(DATA / "stores_refined.csv", low_memory=False).fillna("")
    ai = pd.read_csv(DATA / "ai_categories.csv").fillna("")
    df = df.merge(ai[["domain", "ai_category", "ai_vote_share", "ai_runner_up", "category_agreed"]], on="domain", how="left")
    df["ai_vote_share"] = pd.to_numeric(df["ai_vote_share"], errors="coerce").fillna(0)

    checks = dict(CHECKS)
    live_file = DATA / "live_checks.csv"
    if live_file.exists():
        df = df.merge(pd.read_csv(live_file), on="domain", how="left")
        df["live_checked"] = df["logo_loads"].notna()
        checks.update(LIVE_CHECKS)
    ALL_CHECKS.update(checks)

    raw = DATA / "candidates_raw.csv"    # popularity, only used to break ties (file is big, not in the repo)
    if raw.exists():
        ranks = pd.read_csv(raw, usecols=["domain", "crux_rank"])
        df = df.merge(ranks, on="domain", how="left")
    df["crux_rank"] = pd.to_numeric(df.get("crux_rank"), errors="coerce").fillna(10_000_000)

    # one pass/fail column per check + the first reason a store was left out
    for name, (_, test) in checks.items():
        df[f"chk_{name}"] = test(df).astype(bool)
    chk_cols = [f"chk_{n}" for n in checks]
    df["passes_all_checks"] = df[chk_cols].all(axis=1)
    df["first_failed_check"] = df.apply(lambda r: next((n for n in checks if not r[f"chk_{n}"]), ""), axis=1)
    df["excluded_reason"] = df.apply(lambda r: exclusion_detail(r, r["first_failed_check"]) if r["first_failed_check"] else "", axis=1)

    # final contacts: every email/phone the store shows, minus placeholders (already gone) and shared ones
    shared = df["shared_contacts"].apply(lambda c: set(split(c)))
    df["final_emails"] = ["; ".join(e for e in split(es) if e not in s) for es, s in zip(df["emails"], shared)]
    df["final_phones"] = ["; ".join(p for p in split(ps) if p not in s) for ps, s in zip(df["phones"], shared)]

    df["quality_score"] = 0
    good = df["passes_all_checks"]
    df.loc[good, "quality_score"] = quality_score(df[good])
    ranked = df[good].sort_values(["quality_score", "crux_rank", "ai_vote_share", "domain"],
                                  ascending=[False, True, False, True])
    final = ranked.head(FINAL_SIZE).copy()
    final.insert(0, "rank", range(1, len(final) + 1))
    df["in_final_1000"] = df["domain"].isin(final["domain"])

    deliverable = pd.DataFrame({
        "rank": final["rank"], "store_name": final["meta_name"], "domain_url": "https://" + final["domain"],
        "emails": final["final_emails"], "phones": final["final_phones"],
        **{s: final[s] for s in SOCIALS},
        "category": final["category"], "tagline": final["tagline"], "tagline_source": final["tagline_source"],
        "logo_url": final["logo_url"], "state": final["state"], "city": final["meta_city"],
        "gstin": final["gstin"], "india_evidence": final["india_evidence"] + "; " + final["independent_india_evidence"],
        "quality_score": final["quality_score"],
    })
    deliverable.to_csv(DATA / "stores.csv", index=False)
    records = deliverable.to_dict("records")
    for r in records:                               # in JSON, contacts are real lists
        r["emails"], r["phones"] = split(r["emails"]), split(r["phones"])
    (DATA / "stores.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    df.to_csv(DATA / "all_stores.csv", index=False)
    write_report(df, checks, final)

    print(f"Indian stores: {len(df):,} | pass all {len(checks)} checks: {good.sum():,} | final: {len(final):,}")
    print(f"Saved data/stores.csv, data/stores.json, data/all_stores.csv, reports/funnel.md")


if __name__ == "__main__":
    main()
