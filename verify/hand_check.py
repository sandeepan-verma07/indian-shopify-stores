"""Part 8: hand-check a random sample of the final 1,000 - our own spot-check before Rivyou does theirs.

  python -m verify.hand_check --make     # 50 random stores -> data/hand_check.csv (open in Excel)
  python -m verify.hand_check --score    # after filling it in -> accuracy per field + reports/hand_check.md

How to fill it in (one row per store, ~1 minute each):
  open domain_url (and meta_json_url) in the browser, then in each ok_ column type
    Y  = correct            N = wrong (write what's wrong in `notes`)
    -  = can't tell / not applicable
  ok_shopify   meta_json_url opens and shows JSON with "myshopify_domain"  (or page source has cdn.shopify.com)
  ok_indian    meta.json "country":"IN" + prices in ₹ + an Indian address/phone on the site
  ok_email     the email appears on the site (footer / contact page / policies) and belongs to this store
  ok_phone     the phone appears on the site and belongs to this store
  ok_social    the instagram link opens this store's profile
  ok_logo      logo_url opens the store's logo (the one in the header, not the tiny browser-tab icon)
  ok_tagline   the tagline text is on the site in these words (homepage / About page / page description)
  ok_category  the category fits what the store mostly sells
  ok_state     the state matches the address / GST number on the site
Save as CSV (Excel: File > Save As > "CSV UTF-8").
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

STORES_FILE = Path("data/stores.csv")
SHEET_FILE = Path("data/hand_check.csv")
REPORT_FILE = Path("reports/hand_check.md")
SAMPLE_SIZE = 50
SEED = 2026                  # fixed, so anyone rerunning --make gets the same 50 stores
CHECKS = ["ok_shopify", "ok_indian", "ok_email", "ok_phone", "ok_social",
          "ok_logo", "ok_tagline", "ok_category", "ok_state"]
YES, NO = {"y", "yes", "1", "true", "ok"}, {"n", "no", "0", "false", "x"}


def first(cell, n: int = 1) -> str:
    """'a; b; c' -> 'a' (keeps the sheet short; the full list is in stores.csv)."""
    return "; ".join(str(cell).split("; ")[:n]) if str(cell) else ""


def make(force: bool):
    if SHEET_FILE.exists() and not force:
        sys.exit(f"{SHEET_FILE} already exists - it may hold your checks. Use --make --force to overwrite.")
    try:
        stores = pd.read_csv(STORES_FILE, encoding="utf-8-sig").fillna("")
    except UnicodeDecodeError:
        sys.exit(f"{STORES_FILE} is not UTF-8 any more (was it saved from Excel?). "
                 "Rebuild it with: python build_final.py")
    sample = stores.sample(SAMPLE_SIZE, random_state=SEED).sort_values("rank")
    sheet = pd.DataFrame({
        "rank": sample["rank"],
        "domain_url": sample["domain_url"],
        "meta_json_url": sample["domain_url"] + "/meta.json",
        "store_name": sample["store_name"],
        "email": sample["emails"].map(first),
        "phone": sample["phones"].map(first),
        "instagram": sample["instagram"],
        "logo_url": sample["logo_url"],
        "tagline": sample["tagline"].str[:150],
        "category": sample["category"],
        "state": sample["state"] + " (" + sample["city"] + ")",
        **{c: "" for c in CHECKS},
        "notes": "",
    })
    sheet.to_csv(SHEET_FILE, index=False, encoding="utf-8-sig")    # -sig: Excel shows ₹ and Indian names correctly
    print(f"Saved {SHEET_FILE} ({len(sheet)} stores, seed {SEED}). Open it in Excel and fill the ok_ columns (see top of this file).")


def read_sheet() -> pd.DataFrame:
    for encoding in ("utf-8-sig", "cp1252"):                       # Excel may save either way
        try:
            return pd.read_csv(SHEET_FILE, encoding=encoding, dtype=str).fillna("")
        except UnicodeDecodeError:
            continue
    sys.exit(f"Could not read {SHEET_FILE} - save it from Excel as 'CSV UTF-8'.")


def verdict(cell: str) -> str:
    v = cell.strip().lower()
    return "Y" if v in YES else "N" if v in NO else "-" if v else ""


def score():
    sheet = read_sheet()
    marks = sheet[CHECKS].apply(lambda col: col.map(verdict))
    unchecked = (marks == "").all(axis=1).sum()

    lines = ["# Hand-check of the final 1,000", "",
             f"{len(sheet)} stores picked at random (seed {SEED}) from `data/stores.csv` and checked by hand in a browser.", "",
             "| Field | Correct | Wrong | Can't tell | Accuracy |", "|---|---:|---:|---:|---:|"]
    for c in CHECKS:
        y, n, na = (marks[c] == "Y").sum(), (marks[c] == "N").sum(), (marks[c] == "-").sum()
        acc = f"{y / (y + n):.0%}" if y + n else "-"
        lines.append(f"| {c.removeprefix('ok_')} | {y} | {n} | {na} | {acc} |")
    all_ok = ((marks == "Y") | (marks == "-")).all(axis=1) & (marks == "Y").any(axis=1)
    lines += ["", f"**Stores fully correct: {all_ok.sum()} / {len(sheet) - unchecked}** (unchecked rows: {unchecked})", ""]

    wrong = sheet[(marks == "N").any(axis=1)]
    if len(wrong):
        lines += ["## What was wrong", "", "| Store | Wrong fields | Notes |", "|---|---|---|"]
        for i, row in wrong.iterrows():
            fields = ", ".join(c.removeprefix("ok_") for c in CHECKS if marks.loc[i, c] == "N")
            lines.append(f"| {row['domain_url']} | {fields} | {row['notes']} |")

    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nSaved {REPORT_FILE}")


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--make", action="store_true", help="create the sheet with 50 random stores")
    mode.add_argument("--score", action="store_true", help="count the Y/N marks in the filled sheet")
    parser.add_argument("--force", action="store_true", help="with --make: overwrite an existing sheet")
    args = parser.parse_args()
    make(args.force) if args.make else score()


if __name__ == "__main__":
    main()
