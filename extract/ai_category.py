"""Step 6 refine, Part 5: a second opinion on each store's category from a small AI model.

The keyword rules (extract/category.py) can't understand names like "Air Force 1 Low" or "Choco Chip
Crunch", so an embedding model reads the store's own product titles and votes on the category.
A store keeps its category only when the keywords and the AI agree - disagreements are left out of the
final 1,000.

How it works:
  1. each of our categories gets a one-line description (CATEGORY_TEXT below)
  2. each product title (+ its product type) from the store's cached /products.json is turned into
     384 numbers by all-MiniLM-L6-v2 and matched to the closest category description
  3. majority vote over the store's products = the AI category (a store with no products uses its tagline)
  4. category_agreed = AI category is the same as the keyword category

  python -m extract.ai_category --limit 40     # trial: 40 random stores printed side by side, nothing saved
  python -m extract.ai_category                # all stores -> data/ai_categories.csv

Reads data/stores_refined.csv (never changed). The model is downloaded once to ~/.cache/huggingface.
"""
import argparse
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from extract.category import CATEGORIES
from extract.run_extract import page_url
from utils.fetcher import read_cache

IN_FILE = Path("data/stores_refined.csv")
OUT_FILE = Path("data/ai_categories.csv")
MODEL_NAME = "all-MiniLM-L6-v2"

# one plain-English line per category - what the model compares every product against
CATEGORY_TEXT = {
    "Apparel & Fashion": "clothing and fashion: sarees, kurtas, lehengas, dresses, shirts, t-shirts, jeans, trousers, jackets, hoodies, co-ord sets, innerwear",
    "Footwear": "footwear: shoes, sneakers, sandals, slippers, heels, loafers, boots, flip flops, juttis, mojaris",
    "Jewellery & Accessories": "jewellery and accessories: earrings, necklaces, rings, bracelets, bangles, pendants, anklets, watches, sunglasses, belts, wallets",
    "Bags & Luggage": "bags and luggage: handbags, backpacks, tote bags, sling bags, clutches, suitcases, trolley bags",
    "Beauty & Personal Care": "beauty and personal care: skincare, face wash, serum, moisturiser, sunscreen, shampoo, hair oil, makeup, lipstick, perfume, soap, beard care",
    "Health & Wellness": "health and wellness: supplements, protein powder, vitamins, ayurvedic medicine, herbal capsules, immunity boosters, medical products",
    "Food & Beverages": "food and drinks: tea, coffee, snacks, spices, masala, pickles, chocolates, sweets, namkeen, dry fruits, honey, ghee, flour, cookies, juices",
    "Home & Decor": "home decor and furnishing: cushions, curtains, bedsheets, rugs, lamps, vases, wall art, furniture, candles, towels, mattresses, clocks",
    "Kitchen & Dining": "kitchen and dining: cookware, utensils, pans, kadai, tawa, bottles, mugs, plates, bowls, cutlery, dinnerware, lunch boxes, containers",
    "Electronics & Gadgets": "electronics and gadgets: earbuds, headphones, speakers, chargers, cables, power banks, smartwatches, phone cases, mobile accessories, cameras, laptops",
    "Baby & Kids": "baby and kids products: baby clothes, diapers, newborn care, toddler and children essentials",
    "Toys & Games": "toys and games: toys, puzzles, board games, dolls, plush soft toys, building blocks, remote control cars",
    "Pet Supplies": "pet supplies: dog food, cat food, pet toys, leashes, collars, pet beds, pet grooming",
    "Sports & Fitness": "sports and fitness: gym equipment, dumbbells, yoga mats, cricket bats, badminton, cycling gear, activewear, workout accessories",
    "Books & Stationery": "books and stationery: books, novels, notebooks, diaries, journals, pens, planners, stickers, office supplies",
    "Art & Craft": "art and craft: paintings, canvas, art supplies, resin art, handmade craft items, DIY craft kits",
    "Religious & Pooja": "religious and pooja items: god idols, incense sticks, agarbatti, dhoop, rudraksha, pooja thali, spiritual items",
    "Plants & Gardening": "plants and gardening: live plants, seeds, planters, pots, succulents, bonsai, fertiliser, gardening tools",
    "Automotive": "automotive: car accessories, bike and motorcycle accessories, helmets, riding gear, spare parts, car care",
    "Gifts & Hampers": "gifts and hampers: gift boxes, gift hampers, personalised gifts, combo gift sets",
}
assert set(CATEGORY_TEXT) == set(CATEGORIES), "CATEGORY_TEXT must cover exactly the keyword categories"

