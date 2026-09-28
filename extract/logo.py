"""Step 6d: the brand logo (never the favicon)."""
import json

from extract.html_text import absolute_url, parse


def _logo_from_json_ld(tree) -> str:
    """Shopify themes publish Organization data for Google, often with the logo URL."""
    for script in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text())
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in items:
            if isinstance(item, dict) and item.get("logo"):
                logo = item["logo"]
                return logo.get("url", "") if isinstance(logo, dict) else str(logo)
    return ""


def _logo_from_header(tree) -> str:
    """Look for an <img> whose class / alt / src mentions 'logo' — header first, then anywhere."""
    for selector in ("header img", "img"):
        for img in tree.css(selector):
            attrs = img.attributes
            hint = " ".join(str(attrs.get(k) or "") for k in ("class", "alt", "src", "id")).lower()
            if "logo" not in hint:
                continue
            src = attrs.get("src") or attrs.get("data-src") or (attrs.get("srcset") or "").split(" ")[0]
            if src and not src.startswith("data:"):
                return src
    return ""


def find_logo(html: str, base: str) -> tuple[str, str]:
    """Returns (logo_url, where_it_came_from)."""
    tree = parse(html)
    for source, finder in (("json_ld", _logo_from_json_ld), ("header_img", _logo_from_header)):
        url = absolute_url(finder(tree), base)
        if url and "favicon" not in url.lower():
            return url, source
    return "", ""
