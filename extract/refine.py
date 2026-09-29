"""Step 6 refine: clean and improve the extracted fields, one part at a time.

Reads data/stores_enriched.csv (from run_extract.py), writes data/stores_refined.csv.
Earlier files are never changed.

  Part 1 - contacts: drop placeholder emails left in store templates, flag contacts shared by many stores
  Part 2 - state: one final `state`, cross-checked against the GST number's state code
  Part 3 - tagline: fill empty taglines from the store's About page / homepage title (their own words only)
"""
import html as html_lib
import re
from collections import Counter
from pathlib import Path

import pandas as pd

from extract.html_text import parse
from extract.run_extract import about_url
from extract.tagline import _just_the_name
from utils.fetcher import read_cache
from verify.india_score import STATE_ALIASES

IN_FILE = Path("data/stores_enriched.csv")
OUT_FILE = Path("data/stores_refined.csv")

# ---------- Part 1: contacts ----------
# example addresses that some Shopify themes ship with and store owners never replaced
PLACEHOLDER_EMAIL = re.compile(
    r"yourstore|yourbrand|yourcompany|yourshop|yourdomain|storename|brandname|"
    r"@company\.com$|@example\.|@adress\.com$|@email\.com$|@domain\.com$|^test@|^abc@|^xyz@"
)
SHARED_LIMIT = 4        # the same email/phone on this many different stores = not the store's own


def split(cell: str) -> list[str]:
    return [x for x in str(cell).split("; ") if x]


def clean_contacts(df: pd.DataFrame) -> pd.DataFrame:
    emails = df["emails"].apply(split)
    removed = emails.apply(lambda lst: [e for e in lst if PLACEHOLDER_EMAIL.search(e)])
    emails = emails.apply(lambda lst: [e for e in lst if not PLACEHOLDER_EMAIL.search(e)])
    phones = df["phones"].apply(split)

    # how many different stores show each email / phone
    seen = Counter(c for lst in emails for c in set(lst)) + Counter(c for lst in phones for c in set(lst))
    shared = {contact for contact, n in seen.items() if n >= SHARED_LIMIT}

    df["emails"] = emails.apply("; ".join)
    df["placeholder_emails_removed"] = removed.apply("; ".join)
    df["shared_contacts"] = [
        "; ".join(c for c in e + p if c in shared) for e, p in zip(emails, phones)
    ]
    df["own_email"] = emails.apply(lambda lst: next((e for e in lst if e not in shared), ""))
    df["own_phone"] = phones.apply(lambda lst: next((p for p in lst if p not in shared), ""))

    print("Part 1 - contacts")
    print(f"  placeholder emails removed: {removed.str.len().sum()} (from {(removed.str.len() > 0).sum()} stores)")
    print(f"  contacts shared by {SHARED_LIMIT}+ stores: {len(shared)} -> flagged on {(df['shared_contacts'] != '').sum()} stores")
    print(f"  stores with an own (not shared) email: {(df['own_email'] != '').sum():,} | own phone: {(df['own_phone'] != '').sum():,}")
    return df


# ---------- Part 2: state ----------
# Shopify's state dropdown for India starts with this entry; a store that never picked
# its state can end up with it, so we don't trust it when the GST number says otherwise.
DROPDOWN_DEFAULT = "andaman and nicobar islands"


def same_state(a: str, b: str) -> bool:
    norm = lambda s: STATE_ALIASES.get(s.strip().lower(), s.strip().lower())
    return norm(a) == norm(b)


def decide_state(row) -> tuple[str, str, str]:
    """Returns (state, where it came from, conflict note)."""
    meta, gst = row["meta_province"], row["gstin_state"]
    if not gst or same_state(meta, gst):
        return meta, "meta.json" + (" + GSTIN" if gst else ""), ""
    if meta.strip().lower() == DROPDOWN_DEFAULT:
        return gst, "GSTIN (meta.json had Shopify's default first option)", f"meta.json said {meta}"
    return meta, "meta.json", f"meta.json says {meta}, GSTIN says {gst}"


def clean_state(df: pd.DataFrame) -> pd.DataFrame:
    decided = df.apply(decide_state, axis=1, result_type="expand")
    df["state"], df["state_source"], df["state_conflict"] = decided[0], decided[1], decided[2]

    print("Part 2 - state")
    print(f"  state filled: {(df['state'] != '').sum():,}")
    print(f"  confirmed by GSTIN on the site: {df['state_source'].str.contains('GSTIN').sum():,}")
    print(f"  corrected from Shopify's default option: {df['state_source'].str.startswith('GSTIN (').sum()}")
    print(f"  conflicts kept + flagged: {(df['state_conflict'].str.startswith('meta.json says')).sum()}")
    return df


