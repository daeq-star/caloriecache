"""Pull calorie, serving, and shelf-life claims out of a product page.

Only explicit claims are used. A kit the page does not quantify stays empty
so the caller can mark it unverified instead of guessing.
"""

from __future__ import annotations

import json
import re
from html import unescape

PER_DAY_RE = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<plus>\+)?\s*"
    r"(?:kcal|calories)\b.{0,60}?\b(?:per|/)\s*day",
    re.IGNORECASE,
)
# The number must sit on the same line as the label, or on a following line that
# is only a number. Letting whitespace cross lines pulled "2,000" out of the
# column header "2,000 Calorie Days".
TOTAL_LABELED_RE = re.compile(
    r"total\s+calories\s*[:\-–—]\s*(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
TOTAL_NEXT_LINE_RE = re.compile(
    r"total\s+calories[ \t]*\n[ \t]*(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)[ \t]*(?:\n|$)",
    re.IGNORECASE,
)
TOTAL_BEFORE_RE = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s+total\s+calories\b",
    re.IGNORECASE,
)
TOTAL_CALORIES_WORD_RE = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+)\s+calories\s+total\b",
    re.IGNORECASE,
)
# "56,650 (1,888 daily calories)" states the kit total and the daily figure.
TOTAL_DAILY_PAREN_RE = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+)\s*\(\s*[\d,]+\s*daily\s+calories\s*\)",
    re.IGNORECASE,
)
# A line that is only a calorie count, e.g. "24,540 calories".
TOTAL_BARE_RE = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+)\s+calories\b(?!\s+per\b)",
    re.IGNORECASE,
)
RANGE_RE = re.compile(
    r"total\s+calories[^.\n]{0,40}?(?P<a>\d{1,3}(?:,\d{3})+|\d+)\s+to\s+(?P<b>\d{1,3}(?:,\d{3})+|\d+)",
    re.IGNORECASE,
)
PER_SERVING_RE = re.compile(
    r"(?:(?:average|avg\.?)\s+)?calories\s+per\s+serving\s*[:\-–—]?\s*"
    r"(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"|"
    r"(?P<num2>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s+"
    r"(?:average\s+|avg\.?\s+)?calories\s+per\s+serving",
    re.IGNORECASE,
)
SERVINGS_RE = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+|\d+)\s*-?\s*servings?\b",
    re.IGNORECASE,
)
SHELF_RES = [
    re.compile(r"(?P<num>\d{1,2})\s*-?\s*year\s+taste\s+guarantee", re.I),
    re.compile(r"(?P<num>\d{1,2})\s*-?\s*year\s+shelf\s+life", re.I),
    re.compile(r"shelf\s+life\s+of\s+(?:up\s+to\s+)?(?P<num>\d{1,2})\s*years?", re.I),
    re.compile(r"(?:up\s+to|lasts?)\s+(?P<num>\d{1,2})\s*years?\s*(?:on\s+the\s+shelf|shelf\s+life)?", re.I),
]


def html_to_text(html: str) -> str:
    text = unescape(html or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"(?is)<script\b.*?</script>", " ", text)
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|li|div|h\d|tr|td|th)>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    return text.strip()


def parse_number(raw) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    match = re.search(r"\d[\d,]*(?:\.\d+)?", str(raw))
    if not match:
        return None
    return float(match.group(0).replace(",", ""))


def days_from_title(title: str) -> tuple[int | None, str]:
    """Marketing length printed in the product name, not a calorie calculation."""
    text = title or ""
    if re.search(r"72\s*-?\s*hours?", text, re.I):
        return 3, "title: 72-hour → 3 days"
    day = re.search(r"(\d+)\s*-?\s*days?", text, re.I)
    week = re.search(r"(\d+)\s*-?\s*weeks?", text, re.I)
    month = re.search(r"(\d+)\s*-?\s*months?", text, re.I)
    year = re.search(r"(\d+)\s*-?\s*years?", text, re.I)
    # A day count in the name is more precise than "1-month".
    if day:
        days = int(day.group(1))
        return days, f"title: {day.group(0).strip()} → {days} days"
    if week:
        count = int(week.group(1))
        return count * 7, f"title: {week.group(0).strip()} → {count * 7} days"
    if month:
        count = int(month.group(1))
        return count * 30, f"title: {month.group(0).strip()} → {count * 30} days (30 days per named month)"
    if year:
        count = int(year.group(1))
        return count * 365, f"title: {year.group(0).strip()} → {count * 365} days"
    if re.search(r"\bone\s+year\b", text, re.I):
        return 365, "title: one year → 365 days"
    return None, ""


