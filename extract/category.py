"""Step 6f: what the store sells, as one category from a fixed list (transparent keyword rules)."""
import json
import re
from collections import Counter

CATEGORIES = {
    "Apparel & Fashion": ["saree", "sari", "kurta", "kurti", "lehenga", "salwar", "dupatta", "dress", "shirt",
                          "t-shirt", "tshirt", "top", "jeans", "trouser", "pant", "jacket", "hoodie", "sweatshirt",
                          "co-ord", "blouse", "skirt", "nightwear", "innerwear", "underwear", "boxer", "bra",
                          "lingerie", "apparel", "clothing", "ethnic", "fabric", "shorts", "jogger", "tee"],
    "Footwear": ["shoe", "sneaker", "sandal", "slipper", "footwear", "heel", "loafer", "boot", "flip flop", "jutti", "mojari"],
    "Jewellery & Accessories": ["jewel", "jewelry", "jewellery", "earring", "necklace", "ring", "bracelet", "bangle",
                                "pendant", "anklet", "chain", "watch", "sunglass", "belt", "wallet", "cufflink", "mangalsutra"],
    "Bags & Luggage": ["bag", "backpack", "handbag", "tote", "luggage", "trolley", "suitcase", "clutch", "sling"],
    "Beauty & Personal Care": ["skincare", "skin care", "serum", "face wash", "facewash", "moisturiser", "moisturizer",
                               "sunscreen", "shampoo", "conditioner", "hair oil", "lipstick", "makeup", "kajal",
                               "cosmetic", "perfume", "fragrance", "deodorant", "soap", "body wash", "beard",
                               "grooming", "cream", "lotion", "nail", "attar"],
    "Health & Wellness": ["supplement", "protein", "vitamin", "ayurved", "herbal", "wellness", "capsule", "tablet",
                          "immunity", "medical", "health", "whey", "collagen", "sexual wellness"],
    "Food & Beverages": ["tea", "coffee", "snack", "spice", "masala", "pickle", "chocolate", "sweet", "namkeen",
                         "dry fruit", "nuts", "honey", "ghee", "millet", "flour", "rice", "cooking oil", "sauce", "food",
                         "beverage", "juice", "cookie", "granola", "muesli", "peanut butter"],
    "Home & Decor": ["decor", "cushion", "curtain", "bedsheet", "bed sheet", "rug", "carpet", "lamp", "vase",
                     "décor", "wall art", "furniture", "candle", "towel", "mattress", "pillow", "planter", "clock", "furnishing"],
    "Kitchen & Dining": ["kitchen", "cookware", "utensil", "tawa", "kadai", "pan", "foil", "bottle", "mug", "plate", "bowl",
                         "cutlery", "dinnerware", "container", "lunch box", "tiffin", "glassware", "flask"],
    "Electronics & Gadgets": ["earbud", "headphone", "earphone", "speaker", "charger", "cable", "power bank",
                              "smartwatch", "mobile", "phone case", "laptop", "camera", "gadget", "electronic",
                              "led", "battery", "adapter", "keyboard", "mouse", "tws"],
    "Baby & Kids": ["baby", "kids", "infant", "toddler", "diaper", "newborn", "children"],
    "Toys & Games": ["toy", "puzzle", "board game", "game", "lego", "doll", "plush"],
    "Pet Supplies": ["pet", "dog", "cat", "puppy", "kitten", "leash", "collar"],
    "Sports & Fitness": ["gym", "fitness", "yoga", "sports", "cricket", "badminton", "cycling", "dumbbell", "workout", "activewear"],
    "Books & Stationery": ["book", "notebook", "diary", "journal", "stationery", "pen", "planner", "sticker"],
    "Art & Craft": ["art", "craft", "painting", "handmade", "handcrafted", "canvas", "resin", "diy"],
    "Religious & Pooja": ["pooja", "puja", "idol", "incense", "agarbatti", "dhoop", "rudraksha", "spiritual", "god"],
    "Plants & Gardening": ["plant", "seed", "garden", "pot", "succulent", "bonsai", "fertiliser", "fertilizer"],
    "Automotive": ["car", "bike", "helmet", "motorcycle", "automotive", "riding", "spare part", "ktm"],
    "Gifts & Hampers": ["gift", "hamper", "combo box", "gifting"],
}
AUDIENCE_WORDS = {"Women": ["women", "woman", "ladies", "girl", "her"], "Men": ["men", "man", "gents", "boy", "his"]}


def _keyword_hits(text: str) -> Counter:
    hits = Counter()
    for category, words in CATEGORIES.items():
        for word in words:
            hits[category] += len(re.findall(rf"\b{re.escape(word)}(?:s|es)?\b", text))
    return hits


def _products_text(products_json: str) -> tuple[str, list[str]]:
    """Product types count 3x (the merchant chose them), titles and tags once."""
    try:
        products = json.loads(products_json).get("products", [])
    except (json.JSONDecodeError, AttributeError, TypeError):
        return "", []
    types = [p.get("product_type", "") for p in products if p.get("product_type")]
    titles = [p.get("title", "") for p in products]
    tags = [t for p in products for t in (p.get("tags") or [])]
    text = " ".join(types * 3 + titles + tags).lower()
    top_types = [t for t, _ in Counter(types).most_common(3)]
    return text, top_types


def find_category(products_json: str, fallback_text: str) -> tuple[str, str, str]:
    """Returns (category, source, top product types)."""
    text, top_types = _products_text(products_json)
    source = "products_json"
    hits = _keyword_hits(text) if text else Counter()
    if not hits or hits.most_common(1)[0][1] == 0:
        text, source = (fallback_text or "").lower(), "description"
        hits = _keyword_hits(text)
    if not hits or hits.most_common(1)[0][1] == 0:
        return "Other", "", ", ".join(top_types)

    category = hits.most_common(1)[0][0]
    if category == "Apparel & Fashion":           # e.g. "Apparel & Fashion (Women)"
        audience = {who: sum(len(re.findall(rf"\b{w}\b", text)) for w in words) for who, words in AUDIENCE_WORDS.items()}
        top, second = sorted(audience.values(), reverse=True)
        if top >= 3 and top >= 2 * second:
            category += f" ({max(audience, key=audience.get)})"
    return category, source, ", ".join(top_types)