# ---------- Part 3: taglines ----------
# Only for stores whose tagline is still empty. Every tagline is copied from the store's own
# pages - never written by us. If nothing good is found, it stays empty.
MAX_CHARS = 300
MIN_WORDS = 8            # an About-page sentence shorter than this is usually a heading, not a description
JUNK_TEXT = re.compile(
    r"page you're looking for|doesn.t exist|cookie|newsletter|subscribe|add to cart|your cart|"
    r"\bgst\b|\bgstin\b|all rights reserved|sign in|log in|whatsapp|shipping available|free shipping|"
    r"\d{5}\s?\d{5}", re.I)                      # announcement bars and phone numbers are not descriptions
CUT_AT = re.compile(r"\s(address|contact us|call us|email us)\s*:", re.I)   # stop before contact details
REMOVE = "script, style, noscript, template, header, footer, nav, form"


def _tidy(text: str) -> str:
    """Unescape, squeeze spaces, stop before contact details, keep whole sentences up to 300 chars."""
    text = " ".join(html_lib.unescape(str(text)).split())
    text = CUT_AT.split(text)[0].strip()
    if len(text) <= MAX_CHARS:
        return text
    kept = ""
    for sentence in re.split(r"(?<![A-Z][.!?])(?<=[.!?])\s+", text):   # not after an initial ("S. Seetha")
        if len(kept) + len(sentence) + 1 > MAX_CHARS:
            break
        kept = f"{kept} {sentence}".strip()
    if len(kept) < 80:                        # sentences glued together ("Wear.We sell") -> cut at a word
        kept = text[:MAX_CHARS].rsplit(" ", 1)[0]
    return kept


def _usable(text: str, store_name: str) -> bool:
    shouting = sum(c.isupper() for c in text) > 0.6 * sum(c.isalpha() for c in text)   # ALL-CAPS banner text
    return (not shouting and len(text.split()) >= MIN_WORDS
            and not JUNK_TEXT.search(text) and not _just_the_name(text, store_name))


def _html(url: str) -> str:
    page = read_cache(url) if url else None
    return page.text if page and page.status == 200 else ""


def about_tagline(about_html: str, store_name: str) -> tuple[str, str]:
    """About page: its meta description, then og:description, then its first real paragraph."""
    tree = parse(about_html)
    for source, selector in (("about_meta_description", 'meta[name="description"]'),
                             ("about_og_description", 'meta[property="og:description"]')):
        node = tree.css_first(selector)
        text = _tidy(node.attributes.get("content") or "") if node else ""
        if _usable(text, store_name):
            return text, source
    for node in tree.css(REMOVE):             # drop menu, header, footer, forms before reading paragraphs
        node.decompose()
    for p in tree.css("p"):
        text = _tidy(p.text(separator=" "))
        if _usable(text, store_name):
            return text, "about_paragraph"
    return "", ""


def title_tagline(home_html: str, store_name: str) -> tuple[str, str]:
    """Homepage <title> minus the brand: 'Alpha Cases — Where Tech Meets Fashion' -> 'Where Tech Meets Fashion'."""
    node = parse(home_html).css_first("title")
    title = " ".join(html_lib.unescape(node.text()).split()) if node else ""
    for part in re.split(r"\s[|\-–—:]\s", title):
        part = part.strip(" ,")
        if len(part.split()) >= 3 and not _just_the_name(part, store_name) and not JUNK_TEXT.search(part):
            return part[:MAX_CHARS], "home_title"
    return "", ""


def fill_tagline(row) -> tuple[str, str]:
    if row["tagline"]:                        # already has one from Step 6 -> keep it as it is
        return row["tagline"], row["tagline_source"]
    home = _html(f"https://{row['domain']}/")
    name = str(row["meta_name"])
    text, source = about_tagline(_html(about_url(row["domain"], home)), name)
    return (text, source) if text else title_tagline(home, name)


def clean_tagline(df: pd.DataFrame) -> pd.DataFrame:
    before = (df["tagline"] != "").sum()
    print(f"Part 3 - taglines: reading cached pages for {len(df) - before:,} stores (a few minutes on Windows)...")
    filled = df.apply(fill_tagline, axis=1, result_type="expand")
    df["tagline"], df["tagline_source"] = filled[0], filled[1]

    print(f"  tagline before: {before:,} | after: {(df['tagline'] != '').sum():,} | still empty: {(df['tagline'] == '').sum():,}")
    new = df["tagline_source"].str.startswith(("about_", "home_title"))
    print("  new ones came from:", df.loc[new, "tagline_source"].value_counts().to_dict())
    return df


def main():
    df = pd.read_csv(IN_FILE, low_memory=False).fillna("")
    df = clean_contacts(df)
    df = clean_state(df)
    df = clean_tagline(df)
    df.to_csv(OUT_FILE, index=False)
    print(f"Saved {OUT_FILE} ({len(df):,} stores)")


if __name__ == "__main__":
    main()
