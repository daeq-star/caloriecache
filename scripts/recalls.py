#!/usr/bin/env python3
"""Pull openFDA food-enforcement records for the brands this site tracks.

Window is the last 12 months. A brand with no matching record is a quiet
result, not an error. API failures are stored on the document so the site
can say the check did not finish.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import RECALLS_JSON  # noqa: E402

UA = "Mozilla/5.0 (compatible; CalorieCache/1.0; +https://daeq-star.github.io/caloriecache/)"
# Phrases are matched against the recalling firm and the product description.
# Short words like "Legacy" or "Peak" are not searched on their own.
BRAND_TERMS = [
    ("Emergency Essentials", "Emergency Essentials"),
    ("Ready Hour", "Ready Hour"),
    ("ReadyWise", "ReadyWise"),
    ("Wise Company", "Wise Company"),
    ("Augason Farms", "Augason"),
    ("Mountain House", "Mountain House"),
    ("Legacy Food Storage", "Legacy Food Storage"),
    ("Valley Food Storage", "Valley Food Storage"),
    ("4Patriots", "4Patriots"),
    ("Nutrient Survival", "Nutrient Survival"),
    ("Peak Refuel", "Peak Refuel"),
]


def fetch_search(search: str, skip: int) -> tuple[int, dict]:
    query = urllib.parse.urlencode({"search": search, "limit": 100, "skip": skip})
    url = f"https://api.fda.gov/food/enforcement.json?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"error": {"message": body[:300]}}
        return error.code, payload
    except urllib.error.URLError as error:
        return 0, {"error": {"message": str(error)}}


def slim(record: dict, brands: list[str]) -> dict:
    return {
        "recall_number": record.get("recall_number") or "",
        "report_date": record.get("report_date") or "",
        "recall_initiation_date": record.get("recall_initiation_date") or "",
        "status": record.get("status") or "",
        "classification": record.get("classification") or "",
        "recalling_firm": record.get("recalling_firm") or "",
        "city": record.get("city") or "",
        "state": record.get("state") or "",
        "product_description": (record.get("product_description") or "").strip(),
        "reason_for_recall": (record.get("reason_for_recall") or "").strip(),
        "distribution_pattern": (record.get("distribution_pattern") or "").strip(),
        "matched_brands": brands,
        "source_url": "https://api.fda.gov/food/enforcement.json?search="
        + urllib.parse.quote(f'recall_number:"{record.get("recall_number")}"'),
    }


def main() -> None:
    end = date.today()
    start = end - timedelta(days=365)
    start_stamp = start.strftime("%Y%m%d")
    end_stamp = end.strftime("%Y%m%d")
    found: dict[str, dict] = {}
    errors = []
    queries = []
    for brand, phrase in BRAND_TERMS:
        search = (
            f"report_date:[{start_stamp} TO {end_stamp}] AND "
            f'(recalling_firm:"{phrase}" OR product_description:"{phrase}")'
        )
        queries.append({"brand": brand, "search": search})
        skip = 0
        while skip <= 400:
            status, payload = fetch_search(search, skip)
            if status == 404:
                break
            if status != 200:
                message = (payload.get("error") or {}).get("message") or f"HTTP {status}"
                errors.append(f"{brand}: {message}")
                break
            results = payload.get("results") or []
            if not results:
                break
            for record in results:
                number = record.get("recall_number") or f"no-number-{len(found)}"
                blob = " ".join(
                    [
                        record.get("recalling_firm") or "",
                        record.get("product_description") or "",
                    ]
                ).lower()
                if phrase.lower() not in blob:
                    continue
                existing = found.get(number)
                if existing:
                    if brand not in existing["matched_brands"]:
                        existing["matched_brands"].append(brand)
                else:
                    found[number] = slim(record, [brand])
            if len(results) < 100:
                break
            skip += 100
    recalls = sorted(found.values(), key=lambda item: item.get("report_date") or "", reverse=True)
    document = {
        "source": "https://api.fda.gov/food/enforcement.json",
        "checked": end.isoformat(),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "queries": queries,
        "errors": errors,
        "recall_count": len(recalls),
        "recalls": recalls,
    }
    RECALLS_JSON.parent.mkdir(parents=True, exist_ok=True)
    RECALLS_JSON.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(recalls)} matching recalls. API errors: {len(errors)}.")
    for line in errors:
        print(" ", line)


if __name__ == "__main__":
    main()
