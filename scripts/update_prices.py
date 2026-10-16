#!/usr/bin/env python3
"""Refresh listed prices from official stores.

Shopify product JSON is tried first. If that fails, the product HTML is
checked for a price tag. A failed fetch keeps the last good price and does
not add a history row, so a blip is not recorded as a new price.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import load_document, load_history, save_document, save_history, upsert_history  # noqa: E402

UA = "Mozilla/5.0 (compatible; CalorieCache/1.0; +https://daeq-star.github.io/caloriecache/)"
TODAY = date.today().isoformat()


def fetch(url: str, accept: str) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "en-US,en;q=0.9"},
    )
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.status, response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as error:
        return 0, str(error)


def dollars_from_cents(value) -> float | None:
    """Shopify's /products/<handle>.js endpoint reports price in cents."""
    try:
        cents = float(value)
    except (TypeError, ValueError):
        return None
    if cents <= 0:
        return None
    return round(cents / 100.0, 2)


def _choose_variant(variants: list, variant_id):
    if variant_id is not None:
        for variant in variants:
            if str(variant.get("id")) == str(variant_id):
                return variant
    return variants[0] if variants else None


def price_from_ajax_js(body: str, variant_id) -> tuple[float | None, bool | None]:
    """The .js product document includes availability. The .json document does not."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None, None
    chosen = _choose_variant(payload.get("variants") or [], variant_id)
    if not chosen:
        return None, None
    price = dollars_from_cents(chosen.get("price"))
    if price is None:
        return None, None
    in_stock = bool(chosen.get("available")) if "available" in chosen else None
    return price, in_stock


def price_from_product_json(body: str, variant_id) -> tuple[float | None, bool | None]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None, None
    product = payload.get("product") or payload
    chosen = _choose_variant(product.get("variants") or [], variant_id)
    if not chosen:
        return None, None
    try:
        price = float(chosen.get("price"))
    except (TypeError, ValueError):
        return None, None
    if price <= 0:
        return None, None
    # The single-product .json feed omits `available`. Do not treat that as out of stock.
    in_stock = bool(chosen["available"]) if "available" in chosen else None
    return round(price, 2), in_stock


def price_from_html(html: str) -> tuple[float | None, bool | None]:
    patterns = [
        r'property=["\']og:price:amount["\']\s+content=["\']([0-9]+(?:\.[0-9]+)?)["\']',
        r'content=["\']([0-9]+(?:\.[0-9]+)?)["\']\s+property=["\']og:price:amount["\']',
        r'property=["\']product:price:amount["\']\s+content=["\']([0-9]+(?:\.[0-9]+)?)["\']',
    ]
    price = None
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            price = round(float(match.group(1)), 2)
            break
    if price is None or price <= 0:
        return None, None
    in_stock = None
    if re.search(r"schema.org/OutOfStock", html):
        in_stock = False
    elif re.search(r"schema.org/InStock", html):
        in_stock = True
    availability = re.search(r'property=["\']og:availability["\']\s+content=["\']([^"\']+)', html, re.I)
    if availability:
        in_stock = "out" not in availability.group(1).lower()
    return price, in_stock


def refresh_kit(kit: dict) -> tuple[dict, str | None]:
    domain = kit.get("store_domain")
    handle = kit.get("handle")
    if not domain or not handle:
        kit["last_price_error"] = "missing store domain or handle"
        return kit, None
    slug = quote(handle, safe="")
    # .js includes variant.available. .json has the dollar price but no stock flag.
    js_status, js_body = fetch(f"https://{domain}/products/{slug}.js", "application/json")
    if js_status == 200:
        price, in_stock = price_from_ajax_js(js_body, kit.get("variant_id"))
        if price:
            kit["price"] = price
            if in_stock is not None:
                kit["in_stock"] = in_stock
            kit["date_checked"] = TODAY
            kit["price_source"] = "shopify_json"
            kit["last_price_error"] = ""
            return kit, "shopify_json"
    json_status, body = fetch(f"https://{domain}/products/{slug}.json", "application/json")
    if json_status == 200:
        price, in_stock = price_from_product_json(body, kit.get("variant_id"))
        if price:
            kit["price"] = price
            if in_stock is not None:
                kit["in_stock"] = in_stock
            kit["date_checked"] = TODAY
            kit["price_source"] = "shopify_json"
            kit["last_price_error"] = ""
            return kit, "shopify_json"
    html_status, html = fetch(f"https://{domain}/products/{slug}", "text/html")
    if html_status == 200 and html and not html.lstrip().startswith("{"):
        price, in_stock = price_from_html(html)
        if price:
            kit["price"] = price
            if in_stock is not None:
                kit["in_stock"] = in_stock
            kit["date_checked"] = TODAY
            kit["price_source"] = "html_fallback"
            kit["last_price_error"] = ""
            return kit, "html_fallback"
    kit["last_price_error"] = (
        f"price fetch failed (JS HTTP {js_status}, JSON HTTP {json_status}, HTML HTTP {html_status}); kept the last good price"
    )
    return kit, None


def main() -> None:
    doc = load_document()
    history_rows = []
    failures = []
    for kit in doc["kits"]:
        refresh_kit(kit)
        if kit.get("last_price_error"):
            failures.append(f"{kit.get('id')}: {kit['last_price_error']}")
            continue
        history_rows.append(
            {
                "date": TODAY,
                "kit_id": kit["id"],
                "price": f"{float(kit['price']):.2f}",
                "in_stock": "true" if kit.get("in_stock") else "false",
                "source": kit.get("price_source") or "shopify_json",
            }
        )
    doc["price_checked"] = TODAY
    save_document(doc)
    merged = upsert_history(load_history(), history_rows)
    save_history(merged)
    print(f"Updated {len(history_rows)} prices for {TODAY}. Failures: {len(failures)}.")
    for line in failures:
        print(" ", line)


if __name__ == "__main__":
    main()
