"""Step 6e: independent proof of being Indian, read from the website itself (not from meta.json).

GSTIN = India's 15-character GST number. Its first 2 digits are the state code,
so it also cross-checks the state that meta.json claims.
"""
import re

from extract.html_text import visible_text

GSTIN_RE = re.compile(r"\b(\d{2})[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
GST_STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "25": "Dadra and Nagar Haveli and Daman and Diu", "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra", "28": "Andhra Pradesh", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands",
    "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
}
# a 6-digit PIN right after words like "PIN", "Pincode" or "India"
PIN_RE = re.compile(r"(?:pin\s*(?:code)?|pincode|india)\s*[:\-–,]?\s*([1-9]\d{2}\s?\d{3})\b", re.IGNORECASE)


def find_gstin(*htmls: str) -> tuple[str, str]:
    """Returns (gstin, state from its first 2 digits)."""
    for html in htmls:
        for match in GSTIN_RE.finditer(visible_text(html) if html else ""):
            state = GST_STATE_CODES.get(match.group(1))
            if state:
                return match.group(0), state
    return "", ""


def find_pincode(*htmls: str) -> str:
    for html in htmls:
        match = PIN_RE.search(visible_text(html) if html else "")
        if match:
            return match.group(1).replace(" ", "")
    return ""


def independent_evidence(gstin: str, phones: list[str], pincode: str) -> str:
    parts = []
    if gstin:
        parts.append("GSTIN on site")
    if any(p.startswith("+91") for p in phones):
        parts.append("+91 phone on site")
    if pincode:
        parts.append("Indian PIN code on site")
    return "; ".join(parts)