# items most stores list that say nothing about what the store sells
NOT_A_PRODUCT = re.compile(r"gift card|gift voucher|e-?gift|shipping|insurance|protection|tip\b|donation|sample|test product", re.I)


def base_category(category: str) -> str:
    """'Apparel & Fashion (Women)' -> 'Apparel & Fashion'."""
    return category.split(" (")[0]


def product_texts(domain: str) -> list[str]:
    """'Title (product type)' for each product in the store's cached /products.json."""
    page = read_cache(page_url(domain, "products"))
    if not page or page.status != 200:
        return []
    try:
        products = json.loads(page.text).get("products", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    texts = []
    for p in products:
        title, ptype = (p.get("title") or "").strip(), (p.get("product_type") or "").strip()
        text = f"{title} ({ptype})" if ptype else title
        if text and not NOT_A_PRODUCT.search(text):
            texts.append(text[:200])
    return texts


def classify(stores: pd.DataFrame) -> pd.DataFrame:
    from sentence_transformers import SentenceTransformer     # imported here: loading PyTorch is slow

    start = time.time()
    print(f"Reading cached products for {len(stores):,} stores...")
    with ThreadPoolExecutor(max_workers=8) as pool:            # file reading, so threads help
        per_store = list(pool.map(product_texts, stores["domain"]))
    print(f"  {sum(map(len, per_store)):,} product titles in {time.time() - start:.0f}s")

    # a store with no usable products gets one vote from its own tagline
    sources = ["products" if texts else ("tagline" if tag else "") for texts, tag in zip(per_store, stores["tagline"])]
    per_store = [texts or ([tag] if tag else []) for texts, tag in zip(per_store, stores["tagline"])]

    print(f"Loading {MODEL_NAME}...")
    model = SentenceTransformer(MODEL_NAME)
    names = list(CATEGORY_TEXT)
    label_vecs = model.encode([CATEGORY_TEXT[n] for n in names], normalize_embeddings=True)

    flat = [t for texts in per_store for t in texts]
    print(f"Encoding {len(flat):,} texts...")
    vecs = model.encode(flat, batch_size=128, normalize_embeddings=True, show_progress_bar=True)
    best = (vecs @ label_vecs.T).argmax(axis=1)                  # cosine similarity -> closest category

    rows, i = [], 0
    for domain, texts, source in zip(stores["domain"], per_store, sources):
        votes = Counter(names[b] for b in best[i:i + len(texts)])
        i += len(texts)
        ranked = votes.most_common(2)
        rows.append({
            "domain": domain,
            "ai_category": ranked[0][0] if ranked else "",
            "ai_vote_share": round(ranked[0][1] / len(texts), 2) if ranked else 0.0,
            "ai_runner_up": ranked[1][0] if len(ranked) > 1 else "",
            "ai_source": source,
            "ai_items_used": len(texts),
        })
    print(f"  done in {time.time() - start:.0f}s")

    out = stores[["domain", "category"]].rename(columns={"category": "keyword_category"}).merge(pd.DataFrame(rows), on="domain")
    out["category_agreed"] = (out["keyword_category"] != "Other") & (
        out["keyword_category"].map(base_category) == out["ai_category"])
    return out


def report(out: pd.DataFrame):
    agreed = out["category_agreed"]
    print(f"\nKeywords and AI agree: {agreed.sum():,} of {len(out):,} ({agreed.mean():.0%})")
    print("AI source:", out["ai_source"].replace("", "none").value_counts().to_dict())
    print("\nMost common disagreements (keyword -> AI):")
    pairs = out[~agreed].apply(lambda r: f"{r['keyword_category']} -> {r['ai_category'] or '(nothing)'}", axis=1)
    print(pairs.value_counts().head(12).to_string())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="trial: N random stores, printed, nothing saved")
    args = parser.parse_args()

    stores = pd.read_csv(IN_FILE, low_memory=False).fillna("")
    if args.limit:
        stores = stores.sample(args.limit, random_state=42)
    out = classify(stores)

    if args.limit:
        pd.set_option("display.width", 200)
        print(out[["domain", "keyword_category", "ai_category", "ai_vote_share", "category_agreed"]].to_string(index=False))
    else:
        out.to_csv(OUT_FILE, index=False)
        print(f"Saved {OUT_FILE}")
    report(out)


if __name__ == "__main__":
    main()
