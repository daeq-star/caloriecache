#!/usr/bin/env python3
"""Build the static CalorieCache site into dist/."""

from __future__ import annotations

import html
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    BASE_PATH,
    BASE_URL,
    KCAL_PER_LB_MAX,
    KCAL_PER_LB_MIN,
    KCAL_PER_SERVING_MAX,
    KCAL_PER_SERVING_MIN,
    RECALLS_JSON,
    ROOT,
    load_document,
    load_history,
)

DIST = ROOT / "dist"
SITE = ROOT / "site"
NEWSLETTER = ROOT / "newsletter"


def esc(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def money(value) -> str:
    if value is None or value == "":
        return "—"
    return f"${float(value):,.2f}"


def kcal(value) -> str:
    if value is None or value == "":
        return "—"
    number = float(value)
    if abs(number - round(number)) < 0.05:
        return f"{int(round(number)):,}"
    return f"{number:,.1f}"


def days_text(value) -> str:
    if value is None or value == "":
        return "—"
    return f"{float(value):,.1f}"


def shelf_text(value) -> str:
    if value is None or value == "":
        return "Not stated"
    return f"{int(value)} years"


def page(title: str, description: str, path: str, body: str, current: str, extra_head: str = "") -> str:
    canonical = BASE_URL + path
    nav = [
        ("Home", "/", "home"),
        ("How we calculate", "/how-we-calculate/", "method"),
        ("Recalls", "/recalls/", "recalls"),
        ("Newsletter", "/newsletter/", "newsletter"),
    ]
    links = []
    for label, href, key in nav:
        current_attr = ' aria-current="page"' if key == current else ""
        links.append(f'<a href="{BASE_PATH}{href}"{current_attr}>{label}</a>')
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="CalorieCache">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(canonical)}">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(description)}">
<link rel="icon" href="{BASE_PATH}/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{BASE_PATH}/assets/style.css">
{extra_head}
</head>
<body>
<a class="skip" href="#content">Skip to content</a>
<header class="site-header">
  <div class="wrap">
    <a class="brand" href="{BASE_PATH}/">Calorie<span>Cache</span></a>
    <nav>{''.join(links)}</nav>
  </div>
</header>
<main id="content">
  <div class="wrap">
{body}
  </div>
</main>
<footer>
  <div class="wrap">
    <p><strong>Affiliate disclosure.</strong> Product links go to the brand’s own store. The affiliate URL field on every kit is empty, so these are not paid placements. If that changes, the kit page will say so. Rankings follow listed price per 2,000 kcal and nothing else.</p>
    <p>2,000 kcal is a comparison yardstick used on food labels. It is not personal nutrition or medical advice. CalorieCache does not sell food.</p>
    <p>Prices and calorie claims are copied from official product pages. Check the linked page before you buy; stores change both.</p>
  </div>
