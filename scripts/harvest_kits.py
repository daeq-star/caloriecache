#!/usr/bin/env python3
"""Capture one snapshot of official-store kits into data/kits.json.

Calories come from the product description or that product's structured data.
Prices come from the Shopify product JSON. Nothing is filled in by hand.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from urllib.parse import quote as urlquote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, apply_metrics, blank_kit, save_document  # noqa: E402
from extract import (  # noqa: E402
    extract_nutrition,
    find_shelf_life,
    html_to_text,
    jsonld_properties,
    pick_jsonld_product,
)

UA = "Mozilla/5.0 (compatible; CalorieCache/1.0; +https://daeq-star.github.io/caloriecache/)"
CACHE = Path(__file__).resolve().parents[1] / ".cache"
TODAY = date.today().isoformat()

# (brand, domain, handle). Handles can repeat across stores; the pair is the key.
KITS = [
    ("4Patriots", "4patriots.com", "72-hour-emergency-survival-food-kit"),
    ("4Patriots", "4patriots.com", "72-hour-platinumxl-emergency-survival-food-kit"),
    ("4Patriots", "4patriots.com", "1-week-emergency-survival-food-kit"),
    ("4Patriots", "4patriots.com", "2-week-emergency-survival-food-kit"),
    ("4Patriots", "4patriots.com", "4-week-emergency-survival-food-kit"),
    ("4Patriots", "4patriots.com", "3-month-emergency-survival-food-kit"),
    ("4Patriots", "4patriots.com", "1-year-emergency-survival-food-kit"),
    ("4Patriots", "4patriots.com", "plant-based-protein-emergency-survival-food-kit"),
    ("4Patriots", "4patriots.com", "pasta-lovers-emergency-survival-food-kit"),
    ("4Patriots", "4patriots.com", "meat-protein-deluxe-emergency-survival-food-kit"),
    ("4Patriots", "4patriots.com", "lumberjack-emergency-survival-food-kit"),
    ("4Patriots", "4patriots.com", "fruit-veggie-snack-emergency-survival-food-kit"),
    ("ReadyWise", "readywise.com", "72-hour-emergency-food-kit"),
    ("ReadyWise", "readywise.com", "14-day-emergency-food-bucket"),
    ("ReadyWise", "readywise.com", "emergency-food-supply-ready-grab-bag"),
    ("ReadyWise", "readywise.com", "emergency-1-month-supply-2-bucket-bundle"),
    ("ReadyWise", "readywise.com", "3-month-emergency-food-supply"),
    ("ReadyWise", "readywise.com", "6-month-emergency-food-supply"),
    ("ReadyWise", "readywise.com", "1-year-emergency-food-supply"),
    ("ReadyWise", "readywise.com", "60-serving-entree-bucket-1"),
    ("ReadyWise", "readywise.com", "120-serving-emergency-food-supply"),
    ("ReadyWise", "readywise.com", "118-calorie-booster-bucket"),
    ("ReadyWise", "readywise.com", "84-serving-gluten-free-grab-and-go-bucket-1"),
    ("ReadyWise", "readywise.com", "meat-and-rice-emergency-food-bucket"),
    ("Mountain House", "mountainhouse.com", "just-in-case-3-day-emergency-food-supply"),
    ("Mountain House", "mountainhouse.com", "just-in-case-14-day-emergency-food-supply"),
    ("Mountain House", "mountainhouse.com", "15-day-emergency-food-supply-kit"),
    ("Mountain House", "mountainhouse.com", "30-day-emergency-food-supply-kit"),
    ("Mountain House", "mountainhouse.com", "3-month-emergency-food-supply"),
    ("Mountain House", "mountainhouse.com", "6-month-emergency-food-supply"),
    ("Mountain House", "mountainhouse.com", "1-year-emergency-food-supply"),
    ("Mountain House", "mountainhouse.com", "essential-assortment-bucket"),
    ("Mountain House", "mountainhouse.com", "expedition-meal-assortment-bucket-5-day-meal-kit"),
    ("Mountain House", "mountainhouse.com", "classic-assortment-bucket"),
    ("Legacy Food Storage", "legacyfoodstorage.com", "60-serving-entree-bucket"),
    ("Legacy Food Storage", "legacyfoodstorage.com", "120-serving-entree-bucket"),
    ("Legacy Food Storage", "legacyfoodstorage.com", "60-serving-breakfast-lunch-and-dinner-bucket"),
    ("Legacy Food Storage", "legacyfoodstorage.com", "120-serving-breakfast-lunch-and-dinner-bucket"),
    ("Legacy Food Storage", "legacyfoodstorage.com", "32-serving-family-72-hour-emergency-food-kit"),
    ("Legacy Food Storage", "legacyfoodstorage.com", "120-serving-breakfast-bucket"),
    ("Legacy Food Storage", "legacyfoodstorage.com", "premium-240-serving-package"),
    ("Legacy Food Storage", "legacyfoodstorage.com", "premium-360-serving-package"),
    ("Valley Food Storage", "valleyfoodstorage.com", "72-hour-emergency-food-kit"),
    ("Valley Food Storage", "valleyfoodstorage.com", "175-servings-long-term-food-kit"),
    ("Valley Food Storage", "valleyfoodstorage.com", "350-serving-long-term-food-kit"),
    ("Valley Food Storage", "valleyfoodstorage.com", "1050-serving-long-term-food-kit"),
    ("Valley Food Storage", "valleyfoodstorage.com", "2100-serving-long-term-food-kit"),
    ("Valley Food Storage", "valleyfoodstorage.com", "4200-serving-long-term-food-kit"),
    ("Valley Food Storage", "valleyfoodstorage.com", "entree-bucket"),
    ("Valley Food Storage", "valleyfoodstorage.com", "breakfast-bucket"),
    ("Valley Food Storage", "valleyfoodstorage.com", "freeze-dried-fruit-vegetable-bucket"),
    ("Emergency Essentials", "beprepared.com", "emergency-food-supply-30-days"),
    ("Emergency Essentials", "beprepared.com", "emergency-essentials®-3-month-1-person-emergency-food-kit"),
    ("Emergency Essentials", "beprepared.com", "6-month-emergency-food-kit-emergency-essentials"),
    ("Emergency Essentials", "beprepared.com", "1-year-emergency-food-kit-emergency-essentials"),
    ("Emergency Essentials", "beprepared.com", "2-week-true-survival-food-kit"),
    ("Emergency Essentials", "beprepared.com", "z_legacy_zf_nogluten_gluten-free-kit"),
    ("Emergency Essentials", "beprepared.com", "12-complete-meal-mre-food-supply"),
    ("Nutrient Survival", "nutrientsurvival.com", "14-day-emergency-food-kit"),
    ("Nutrient Survival", "nutrientsurvival.com", "30-day-emergency-food-kit"),
    ("Nutrient Survival", "nutrientsurvival.com", "30-day-max-variety-emergency-food-kit"),
    ("Nutrient Survival", "nutrientsurvival.com", "60-day-max-variety-emergency-food-kit"),
    ("Nutrient Survival", "nutrientsurvival.com", "90-day-max-variety-emergency-food-kit"),
    ("Nutrient Survival", "nutrientsurvival.com", "7-day-high-protein-emergency-food-bucket"),
    ("Nutrient Survival", "nutrientsurvival.com", "fruits-and-vegetables-emergency-food-bucket"),
    ("Peak Refuel", "peakrefuel.com", "entree-essentials-bucket-2-0"),
    ("Peak Refuel", "peakrefuel.com", "14-day-pack"),
    ("Peak Refuel", "peakrefuel.com", "30-day-pack"),
    ("Peak Refuel", "peakrefuel.com", "90-day-pack"),
    ("Augason Farms", "augasonfarms.com", "8-variety-food-supply-bucket-emergency-kit-variety-add-on-162-servings"),
    ("Augason Farms", "augasonfarms.com", "freeze-dried-dehydrated-vegetable-variety-kit-125-servings"),
]


def fetch(url: str, accept: str) -> tuple[int, str]:
    # Shopify returns product JSON instead of HTML when Accept prefers JSON.
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return response.status, raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        return error.code, body
    except urllib.error.URLError as error:
        return 0, str(error)


def cached_fetch(url: str, cache_path: Path, accept: str) -> tuple[int, str, str]:
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return 200, cache_path.read_text(encoding="utf-8", errors="replace"), "cache"
    last_status = 0
    last_body = ""
    for attempt in range(3):
        status, body = fetch(url, accept)
        last_status, last_body = status, body
        if status == 200 and body:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(body, encoding="utf-8")
            return status, body, "network"
        if status not in (429, 500, 502, 503, 504, 0):
            break
        time.sleep(1.5 * (attempt + 1))
    return last_status, last_body, "network"


def load_catalog(domain: str) -> dict[str, dict]:
    products: dict[str, dict] = {}
    for page in (1, 2, 3):
        url = f"https://{domain}/products.json?limit=250&page={page}"
        cache = CACHE / "catalog" / f"{domain}-{page}.json"
        status, body, _source = cached_fetch(url, cache, "application/json")
        if status != 200:
            print(f"  catalog {domain} page {page}: HTTP {status}")
            break
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            print(f"  catalog {domain} page {page}: not JSON")
            break
        batch = payload.get("products") or []
        if not batch:
            break
        for product in batch:
            products[product["handle"]] = product
        if len(batch) < 250:
            break
        time.sleep(0.2)
    return products


def kit_id(brand: str, handle: str) -> str:
    brand_slug = re.sub(r"[^a-z0-9]+", "-", brand.lower()).strip("-")
    handle_slug = handle.replace("®", "")
    handle_slug = re.sub(r"[^a-z0-9]+", "-", handle_slug.lower()).strip("-")
    return f"{brand_slug}-{handle_slug}"[:140]


def weight_from_product(product: dict, title: str) -> tuple[int | None, str]:
    variant = (product.get("variants") or [{}])[0]
    grams = variant.get("grams") or 0
    try:
        grams = float(grams)
    except (TypeError, ValueError):
        grams = 0
    if grams > 0:
        return int(round(grams)), "Shopify variant shipping weight (grams)"
    match = re.search(r"(\d+(?:\.\d+)?)\s*lbs?\b", title or "", re.I)
    if match:
        pounds = float(match.group(1))
        return int(round(pounds * 453.59237)), "pounds stated in the product name"
    return None, ""


def build_one(brand: str, domain: str, handle: str, product: dict | None) -> dict:
    kit = blank_kit()
    kit["id"] = kit_id(brand, handle)
    kit["brand"] = brand
    kit["handle"] = handle
    kit["store_domain"] = domain
    kit["currency"] = "USD"
    kit["affiliate_url"] = ""
    kit["nutrition_checked"] = TODAY
    kit["date_checked"] = TODAY
    product_url = f"https://{domain}/products/{urlquote(handle, safe='')}"
    kit["product_url"] = product_url
    if product is None:
        kit["name"] = handle
        kit["unverified_reason"] = "product was not in the store's products.json catalog"
        kit["exclude_from_ranking"] = True
        kit["page_fetch_note"] = "missing from catalog"
        return apply_metrics(kit)

    variant = (product.get("variants") or [{}])[0]
    kit["name"] = product.get("title") or handle
    kit["variant_id"] = variant.get("id")
    try:
        price = float(variant.get("price"))
    except (TypeError, ValueError):
        price = None
    kit["price"] = price if price and price > 0 else None
    kit["in_stock"] = bool(variant.get("available"))
    kit["price_source"] = "shopify_products_json"
    if not kit["price"]:
        kit["last_price_error"] = "catalog variant had no positive price"
    weight, weight_basis = weight_from_product(product, kit["name"])
    kit["weight_grams"] = weight
    kit["weight_basis"] = weight_basis

    page_cache = CACHE / "pages" / domain / f"{handle.replace('/', '_')}.html"
    status, html, source = cached_fetch(product_url, page_cache, "text/html")
    if status != 200:
        kit["page_fetch_note"] = f"product page HTTP {status} ({source})"
        html = ""
    else:
        kit["page_fetch_note"] = ""

    sku = str(variant.get("sku") or "")
    props = jsonld_properties(pick_jsonld_product(html, handle, sku, kit["name"]))
    body_text = html_to_text(product.get("body_html") or "")
    nutrition = extract_nutrition(kit["name"], body_text, props)
    for key, value in nutrition.items():
        if key == "notes" and kit.get("notes"):
            kit["notes"] = (kit["notes"] + " " + value).strip()
        else:
            kit[key] = value

    # Shelf life is often outside the description. Use the full page only when
    # the description did not already state one, and only if the page agrees.
    if kit.get("shelf_life_years") is None and html:
        page_text = html_to_text(html)
        years, quote = find_shelf_life(page_text)
        if years:
            kit["shelf_life_years"] = years
            kit["shelf_life_quote"] = quote
        elif quote.startswith("Conflicting") and not kit.get("notes"):
            kit["notes"] = quote

    if re.search(r"buy 1,\s*get 1|buy one,\s*get one", body_text, re.I):
        extra = (
            "The product page also advertises a buy-one-get-one offer. "
            "The price here is the listed price of one kit, not a discounted pair."
        )
        kit["notes"] = ((kit.get("notes") or "") + " " + extra).strip()

    return apply_metrics(kit)


def main() -> None:
    domains = sorted({domain for _brand, domain, _handle in KITS})
    catalogs = {}
    print(f"Loading catalogs for {len(domains)} stores...")
    for domain in domains:
        catalogs[domain] = load_catalog(domain)
        print(f"  {domain}: {len(catalogs[domain])} products")

    kits = []
    failures = []
    print(f"Reading {len(KITS)} product pages...")
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {}
        for brand, domain, handle in KITS:
            product = catalogs.get(domain, {}).get(handle)
            futures[pool.submit(build_one, brand, domain, handle, product)] = (brand, handle)
        for future in as_completed(futures):
            brand, handle = futures[future]
            kit = future.result()
            kits.append(kit)
            flag = "ok" if kit.get("verified") else "UNVERIFIED"
            est = " est" if kit.get("calorie_is_estimate") else ""
            check = " CHECK" if kit.get("calorie_check") else ""
            print(
                f"  [{flag}{est}{check}] {kit['brand']}: {kit['name'][:64]} "
                f"${kit.get('price')} cal={kit.get('total_calories')} "
                f"$/2k={kit.get('price_per_2000_kcal')}"
            )
            if kit.get("page_fetch_note"):
                failures.append(f"{brand} {handle}: {kit['page_fetch_note']}")
            if not kit.get("verified"):
                failures.append(f"{brand} {handle}: {kit.get('unverified_reason')}")

    doc = {
        "project": "CalorieCache",
        "description": (
            "Emergency food kits ranked by listed price per 2,000 kcal. "
            "Figures are copied from official brand stores on the nutrition_checked date."
        ),
        "nutrition_checked": TODAY,
        "base_url": "https://daeq-star.github.io/caloriecache/",
        "calorie_check_kcal_per_lb_min": 700,
        "calorie_check_kcal_per_lb_max": 3600,
        "kits": kits,
    }
    save_document(doc)
    verified = sum(1 for kit in kits if kit.get("verified"))
    print(f"Wrote {len(kits)} kits ({verified} verified, {len(kits) - verified} unverified) to {DATA_DIR}")
    if failures:
        print("Notes:")
        for line in failures:
            print(" ", line)


if __name__ == "__main__":
    main()
