"""Step 6c: tagline / description in the store's own words."""
import html as html_lib

import pandas as pd

from extract.html_text import parse

MAX_CHARS = 300


def _clean(text) -> str:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    text = " ".join(html_lib.unescape(str(text)).split())     # "&amp;" -> "&"
    return text[:MAX_CHARS]


def _just_the_name(text: str, store_name: str) -> bool:
    """'HealthyHey' is a name, not a tagline."""
    squash = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())
    return len(text) < 40 and squash(text) in squash(f"{store_name} {store_name}") or len(text.split()) < 3


def find_tagline(meta_description, html: str, store_name: str = "") -> tuple[str, str]:
    """Returns (tagline, source). Order: meta.json description -> <meta name=description> -> og:description."""
    tree = parse(html)
    candidates = [("meta_json", meta_description)]
    for source, selector in (("meta_description", 'meta[name="description"]'),
                             ("og_description", 'meta[property="og:description"]')):
        node = tree.css_first(selector)
        candidates.append((source, node.attributes.get("content") if node else ""))

    for source, raw in candidates:
        text = _clean(raw)
        if text and not _just_the_name(text, store_name):
            return text, source
    return "", ""