</footer>
</body>
</html>
"""


def badges(kit: dict) -> str:
    parts = []
    if kit.get("calorie_is_estimate"):
        parts.append('<span class="badge est">est.</span>')
    if kit.get("calorie_check"):
        parts.append('<span class="badge check">calorie check</span>')
    if not kit.get("in_stock"):
        parts.append('<span class="badge out">Out of stock</span>')
    return " ".join(parts)


def data_attrs(kit: dict) -> str:
    shelf = kit.get("shelf_life_years")
    shelf_attr = str(int(shelf)) if shelf not in (None, "") else "-1"
    days = kit.get("days_at_2000_kcal")
    days_attr = "" if days in (None, "") else str(days)
    ppk = kit.get("price_per_2000_kcal")
    ppk_attr = "" if ppk in (None, "") else str(ppk)
    price = kit.get("price")
    price_attr = "" if price in (None, "") else str(price)
    name = f"{kit.get('brand', '')} {kit.get('name', '')}"
    return (
        f'data-brand="{esc(kit.get("brand"))}" data-name="{esc(name)}" '
        f'data-shelf="{shelf_attr}" data-days="{esc(days_attr)}" '
        f'data-ppk="{esc(ppk_attr)}" data-price="{esc(price_attr)}" '
        f'data-stock="{"in" if kit.get("in_stock") else "out"}"'
    )


def kit_href(kit: dict) -> str:
    return f"{BASE_PATH}/kit/{kit['id']}/"


def row(kit: dict, ranked: bool) -> str:
    rank_cell = '<td class="rank" data-label="Rank"></td>' if ranked else ""
    link = f'<a href="{kit_href(kit)}">{esc(kit["name"])}</a>'
    return f"""<tr {data_attrs(kit)}>
      {rank_cell}
      <td class="span" data-label="Kit"><span class="name">{link}</span><span class="sub">{esc(kit["brand"])} {badges(kit)}</span></td>
      <td data-label="Price">{money(kit.get("price"))}</td>
      <td data-label="Calories">{kcal(kit.get("total_calories"))}</td>
      <td data-label="Per 2,000 kcal">{money(kit.get("price_per_2000_kcal"))}</td>
      <td data-label="Days at 2,000 kcal">{days_text(kit.get("days_at_2000_kcal"))}</td>
      <td data-label="Shelf life">{shelf_text(kit.get("shelf_life_years"))}</td>
      <td data-label="Stock">{"In stock" if kit.get("in_stock") else "Out of stock"}</td>
    </tr>"""


def chart_svg(points: list[tuple[str, float]]) -> str:
    if not points:
        return "<p>No live price has been stored yet.</p>"
    width, height, pad = 640, 200, 28
    prices = [price for _date, price in points]
    low = min(prices)
    high = max(prices)
    if high == low:
        high = low + 1
    def x_at(index: int) -> float:
        if len(points) == 1:
            return width / 2
        return pad + (width - 2 * pad) * index / (len(points) - 1)
    def y_at(price: float) -> float:
        return pad + (height - 2 * pad) * (1 - (price - low) / (high - low))
    coords = " ".join(f"{x_at(i):.1f},{y_at(price):.1f}" for i, (_date, price) in enumerate(points))
    dots = []
    for i, (when, price) in enumerate(points):
        dots.append(
            f'<circle cx="{x_at(i):.1f}" cy="{y_at(price):.1f}" r="4" fill="#0e6b52">'
            f"<title>{esc(when)}: {money(price)}</title></circle>"
        )
    label = f"{points[0][0]} · {money(points[0][1])}"
    if len(points) > 1:
        label = f"{points[0][0]} {money(points[0][1])} → {points[-1][0]} {money(points[-1][1])}"
    return f"""<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Price history: {esc(label)}">
      <rect width="{width}" height="{height}" fill="#fffcf7"></rect>
      <polyline fill="none" stroke="#0e6b52" stroke-width="2" points="{coords}"></polyline>
      {''.join(dots)}
      <text x="{pad}" y="18" fill="#5e584e" font-size="13">{esc(label)}</text>
    </svg>"""


def history_for(kit_id: str, rows: list[dict]) -> list[tuple[str, float]]:
    points = []
    for row in rows:
        if row.get("kit_id") != kit_id:
            continue
        try:
            points.append((row["date"], float(row["price"])))
        except (TypeError, ValueError, KeyError):
            continue
    points.sort()
    return points


def shortfall(kit: dict) -> str:
    advertised = kit.get("advertised_days")
    actual = kit.get("days_at_2000_kcal")
    if not advertised or actual in (None, ""):
        return ""
    if float(actual) >= float(advertised) * 0.85:
        return ""
    return (
        f"The product name reads as about {int(advertised)} days "
        f"({esc(kit.get('advertised_days_basis') or 'from the product name')}). "
        f"At 2,000 kcal a day the calorie figure on the page covers {days_text(actual)} days."
    )


def render_markdown(text: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    out = []
    in_list = False

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    def inline(value: str) -> str:
        value = esc(value)
        value = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", value)
        value = re.sub(
            r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
            r'<a href="\2">\1</a>',
            value,
        )
        return value

    for line in lines:
        stripped = line.strip()
        if not stripped:
            close_list()
            continue
        if stripped.startswith("### "):
            close_list()
            out.append(f"<h3>{inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            close_list()
            out.append(f"<h2>{inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            close_list()
            out.append(f"<h1>{inline(stripped[2:])}</h1>")
        elif stripped.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(stripped[2:])}</li>")
        else:
            close_list()
            out.append(f"<p>{inline(stripped)}</p>")
    close_list()
    return "\n".join(out)


def write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def build() -> None:
    doc = load_document()
    kits = doc["kits"]
    history = load_history()
    recalls = {"recalls": [], "errors": [], "checked": "", "window_start": "", "window_end": "", "recall_count": 0}
    if RECALLS_JSON.exists():
        recalls = json.loads(RECALLS_JSON.read_text(encoding="utf-8"))
    verified = [kit for kit in kits if kit.get("verified")]
    unverified = [kit for kit in kits if not kit.get("verified")]
    verified.sort(key=lambda kit: (kit["price_per_2000_kcal"], kit["name"]))
    unverified.sort(key=lambda kit: (kit.get("brand") or "", kit.get("name") or ""))
    dates = [kit.get("date_checked") for kit in kits if kit.get("date_checked")]
    updated = max(dates) if dates else "unknown"
    stale = sum(1 for kit in kits if kit.get("last_price_error"))

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    shutil.copy(SITE / "favicon.svg", DIST / "favicon.svg")
    (DIST / "assets").mkdir()
    shutil.copy(SITE / "style.css", DIST / "assets" / "style.css")
    shutil.copy(SITE / "main.js", DIST / "assets" / "main.js")

    brands = sorted({kit["brand"] for kit in kits})
    brand_options = '<option value="">All brands</option>' + "".join(
        f'<option value="{esc(brand)}">{esc(brand)}</option>' for brand in brands
    )
    ranked_rows = "\n".join(row(kit, True) for kit in verified)
    other_rows = "\n".join(row(kit, False) for kit in unverified)
    stale_note = ""
    if stale:
        stale_note = f" {stale} kit{'s' if stale != 1 else ''} kept an older price because the store did not return a new one."
    home = f"""
    <h1>Emergency food, priced per 2,000 calories</h1>
    <p class="lede">Kits are sold by the bucket, the month, or the serving. Those labels are hard to compare. This page ranks food-storage kits from the brands’ own stores by listed price for 2,000 kcal, about one line on a nutrition label.</p>
    <p class="meta">Prices last updated {esc(updated)}.{stale_note} {len(verified)} kits have a price and a calorie figure. {len(unverified)} do not, and they are not ranked.</p>
    <form class="filters" action="{BASE_PATH}/">
      <label>Brand
        <select id="brand">{brand_options}</select>
      </label>
      <label>Shelf life
        <select id="shelf">
          <option value="">Any</option>
          <option value="10">10 years or more</option>
          <option value="20">20 years or more</option>
          <option value="25">25 years or more</option>
          <option value="30">30 years or more</option>
          <option value="unknown">Not stated</option>
        </select>
      </label>
      <label>Kit size at 2,000 kcal/day
        <select id="size">
          <option value="">Any</option>
          <option value="small">Under 14 days</option>
          <option value="medium">14–59 days</option>
          <option value="large">60–179 days</option>
          <option value="xlarge">180 days or more</option>
        </select>
      </label>
      <label>Stock
        <select id="stock">
          <option value="">Any</option>
          <option value="in">In stock</option>
          <option value="out">Out of stock</option>
        </select>
      </label>
      <label>Search
        <input id="q" type="search" placeholder="Name or brand">
      </label>
      <label>Sort ranked kits
        <select id="sort">
          <option value="data-ppk">Price per 2,000 kcal</option>
          <option value="data-price">Listed price</option>
          <option value="data-days">Days of food</option>
          <option value="data-shelf">Shelf life</option>
        </select>
      </label>
    </form>
    <p id="count" class="meta"></p>
    <div class="table-wrap">
      <table id="ranked">
        <thead>
          <tr>
            <th>Rank</th><th>Kit</th><th>Price</th><th>Calories</th><th>$ / 2,000 kcal</th><th>Days at 2,000</th><th>Shelf life</th><th>Stock</th>
          </tr>
        </thead>
        <tbody>
          {ranked_rows}
        </tbody>
      </table>
    </div>
    <h2>Not ranked</h2>
    <p>These products are on an official store, but the page did not give both a positive price and a single calorie total we could quote. They stay off the leaderboard.</p>
    <div class="table-wrap">
      <table id="unranked">
        <thead>
          <tr><th>Kit</th><th>Price</th><th>Calories</th><th>$ / 2,000 kcal</th><th>Days at 2,000</th><th>Shelf life</th><th>Stock</th></tr>
        </thead>
        <tbody>
          {other_rows}
        </tbody>
      </table>
    </div>
    <script src="{BASE_PATH}/assets/main.js"></script>
    """
    write(
        DIST / "index.html",
        page(
            "Emergency food kits ranked by price per 2,000 calories | CalorieCache",
            "Compare emergency food storage kits by listed price per 2,000 kcal, using calorie totals copied from official brand stores.",
            "/",
            home,
            "home",
        ),
    )

    for kit in kits:
        points = history_for(kit["id"], history)
        history_rows = "".join(
            f"<tr><td>{esc(when)}</td><td>{money(price)}</td></tr>" for when, price in points
        ) or "<tr><td colspan='2'>No stored price check yet.</td></tr>"
        quote = kit.get("calorie_source_quote") or "No calorie line was found on the product page."
        gap = shortfall(kit)
        gap_html = f'<p class="callout warn">{gap}</p>' if gap else ""
        check_html = ""
        if kit.get("calorie_check"):
            check_html = f'<p class="callout warn"><strong>Calorie check.</strong> {esc(kit.get("calorie_check_reason"))}</p>'
        notes = f"<p>{esc(kit['notes'])}</p>" if kit.get("notes") else ""
        reason = ""
        if not kit.get("verified"):
            reason = f"<p><strong>Not ranked.</strong> {esc(kit.get('unverified_reason') or 'Price or calories could not be verified.')}</p>"
        calc = ""
        if kit.get("verified"):
            calc = (
                f"<p>Price per 2,000 kcal = {money(kit['price'])} × 2,000 ÷ {kcal(kit['total_calories'])} "
                f"= <strong>{money(kit['price_per_2000_kcal'])}</strong>.</p>"
                f"<p>Days at 2,000 kcal = {kcal(kit['total_calories'])} ÷ 2,000 "
                f"= <strong>{days_text(kit['days_at_2000_kcal'])}</strong>.</p>"
            )
        weight = "Not listed"
        if kit.get("weight_grams"):
            pounds = float(kit["weight_grams"]) / 453.59237
            weight = f"{pounds:.1f} lb ({int(kit['weight_grams']):,} g)"
            if kit.get("weight_basis"):
                weight += f", {kit['weight_basis']}"
        per_lb = f"{kit['kcal_per_lb']:,.0f} kcal/lb" if kit.get("kcal_per_lb") else "—"
        affiliate = kit.get("affiliate_url") or ""
        product_link = kit.get("product_url") or "#"
        link_note = "Official product page"
        if affiliate:
            product_link = affiliate
            link_note = "Affiliate link"
        error = ""
        if kit.get("last_price_error"):
            error = f"<p class='meta'>Latest price check: {esc(kit['last_price_error'])}</p>"
        body = f"""
        <p class="meta"><a href="{BASE_PATH}/">All kits</a> · {esc(kit["brand"])}</p>
        <h1>{esc(kit["name"])}</h1>
        <p>{badges(kit)}</p>
        {reason}
        <div class="stats">
          <div class="stat"><b>{money(kit.get("price"))}</b><span>Listed price</span></div>
          <div class="stat"><b>{kcal(kit.get("total_calories"))}</b><span>Total calories</span></div>
          <div class="stat"><b>{money(kit.get("price_per_2000_kcal"))}</b><span>Per 2,000 kcal</span></div>
          <div class="stat"><b>{days_text(kit.get("days_at_2000_kcal"))}</b><span>Days at 2,000 kcal</span></div>
        </div>
        {gap_html}
        {check_html}
        {notes}
        <h2>Where the calories come from</h2>
        <p>{esc(kit.get("calorie_method") or "No method recorded.")}</p>
        <blockquote>{esc(quote)}</blockquote>
        {calc}
        <h2>Details</h2>
        <ul>
          <li>Servings: {esc(kit.get("servings") if kit.get("servings") not in (None, "") else "Not stated")}{(' (' + esc(kit.get("kcal_per_serving_basis")) + ', ' + str(kit.get("kcal_per_serving")) + ' kcal each)') if kit.get("kcal_per_serving") else ''}</li>
          <li>Shelf life: {shelf_text(kit.get("shelf_life_years"))}{(' — ' + esc(kit.get("shelf_life_quote"))) if kit.get("shelf_life_quote") else ''}</li>
          <li>Listed weight: {esc(weight)}. Calorie density: {per_lb}.</li>
          <li>Stock when checked: {"in stock" if kit.get("in_stock") else "out of stock"} on {esc(kit.get("date_checked") or "—")}.</li>
          <li>Nutrition text checked: {esc(kit.get("nutrition_checked") or "—")}.</li>
        </ul>
        <p><a href="{esc(product_link)}">{link_note}</a></p>
        {error}
        <h2>Price history</h2>
        {chart_svg(points)}
        <div class="table-wrap">
          <table>
            <thead><tr><th>Date</th><th>Price</th></tr></thead>
            <tbody>{history_rows}</tbody>
          </table>
        </div>
        """
        description = (
            f"{kit['brand']} {kit['name']}: {money(kit.get('price'))} listed, "
            f"{kcal(kit.get('total_calories'))} calories, "
            f"{money(kit.get('price_per_2000_kcal'))} per 2,000 kcal."
        )
        write(
            DIST / "kit" / kit["id"] / "index.html",
            page(
                f"{kit['name']} — {money(kit.get('price_per_2000_kcal'))} per 2,000 kcal | CalorieCache",
                description,
                f"/kit/{kit['id']}/",
                body,
                "",
            ),
        )

    method = f"""
    <h1>How we calculate</h1>
    <p class="lede">Every ranked number is either copied from a product page or multiplied from numbers the page states. If we cannot do that, the kit is not ranked.</p>
    <h2>Price per 2,000 kcal</h2>
    <p>2,000 kcal is the daily reference used on U.S. nutrition labels. It is a yardstick, not a meal plan.</p>
    <p><strong>Price per 2,000 kcal = listed price × 2,000 ÷ total calories.</strong></p>
    <p>Days of food at that pace = total calories ÷ 2,000. A kit sold as “30 days” can cover fewer days once you use 2,000 kcal instead of the brand’s own daily figure.</p>
    <h2>Where total calories come from</h2>
    <ol>
      <li><strong>A stated total.</strong> Lines such as “Total calories: 12,540” or the product’s structured-data field <code>calories_total</code>. The kit page quotes the line.</li>
      <li><strong>Servings × kcal per serving.</strong> Used when the page gives both and does not give a total. The method line says so.</li>
      <li><strong>est.</strong> Used when the page gives calories per day and the product name states a length (72-hour = 3 days, N-week = N × 7, N-month = N × 30, N-year = N × 365). The badge says est. A “2,000+ per day” claim is treated as a floor, so the price per calorie may look worse than it is.</li>
      <li><strong>est. from a smaller kit.</strong> When a longer kit’s listed price is a whole number of a shorter kit from the same store (within 2%), and that shorter kit states one calorie total, the estimate is that multiple of the stated total. A 1-year kit priced as 12 of the 30-day kit uses 12 × the 30-day total. The kit page names the shorter kit, the multiple, and the daily line from the longer kit’s own page.</li>
    </ol>
    <p>A generic sentence such as “an average adult needs 2,000 calories” is not the kit. If the page states two totals that disagree by more than 2 percent, or a range (“13,200 to 15,600”), the kit is not ranked. Pouch counts inside an ingredient list are not treated as the kit’s serving total.</p>
    <h2>Price</h2>
    <p>The price is the current variant price from the store’s public Shopify product JSON (<code>/products/&lt;handle&gt;.json</code>). If that file fails, the updater reads the price tag on the product HTML and keeps the last good price when both fail. Buy-one-get-one offers are not folded into the price. Out-of-stock kits stay in the table and can be filtered.</p>
    <h2>Calorie check</h2>
    <p>A kit stays ranked, with a <span class="badge check">calorie check</span> badge, when the figures look physically off:</p>
    <ul>
      <li>Above {KCAL_PER_LB_MAX:,.0f} kcal per pound, or below {KCAL_PER_LB_MIN:,.0f}. Pure fat is about 4,080 kcal per pound, so a mixed dry kit should land well under that. Weight is the store’s shipping weight when it publishes one, otherwise pounds in the product name.</li>
      <li>Or, when a serving count is known, outside {KCAL_PER_SERVING_MIN}–{KCAL_PER_SERVING_MAX} kcal per serving.</li>
    </ul>
    <h2>What is left off the ranking</h2>
    <p>No positive price, no single calorie total, or conflicting totals. Those kits are listed under “Not ranked” with the reason.</p>
    <h2>Shelf life and recalls</h2>
    <p>Shelf life is the brand’s own claim (“25-year shelf life”, “30-year taste guarantee”). “1 year after opening” is not used. Recalls come from the openFDA food enforcement API for the last 12 months, matched to these brand names. No matching record is not a safety certificate.</p>
    """
    write(
        DIST / "how-we-calculate" / "index.html",
        page(
            "How CalorieCache calculates price per 2,000 calories",
            "The formula, the est. badge, the calorie-check thresholds, and what keeps a kit off the ranking.",
            "/how-we-calculate/",
            method,
            "method",
        ),
    )

    recall_items = []
    for item in recalls.get("recalls") or []:
        brands = ", ".join(item.get("matched_brands") or [])
        recall_items.append(
            f"""<article class="callout">
            <h2>{esc(item.get("recalling_firm") or "Recall")} <span class="badge">{esc(item.get("classification") or "")}</span></h2>
            <p class="meta">{esc(item.get("report_date") or "")} · {esc(item.get("status") or "")} · matched {esc(brands)} · {esc(item.get("recall_number") or "")}</p>
            <p>{esc(item.get("product_description") or "")}</p>
            <p><strong>Reason.</strong> {esc(item.get("reason_for_recall") or "Not stated.")}</p>
            <p class="meta">{esc(item.get("distribution_pattern") or "")}</p>
            <p><a href="{esc(item.get("source_url") or "https://api.fda.gov/food/enforcement.json")}">openFDA record</a></p>
            </article>"""
        )
    if not recall_items:
        recall_items.append(
            "<p>No food-enforcement record in this window matched the brand names CalorieCache tracks.</p>"
        )
    error_html = ""
    if recalls.get("errors"):
        error_html = "<p class='callout warn'>The FDA request did not fully succeed: " + esc(
            "; ".join(recalls["errors"])
        ) + "</p>"
    recalls_body = f"""
    <h1>Recalls</h1>
    <p class="lede">Food-enforcement reports from openFDA for the last 12 months, kept only when the firm or the product text matches a brand this site tracks.</p>
    <p class="meta">Checked {esc(recalls.get("checked") or "—")}. Window {esc(recalls.get("window_start") or "—")} to {esc(recalls.get("window_end") or "—")}. {esc(recalls.get("recall_count") or 0)} matches.</p>
    {error_html}
    {''.join(recall_items)}
    <p class="meta">Source: <a href="https://api.fda.gov/food/enforcement.json">api.fda.gov/food/enforcement.json</a>. This is not a complete safety review.</p>
    """
    write(
        DIST / "recalls" / "index.html",
        page(
            "Food recall watch for emergency food brands | CalorieCache",
            "openFDA food enforcement reports from the last 12 months that match the emergency-food brands CalorieCache tracks.",
            "/recalls/",
            recalls_body,
            "recalls",
        ),
    )

    issue_path = NEWSLETTER / "issue-001.md"
    issue_html = "<p>Issue 001 has not been added yet.</p>"
    if issue_path.exists():
        issue_html = render_markdown(issue_path.read_text(encoding="utf-8"))
        write(
            DIST / "newsletter" / "issue-001" / "index.html",
            page(
                "Cheapest real calories this week — issue 001 | CalorieCache",
                "The five cheapest verified emergency food kits by price per 2,000 kcal, plus kits whose names promise more days than the calorie label supports.",
                "/newsletter/issue-001/",
                issue_html,
                "newsletter",
            ),
        )
    newsletter = f"""
    <h1>Newsletter</h1>
    <p class="lede">A short note when the ranking moves: the cheapest verified calories, and kits whose day-count in the name does not match 2,000 kcal a day.</p>
    <h2>Latest</h2>
    <p><a href="{BASE_PATH}/newsletter/issue-001/">Issue 001 — Cheapest real calories this week</a></p>
    <h2>Get the next one</h2>
    <div class="signup">
      <p class="todo"><strong>TODO:</strong> connect an email provider. This form is a placeholder. It does not send, store, or subscribe anyone. Wire it to a provider you control (for example a hosted form endpoint) before turning the fields on.</p>
      <form action="#" method="post">
        <label>Email
          <input type="email" name="email" placeholder="you@example.com" autocomplete="email" disabled>
        </label>
        <p><button type="submit" disabled>Subscribe</button></p>
      </form>
    </div>
    """
    write(
        DIST / "newsletter" / "index.html",
        page(
            "CalorieCache newsletter",
            "A plain newsletter on emergency-food price per 2,000 kcal. The signup form is not connected yet.",
            "/newsletter/",
            newsletter,
            "newsletter",
        ),
    )

    urls = ["/", "/how-we-calculate/", "/recalls/", "/newsletter/"]
    if issue_path.exists():
        urls.append("/newsletter/issue-001/")
    urls.extend(f"/kit/{kit['id']}/" for kit in kits)
    lastmod = updated if updated != "unknown" else ""
    body = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url in urls:
        body.append("  <url>")
        body.append(f"    <loc>{BASE_URL}{url}</loc>")
        if lastmod:
            body.append(f"    <lastmod>{esc(lastmod)}</lastmod>")
        body.append("  </url>")
    body.append("</urlset>")
    write(DIST / "sitemap.xml", "\n".join(body) + "\n")
    write(
        DIST / "robots.txt",
        "User-agent: *\nAllow: /\n\nSitemap: https://daeq-star.github.io/caloriecache/sitemap.xml\n",
    )
    print(f"Built {len(kits)} kit pages and {len(urls)} sitemap URLs into {DIST}")


if __name__ == "__main__":
    build()
