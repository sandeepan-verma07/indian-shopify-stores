"""Step 6a: emails and phone numbers."""
import re

import phonenumbers

from extract.html_text import parse, visible_text

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
JUNK_EMAIL_PARTS = ("example.", "sentry", "wixpress", "yourdomain", "domain.com", "email.com",
                    "yourname", "name@", "user@", "@shopify.com", "@2x", ".png", ".jpg", ".jpeg",
                    ".webp", ".gif", ".svg")
MAX_EMAILS, MAX_PHONES = 5, 3


def find_emails(*htmls: str) -> list[str]:
    found = []
    for html in htmls:
        if not html:
            continue
        tree = parse(html)
        mailtos = [a.attributes.get("href", "")[7:].split("?")[0] for a in tree.css('a[href^="mailto:"]')]
        for email in mailtos + EMAIL_RE.findall(visible_text(html)):
            email = email.strip().lower().rstrip(".")
            if email and not any(bad in email for bad in JUNK_EMAIL_PARTS) and email not in found:
                found.append(email)
    return found[:MAX_EMAILS]


def find_phones(*htmls: str) -> list[str]:
    """Only numbers that Google's phonenumbers library says are VALID Indian numbers, as +91XXXXXXXXXX."""
    found = []
    for html in htmls:
        if not html:
            continue
        tree = parse(html)
        tel_links = " ; ".join(a.attributes.get("href", "")[4:] for a in tree.css('a[href^="tel:"]'))
        for text in (tel_links, visible_text(html)):
            for match in phonenumbers.PhoneNumberMatcher(text, "IN"):
                number = match.number
                if number.country_code != 91 or not phonenumbers.is_valid_number(number):
                    continue
                e164 = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
                if e164 not in found:
                    found.append(e164)
    return found[:MAX_PHONES]