def sentence_around(text: str, start: int, end: int) -> str:
    left = 0
    for marker in ("\n", ". "):
        pos = text.rfind(marker, 0, start)
        if pos != -1:
            left = max(left, pos + len(marker))
    right_candidates = []
    for marker in ("\n", ". "):
        pos = text.find(marker, end)
        if pos != -1:
            right_candidates.append(pos + (0 if marker == "\n" else 1))
    right = min(right_candidates) if right_candidates else len(text)
    snippet = re.sub(r"\s+", " ", text[left:right]).strip(" -\u2013")
    return snippet[:320]


def _jsonld_products(html: str) -> list[dict]:
    products = []
    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html or "",
        flags=re.I | re.S,
    ):
        raw = block.strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        products.extend(_walk_products(data))
    return products


def _walk_products(node) -> list[dict]:
    found = []
    if isinstance(node, dict):
        kind = node.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "Product" in kinds:
            found.append(node)
        for value in node.values():
            found.extend(_walk_products(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_products(item))
    return found


def pick_jsonld_product(html: str, handle: str, sku: str, title: str) -> dict | None:
    products = _jsonld_products(html)
    if not products:
        return None
    if sku:
        for product in products:
            if str(product.get("sku") or "") == str(sku):
                return product
    if handle:
        for product in products:
            blob = json.dumps(product.get("offers") or "")
            if handle in blob or handle.replace("®", "") in blob:
                return product
    if len(products) == 1:
        return products[0]
    title_words = set(re.findall(r"[a-z0-9]+", (title or "").lower()))
    best = None
    best_score = -1
    for product in products:
        name = str(product.get("name") or "")
        words = set(re.findall(r"[a-z0-9]+", name.lower()))
        score = len(title_words & words)
        if score > best_score:
            best = product
            best_score = score
    return best if best_score > 0 else None


def jsonld_properties(product: dict | None) -> dict:
    props = {}
    if not product:
        return props
    for item in product.get("additionalProperty") or []:
        if isinstance(item, dict) and item.get("name"):
            props[str(item["name"])] = item.get("value")
            props[f"{item['name']}__raw"] = json.dumps(item, ensure_ascii=False)
    return props


def _ignore_daily_sentence(sentence: str) -> bool:
    """Drop the generic 'an adult needs 2,000 kcal' line, which is not the kit."""
    return bool(
        re.search(
            r"average adult|you may want|need more calories|needs about|"
            r"needs approx|to meet their energy|supplement your daily",
            sentence,
            re.I,
        )
    )


def _collect(pattern, text: str, floor: int = 400) -> list[tuple[float, str]]:
    found = []
    for match in pattern.finditer(text or ""):
        sentence = sentence_around(text, match.start(), match.end())
        if re.search(r"\bper\s+serving\b|\bper\s+meal\b|\ba day\b|\bper\s+day\b|\bdaily\b", sentence, re.I):
            # A daily figure is not a kit total, unless the sentence also labels a total.
            if not re.search(r"total\s+calories|\d[\d,]*\s*\(", sentence, re.I):
                continue
        number = parse_number(match.group("num"))
        if number is None or number < floor:
            continue
        found.append((number, sentence))
    return found


def find_totals(text: str) -> list[tuple[float, str]]:
    """Kit totals, preferring an explicit 'Total calories:' label.

    A nutrition line such as '409 Total Calories' for one food is kept only
    when the page does not also label a much larger kit total.
    """
    text = text or ""
    labeled = []
    labeled += _collect(TOTAL_LABELED_RE, text)
    labeled += _collect(TOTAL_NEXT_LINE_RE, text)
    labeled += _collect(TOTAL_DAILY_PAREN_RE, text)
    other = []
    other += _collect(TOTAL_BEFORE_RE, text)
    other += _collect(TOTAL_CALORIES_WORD_RE, text)
    other += _collect(TOTAL_BARE_RE, text, floor=1000)

    def unique(items):
        seen = set()
        out = []
        for number, quote in items:
            key = (number, quote)
            if key in seen:
                continue
            seen.add(key)
            out.append((number, quote))
        return out

    labeled = unique(labeled)
    other = unique(other)
    labeled_values = sorted({item[0] for item in labeled})
    if labeled_values:
        if len(labeled_values) == 1 or (max(labeled_values) - min(labeled_values)) / max(labeled_values) <= 0.02:
            return labeled
        return labeled  # caller treats a wide spread as a conflict
    if not other:
        return []
    # Drop component-sized totals when a clearly larger one is also stated.
    largest = max(item[0] for item in other)
    kept = [item for item in other if item[0] >= largest * 0.8]
    return unique(kept)


def find_calorie_range(text: str) -> str:
    match = RANGE_RE.search(text or "")
    if not match:
        return ""
    return sentence_around(text, match.start(), match.end())


def find_per_day(text: str) -> list[dict]:
    found = []
    for match in PER_DAY_RE.finditer(text or ""):
        sentence = sentence_around(text, match.start(), match.end())
        if _ignore_daily_sentence(sentence):
            continue
        number = parse_number(match.group("num"))
        if number is None or number < 200 or number > 6000:
            continue
        is_floor = bool(match.group("plus")) or bool(re.search(rf"{re.escape(match.group('num'))}\s*\+", match.group(0)))
        found.append({"value": number, "floor": is_floor, "quote": sentence})
    unique = []
    seen = set()
    for item in found:
        key = (item["value"], item["floor"], item["quote"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def find_per_serving(text: str) -> tuple[float | None, str]:
    match = PER_SERVING_RE.search(text or "")
    if not match:
        return None, ""
    number = parse_number(match.group("num") or match.group("num2"))
    if number is None:
        return None, ""
    return number, sentence_around(text, match.start(), match.end())


def find_servings(title: str, text: str) -> tuple[float | None, str]:
    title_match = SERVINGS_RE.search(title or "")
    if title_match:
        return parse_number(title_match.group("num")), f"Product name: {title_match.group(0).strip()}."
    # Only an explicit kit total. Pouch lines ("6 total servings") are not the kit.
    match = re.search(
        r"total\s+servings\s*[:\-–—]?\s*(?P<num>\d{1,3}(?:,\d{3})+|\d+)",
        text or "",
        re.I,
    )
    if match:
        return parse_number(match.group("num")), sentence_around(text, match.start(), match.end())
    return None, ""


def find_shelf_life(text: str) -> tuple[int | None, str]:
    years = []
    for pattern in SHELF_RES:
        for match in pattern.finditer(text or ""):
            sentence = sentence_around(text, match.start(), match.end())
            tail = (text or "")[match.end(): match.end() + 24]
            if re.match(r"\s*after opening", tail, re.I):
                continue
            number = int(match.group("num"))
            if 5 <= number <= 40:
                years.append((number, sentence))
    if not years:
        return None, ""
    distinct = {item[0] for item in years}
    if len(distinct) > 1:
        # "20 to 30 years" is a range. Keep the claim, but do not pick one end.
        quoted = "; ".join(dict.fromkeys(item[1] for item in years))
        return None, f"Conflicting shelf-life claims: {quoted[:300]}"
    return years[0][0], years[0][1]


def extract_nutrition(title: str, body_text: str, props: dict | None = None) -> dict:
    """Return calorie fields. Empty total_calories means unverified.

    ``props`` comes from the matching product's JSON-LD additionalProperty.
    ``body_text`` must be the product description, not the whole HTML page,
    so comparison widgets for other kits are not treated as this kit.
    """
    props = props or {}
    result = {
        "total_calories": None,
        "calorie_is_estimate": False,
        "calorie_method": "",
        "calorie_source_quote": "",
        "servings": None,
        "kcal_per_serving": None,
        "kcal_per_serving_basis": "",
        "shelf_life_years": None,
        "shelf_life_quote": "",
        "advertised_days": None,
        "advertised_days_basis": "",
        "exclude_from_ranking": False,
        "unverified_reason": "",
        "notes": "",
    }
    advertised, basis = days_from_title(title)
    if props.get("duration") is not None and advertised is None:
        duration = parse_number(props.get("duration"))
        if duration:
            advertised = int(duration)
            basis = f"structured data duration: {int(duration)} days"
    result["advertised_days"] = advertised
    result["advertised_days_basis"] = basis

    shelf_years = parse_number(props.get("shelf_life"))
    if shelf_years:
        result["shelf_life_years"] = int(shelf_years)
        raw = props.get("shelf_life__raw") or f"shelf_life: {int(shelf_years)} years"
        result["shelf_life_quote"] = raw
    else:
        years, quote = find_shelf_life(body_text)
        result["shelf_life_years"] = years
        result["shelf_life_quote"] = quote
        if years is None and quote.startswith("Conflicting"):
            result["notes"] = quote

    servings = parse_number(props.get("servings_total"))
    servings_quote = ""
    if servings:
        servings_quote = props.get("servings_total__raw") or f"servings_total: {int(servings)}"
    else:
        servings, servings_quote = find_servings(title, body_text)
    if servings:
        result["servings"] = int(servings) if float(servings).is_integer() else servings

    per_serving, per_serving_quote = find_per_serving(body_text)

    jsonld_total = parse_number(props.get("calories_total"))
    totals = find_totals(body_text)
    distinct_totals = sorted({item[0] for item in totals})
    calorie_range = find_calorie_range(body_text)

    if jsonld_total and jsonld_total >= 400:
        result["total_calories"] = int(round(jsonld_total))
        result["calorie_method"] = "total calories stated in the product page structured data (calories_total)"
        result["calorie_source_quote"] = props.get("calories_total__raw") or (
            f'{{"name": "calories_total", "value": {int(round(jsonld_total))}, "unitText": "kcal"}}'
        )
    elif len(distinct_totals) > 1 and (max(distinct_totals) - min(distinct_totals)) / max(distinct_totals) > 0.02:
        result["exclude_from_ranking"] = True
        quoted = " | ".join(item[1] for item in totals[:3])
        result["unverified_reason"] = "product description states more than one total-calorie figure"
        result["calorie_source_quote"] = quoted[:500]
        result["notes"] = result["unverified_reason"]
    elif totals:
        number, quote = totals[0]
        result["total_calories"] = int(round(number))
        result["calorie_method"] = "total calories stated on the product page"
        result["calorie_source_quote"] = quote
    else:
        daily = find_per_day(body_text)
        jsonld_daily = parse_number(props.get("calories_per_day"))
        if jsonld_daily and not daily:
            raw = props.get("calories_per_day__raw") or f"calories_per_day: {jsonld_daily}"
            daily = [{"value": jsonld_daily, "floor": False, "quote": raw}]
        exact = [item for item in daily if not item["floor"]]
        floors = [item for item in daily if item["floor"]]
        chosen_pool = exact or floors
        distinct = sorted({item["value"] for item in chosen_pool})
        if len(distinct) > 1 and (max(distinct) - min(distinct)) / max(distinct) > 0.02:
            result["exclude_from_ranking"] = True
            result["unverified_reason"] = "product description states more than one calories-per-day figure"
            result["calorie_source_quote"] = " | ".join(item["quote"] for item in chosen_pool[:3])[:500]
            result["notes"] = result["unverified_reason"]
        elif chosen_pool and advertised:
            item = chosen_pool[0]
            total = int(round(item["value"] * advertised))
            result["total_calories"] = total
            result["calorie_is_estimate"] = True
            floor_note = " (brand stated a floor, so this total may be low)" if item["floor"] else ""
            result["calorie_method"] = (
                f"est. {item['value']:g} kcal/day × {advertised} advertised days{floor_note}"
            )
            result["calorie_source_quote"] = (
                f"{item['quote']} Multiplied by advertised length ({basis})."
            )
            if item["floor"]:
                result["notes"] = (
                    "The brand published a calories-per-day floor rather than an exact total. "
                    "The estimate uses that floor, so price per 2,000 kcal may be overstated."
                )
        elif result["servings"] and per_serving:
            total = int(round(result["servings"] * per_serving))
            result["total_calories"] = total
            result["kcal_per_serving"] = per_serving
            result["kcal_per_serving_basis"] = "stated"
            result["calorie_method"] = "servings × kcal/serving from the product page"
            result["calorie_source_quote"] = (
                f"{servings_quote} {per_serving_quote}"
            ).strip()
        elif calorie_range:
            result["exclude_from_ranking"] = True
            result["unverified_reason"] = "product page gives a calorie range, not a single total"
            result["calorie_source_quote"] = calorie_range

    if result["total_calories"] and result["servings"] and not result["kcal_per_serving"]:
        result["kcal_per_serving"] = round(result["total_calories"] / result["servings"], 1)
        result["kcal_per_serving_basis"] = "computed from total calories ÷ servings"
    elif per_serving and not result["kcal_per_serving"]:
        result["kcal_per_serving"] = per_serving
        result["kcal_per_serving_basis"] = "stated"

    return result
