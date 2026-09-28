"""Step 6b: social media profile links (one per platform, preferring the brand's own handle)."""
import re

from extract.html_text import absolute_url, parse

PLATFORMS = {
    "instagram": re.compile(r"^https?://(www\.)?instagram\.com/[A-Za-z0-9_.]+/?$"),
    "facebook": re.compile(r"^https?://([a-z]+\.)?facebook\.com/[^#]+$"),
    "twitter": re.compile(r"^https?://(www\.)?(twitter|x)\.com/[A-Za-z0-9_]+/?$"),
    "linkedin": re.compile(r"^https?://([a-z]+\.)?linkedin\.com/(company|in|showcase)/[^?#]+$"),
    "youtube": re.compile(r"^https?://(www\.)?youtube\.com/(@|channel/|c/|user/)[^?#]+$"),
}
# share buttons, Shopify's own pages and tracking pixels are not the store's profile
NOT_A_PROFILE = ("sharer", "/share", "intent/", "/shopify", "/tr?", "/plugins/", "/dialog/",
                 "/p/", "/reel/", "/watch", "/hashtag/", "/explore/", "/policies/")


def _clean_url(href: str, base: str) -> str:
    url = absolute_url(href, base).split("#")[0]
    if "profile.php" not in url:              # facebook.com/profile.php?id=123 needs its ?id
        url = url.split("?")[0]
    return url.rstrip("/")


def find_socials(*htmls: str, base: str = "", brand: str = "") -> dict[str, str]:
    """brand = a short word from the domain (e.g. 'boat'); a link containing it wins over other links."""
    candidates = {name: [] for name in PLATFORMS}
    for html in htmls:
        if not html:
            continue
        for a in parse(html).css("a[href]"):
            url = _clean_url(a.attributes.get("href", ""), base)
            if any(bad in url.lower() for bad in NOT_A_PROFILE):
                continue
            for name, pattern in PLATFORMS.items():
                if pattern.match(url) and url not in candidates[name]:
                    candidates[name].append(url)

    brand = brand.lower()
    socials = {}
    for name, urls in candidates.items():
        own = [u for u in urls if brand and brand in u.lower()]
        socials[name] = (own or urls or [""])[0]
    return socials
