"""Small shared helpers for reading HTML."""
from functools import lru_cache
from urllib.parse import urljoin

from selectolax.parser import HTMLParser


def parse(html: str) -> HTMLParser:
    return HTMLParser(html or "")


@lru_cache(maxsize=32)
def visible_text(html: str) -> str:
    """Text a human would see: drops <script>, <style>, <noscript> (they hold IDs and prices, not contacts)."""
    tree = parse(html)
    for node in tree.css("script, style, noscript, template"):
        node.decompose()
    body = tree.body or tree.root
    return " ".join(body.text(separator=" ").split()) if body else ""


def absolute_url(url: str, base: str) -> str:
    """'//cdn.shopify.com/x.png' or '/cdn/x.png' -> full https URL."""
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    return urljoin(base, url)
