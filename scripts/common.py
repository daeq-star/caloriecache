"""Shared kit math, sanity checks, and data file IO.

Price per 2,000 kcal and days of food are computed here so the harvester,
the daily price update, and the site cannot drift apart.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
KITS_JSON = DATA_DIR / "kits.json"
KITS_CSV = DATA_DIR / "kits.csv"
PRICE_HISTORY_CSV = DATA_DIR / "price_history.csv"
RECALLS_JSON = DATA_DIR / "recalls.json"

# Shipping weight of mixed dry food, including the bucket or pouches.
# Pure fat is about 4,080 kcal per pound, so a mixed kit above 3,600 is not
# plausible. Below 700 is far under grains and usually means a bad parse or
# a weight that is not the food.
KCAL_PER_LB_MIN = 700
KCAL_PER_LB_MAX = 3600
# A stated or implied serving outside this band is also flagged. The band is
# wide on purpose: a side can be near 80 kcal and a large entrée near 700.
KCAL_PER_SERVING_MIN = 40
KCAL_PER_SERVING_MAX = 900
GRAMS_PER_LB = 453.59237

BASE_URL = "https://daeq-star.github.io/caloriecache"
BASE_PATH = "/caloriecache"

KIT_KEYS = [
    "id",
    "brand",
    "name",
    "product_url",
    "handle",
    "store_domain",
    "variant_id",
    "price",
    "currency",
    "total_calories",
    "calorie_is_estimate",
    "calorie_method",
    "calorie_source_quote",
    "servings",
    "kcal_per_serving",
    "kcal_per_serving_basis",
    "shelf_life_years",
    "shelf_life_quote",
    "price_per_2000_kcal",
    "days_at_2000_kcal",
    "advertised_days",
    "advertised_days_basis",
    "in_stock",
    "date_checked",
    "affiliate_url",
    "verified",
    "unverified_reason",
    "exclude_from_ranking",
    "weight_grams",
    "weight_basis",
    "kcal_per_lb",
    "calorie_check",
    "calorie_check_reason",
    "notes",
    "nutrition_checked",
    "price_source",
    "last_price_error",
    "page_fetch_note",
]

CSV_FIELDS = [
    "brand",
    "name",
    "product_url",
    "price",
    "total_calories",
    "calorie_method",
    "calorie_source_quote",
    "servings",
    "shelf_life_years",
    "price_per_2000_kcal",
    "days_at_2000_kcal",
    "in_stock",
    "date_checked",
    "affiliate_url",
    "verified",
    "calorie_is_estimate",
    "calorie_check",
    "calorie_check_reason",
    "kcal_per_lb",
    "weight_grams",
    "advertised_days",
    "id",
    "handle",
    "store_domain",
    "variant_id",
    "notes",
    "unverified_reason",
]

HISTORY_FIELDS = ["date", "kit_id", "price", "in_stock", "source"]


def price_per_2000_kcal(price: float | None, total_calories: float | None) -> float | None:
    if price is None or total_calories is None:
        return None
    if price <= 0 or total_calories <= 0:
        return None
    return round(float(price) * 2000.0 / float(total_calories), 2)


def days_at_2000_kcal(total_calories: float | None) -> float | None:
    if total_calories is None or total_calories <= 0:
        return None
    return round(float(total_calories) / 2000.0, 2)


def kcal_per_pound(total_calories: float | None, weight_grams: float | None) -> float | None:
    if not total_calories or not weight_grams or weight_grams <= 0:
        return None
    pounds = float(weight_grams) / GRAMS_PER_LB
    return round(float(total_calories) / pounds, 1)


def calorie_check(
    total_calories: float | None,
    weight_grams: float | None,
    servings: float | None,
) -> tuple[bool, str]:
    """Flag implausible calorie density. Does not drop the kit from the ranking."""
    reasons: list[str] = []
    per_lb = kcal_per_pound(total_calories, weight_grams)
    if per_lb is not None:
        if per_lb > KCAL_PER_LB_MAX:
            reasons.append(
                f"{per_lb:.0f} kcal per pound is above {KCAL_PER_LB_MAX:,.0f}. "
                "Mixed dry food should sit well under pure fat (about 4,080 kcal per pound)."
            )
        elif per_lb < KCAL_PER_LB_MIN:
            reasons.append(
                f"{per_lb:.0f} kcal per pound is below {KCAL_PER_LB_MIN:,.0f}. "
                "That is unusually low for a dry food kit and may be a weight or calorie error."
            )
    if (
        total_calories
        and servings
        and servings >= 5
        and total_calories > 0
    ):
        per_serving = float(total_calories) / float(servings)
        if per_serving < KCAL_PER_SERVING_MIN or per_serving > KCAL_PER_SERVING_MAX:
            reasons.append(
                f"About {per_serving:.0f} kcal per serving is outside "
                f"{KCAL_PER_SERVING_MIN}–{KCAL_PER_SERVING_MAX}, "
                "which usually means the serving count or the calorie total was misread."
            )
    return bool(reasons), " ".join(reasons)


def apply_metrics(kit: dict) -> dict:
    price = _num(kit.get("price"))
    calories = _num(kit.get("total_calories"))
    weight = _num(kit.get("weight_grams"))
    servings = _num(kit.get("servings"))
    kit["price"] = round(price, 2) if price is not None else None
    if calories is not None and abs(calories - round(calories)) < 1e-6:
        kit["total_calories"] = int(round(calories))
    elif calories is not None:
        kit["total_calories"] = round(calories, 1)
    else:
        kit["total_calories"] = None
    kit["price_per_2000_kcal"] = price_per_2000_kcal(kit["price"], kit["total_calories"])
    kit["days_at_2000_kcal"] = days_at_2000_kcal(kit["total_calories"])
    kit["kcal_per_lb"] = kcal_per_pound(kit["total_calories"], weight)
    flagged, reason = calorie_check(kit["total_calories"], weight, servings)
    kit["calorie_check"] = flagged
    kit["calorie_check_reason"] = reason
    quote = (kit.get("calorie_source_quote") or "").strip()
    method = (kit.get("calorie_method") or "").strip()
    blocked = bool(kit.get("exclude_from_ranking"))
    has_price = kit["price"] is not None and kit["price"] > 0
    has_cal = kit["total_calories"] is not None and kit["total_calories"] > 0
    if (not blocked) and has_price and has_cal and quote and method:
        kit["verified"] = True
        kit["unverified_reason"] = ""
    else:
        kit["verified"] = False
        if not kit.get("unverified_reason"):
            missing = []
            if not has_price:
                missing.append("no positive price from the store")
            if not has_cal:
                missing.append("no calorie total on the product page")
            if has_cal and not quote:
                missing.append("calorie figure had no source line to quote")
            if blocked and not missing:
                missing.append("calorie figures on the page conflict")
            kit["unverified_reason"] = "; ".join(missing)
    kit["affiliate_url"] = kit.get("affiliate_url") or ""
    kit["calorie_is_estimate"] = bool(kit.get("calorie_is_estimate"))
    kit["in_stock"] = bool(kit.get("in_stock"))
    kit["exclude_from_ranking"] = blocked
    return kit


def blank_kit() -> dict:
    kit = {key: "" for key in KIT_KEYS}
    for key in (
        "price",
        "total_calories",
        "servings",
        "kcal_per_serving",
        "shelf_life_years",
        "price_per_2000_kcal",
        "days_at_2000_kcal",
        "advertised_days",
        "variant_id",
        "weight_grams",
        "kcal_per_lb",
    ):
        kit[key] = None
    kit["currency"] = "USD"
    kit["affiliate_url"] = ""
    kit["verified"] = False
    kit["calorie_is_estimate"] = False
    kit["calorie_check"] = False
    kit["in_stock"] = False
    kit["exclude_from_ranking"] = False
    kit["notes"] = ""
    kit["unverified_reason"] = ""
    kit["calorie_method"] = ""
    kit["calorie_source_quote"] = ""
    kit["last_price_error"] = ""
    kit["page_fetch_note"] = ""
    kit["price_source"] = ""
    kit["weight_basis"] = ""
    kit["shelf_life_quote"] = ""
    kit["advertised_days_basis"] = ""
    kit["kcal_per_serving_basis"] = ""
    return kit


def load_document() -> dict:
    if not KITS_JSON.exists():
        raise SystemExit(f"Missing {KITS_JSON}. Run scripts/harvest_kits.py first.")
    doc = json.loads(KITS_JSON.read_text(encoding="utf-8"))
    if "kits" not in doc:
        raise SystemExit(f"{KITS_JSON} has no kits array.")
    return doc


def save_document(doc: dict) -> None:
    # Local import: extract does not import common, and this keeps every write
    # on the same multiple-of-a-stated-total rule.
    from extract import apply_stated_multiples

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    kits = [dict(kit) for kit in doc.get("kits", [])]
    apply_stated_multiples(kits)
    kits = [apply_metrics(kit) for kit in kits]
    kits.sort(key=lambda kit: (kit.get("brand") or "", kit.get("name") or "", kit.get("id") or ""))
    doc = dict(doc)
    doc["kits"] = [{key: kit.get(key) for key in KIT_KEYS} for kit in kits]
    doc["kit_count"] = len(kits)
    doc["verified_count"] = sum(1 for kit in kits if kit.get("verified"))
    doc["unverified_count"] = doc["kit_count"] - doc["verified_count"]
    KITS_JSON.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with KITS_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for kit in doc["kits"]:
            row = {}
            for field in CSV_FIELDS:
                value = kit.get(field)
                if isinstance(value, bool):
                    value = "true" if value else "false"
                elif value is None:
                    value = ""
                row[field] = value
            writer.writerow(row)


def load_history() -> list[dict]:
    if not PRICE_HISTORY_CSV.exists():
        return []
    with PRICE_HISTORY_CSV.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def upsert_history(rows: list[dict], new_rows: list[dict]) -> list[dict]:
    """Keep one row per kit per calendar day. A re-run replaces that day's row."""
    index: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    for row in rows + new_rows:
        key = (row["date"], row["kit_id"])
        if key not in index:
            order.append(key)
        index[key] = {
            "date": row["date"],
            "kit_id": row["kit_id"],
            "price": row["price"],
            "in_stock": row["in_stock"],
            "source": row["source"],
        }
    merged = [index[key] for key in order]
    merged.sort(key=lambda row: (row["date"], row["kit_id"]))
    return merged


def save_history(rows: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with PRICE_HISTORY_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _num(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
