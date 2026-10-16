"""Unit tests for ranking math and calorie parsing. No network."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from update_prices import dollars_from_cents, price_from_ajax_js, price_from_product_json  # noqa: E402
from common import (  # noqa: E402
    calorie_check,
    days_at_2000_kcal,
    price_per_2000_kcal,
    upsert_history,
)
from extract import apply_stated_multiples, days_from_title, extract_nutrition, named_months  # noqa: E402


class MetricsTest(unittest.TestCase):
    def test_price_per_2000(self):
        # 36,480 kcal at $299 is 299 * 2000 / 36480 = 16.3925...
        self.assertEqual(price_per_2000_kcal(299, 36480), 16.39)
        self.assertIsNone(price_per_2000_kcal(0, 1000))
        self.assertIsNone(price_per_2000_kcal(10, None))

    def test_days(self):
        self.assertEqual(days_at_2000_kcal(36480), 18.24)
        self.assertEqual(days_at_2000_kcal(4000), 2.0)

    def test_calorie_check_bounds(self):
        # 1,500 kcal/lb is ordinary dry food: 1500 * (453.6/453.59237) grams.
        flagged, _reason = calorie_check(1500, 453.59237, 4)
        self.assertFalse(flagged)
        flagged, reason = calorie_check(5000, 453.59237, 4)
        self.assertTrue(flagged)
        self.assertIn("per pound", reason)
        flagged, reason = calorie_check(200, 453.59237, 4)
        self.assertTrue(flagged)
        self.assertIn("below", reason)

    def test_serving_density_flag(self):
        flagged, reason = calorie_check(100, None, 10)
        self.assertTrue(flagged)
        self.assertIn("per serving", reason)

    def test_ajax_price_is_cents_and_keeps_stock(self):
        self.assertEqual(dollars_from_cents(15199), 151.99)
        body = json.dumps({"variants": [{"id": 5, "price": 3900, "available": True}]})
        price, stock = price_from_ajax_js(body, 5)
        self.assertEqual(price, 39.0)
        self.assertTrue(stock)

    def test_product_json_without_available_does_not_mean_out_of_stock(self):
        body = json.dumps({"product": {"variants": [{"id": 5, "price": "151.99"}]}})
        price, stock = price_from_product_json(body, 5)
        self.assertEqual(price, 151.99)
        self.assertIsNone(stock)

    def test_history_is_idempotent_per_day(self):
        first = upsert_history([], [{"date": "2026-10-16", "kit_id": "a", "price": "10", "in_stock": "true", "source": "shopify_json"}])
        second = upsert_history(first, [{"date": "2026-10-16", "kit_id": "a", "price": "11", "in_stock": "false", "source": "html_fallback"}])
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["price"], "11")
        third = upsert_history(second, [{"date": "2026-10-17", "kit_id": "a", "price": "12", "in_stock": "true", "source": "shopify_json"}])
        self.assertEqual(len(third), 2)


class ExtractTest(unittest.TestCase):
    def test_title_days(self):
        self.assertEqual(days_from_title("4-Week Emergency Survival Food Kit")[0], 28)
        self.assertEqual(days_from_title("72-Hour Emergency Survival Food Kit")[0], 3)
        self.assertEqual(days_from_title("NEW 1-Month (30-Day) Emergency Food Kit")[0], 30)
        self.assertEqual(days_from_title("3-Month Emergency Food Supply")[0], 90)
        self.assertEqual(days_from_title("1-Year Emergency Food Supply")[0], 365)

    def test_explicit_total(self):
        text = "Packed for storage.\nTotal calories: 12,540\nShelf life of 25 years."
        parsed = extract_nutrition("60 Serving Entree Bucket", text, {})
        self.assertEqual(parsed["total_calories"], 12540)
        self.assertFalse(parsed["calorie_is_estimate"])
        self.assertIn("12,540", parsed["calorie_source_quote"])
        self.assertEqual(parsed["servings"], 60)
        self.assertEqual(parsed["shelf_life_years"], 25)

    def test_per_day_is_marked_estimate(self):
        text = (
            "The kit contains 45 freeze-dried food pouches, providing approximately "
            "1,732 calories per day. Just add water."
        )
        parsed = extract_nutrition("15-Day Emergency Food Supply Kit", text, {})
        self.assertTrue(parsed["calorie_is_estimate"])
        self.assertEqual(parsed["total_calories"], 1732 * 15)
        self.assertTrue(parsed["calorie_method"].startswith("est."))
        self.assertIn("1,732 calories per day", parsed["calorie_source_quote"])

    def test_jsonld_total_beats_daily_estimate(self):
        props = {
            "calories_total": 36480,
            "calories_total__raw": '{"name": "calories_total", "value": 36480, "unitText": "kcal"}',
            "calories_per_day": 1302,
            "servings_total": 192,
            "shelf_life": 25,
            "shelf_life__raw": '{"name": "shelf_life", "value": 25, "unitText": "years"}',
        }
        text = "An average adult needs about 2,000 calories a day."
        parsed = extract_nutrition("4-Week Emergency Survival Food Kit", text, props)
        self.assertEqual(parsed["total_calories"], 36480)
        self.assertFalse(parsed["calorie_is_estimate"])
        self.assertEqual(parsed["servings"], 192)
        self.assertEqual(parsed["shelf_life_years"], 25)
        self.assertIn("calories_total", parsed["calorie_source_quote"])

    def test_generic_adult_allowance_is_not_the_kit(self):
        text = "An average adult needs about 2,000 calories per day to meet their energy needs."
        parsed = extract_nutrition("Mystery Bucket", text, {})
        self.assertIsNone(parsed["total_calories"])

    def test_conflicting_totals_are_not_ranked(self):
        text = "Total calories: 10,000\nAlso listed total calories: 40,000"
        parsed = extract_nutrition("Example Kit", text, {})
        self.assertTrue(parsed["exclude_from_ranking"])
        self.assertIsNone(parsed["total_calories"])

    def test_spec_table_does_not_steal_two_thousand(self):
        text = "Total Calories: 24,520\nServings\nTotal Calories\n2,000 Calorie Days\n409 Total Calories"
        parsed = extract_nutrition("60 Serving Breakfast Bucket", text, {})
        self.assertEqual(parsed["total_calories"], 24520)
        self.assertFalse(parsed["exclude_from_ranking"])

    def test_calories_total_word_order(self):
        text = "Six #10 cans. 110 servings. 20,240 calories.\n20,240 calories total — balanced fuel."
        parsed = extract_nutrition("14-Day Emergency Food Kit", text, {})
        self.assertEqual(parsed["total_calories"], 20240)
        self.assertEqual(parsed["advertised_days"], 14)

    def test_parenthetical_daily_total(self):
        text = "With 1,888 calories and 45 grams of protein per day, this kit feeds one person.\nCalories\n56,650 (1,888 daily calories)"
        parsed = extract_nutrition("NEW 1-Month (30-Day) Emergency Food Kit", text, {})
        self.assertEqual(parsed["total_calories"], 56650)
        self.assertFalse(parsed["calorie_is_estimate"])

    def test_per_day_with_words_between(self):
        text = "With 1,888 calories and 45 grams of protein per day, this kit provides three full months."
        parsed = extract_nutrition("3-Month Emergency Food Kit", text, {})
        self.assertTrue(parsed["calorie_is_estimate"])
        self.assertEqual(parsed["total_calories"], 1888 * 90)

    def test_pouch_servings_are_not_the_kit(self):
        text = "9 pouches of Teriyaki Rice (54 total servings)\nIncludes 6 total buckets\nTotal calories: 187,620\nTo avoid waste, most pouches conveniently contain 6 servings"
        parsed = extract_nutrition("3 Month Emergency Food Supply", text, {})
        self.assertEqual(parsed["total_calories"], 187620)
        self.assertIsNone(parsed["servings"])
        self.assertFalse(parsed["exclude_from_ranking"])

    def test_calorie_range_is_not_a_point_estimate(self):
        text = "Total Calories per Case: 13,200 to 15,600"
        parsed = extract_nutrition("12 Complete Meal MRE Food Supply", text, {})
        self.assertIsNone(parsed["total_calories"])
        self.assertTrue(parsed["exclude_from_ranking"])
        self.assertIn("13,200", parsed["calorie_source_quote"])

    def test_opening_year_is_not_shelf_life(self):
        text = "Built to last up to 25 years unopened, and up to 1 year after opening."
        parsed = extract_nutrition("Sample Kit", text, {})
        self.assertEqual(parsed["shelf_life_years"], 25)

    def test_servings_times_label_calories(self):
        text = "Each pouch is 250 calories per serving. Nothing else is stated."
        parsed = extract_nutrition("40 Serving Side Bucket", text, {})
        self.assertEqual(parsed["total_calories"], 10000)
        self.assertIn("servings × kcal/serving", parsed["calorie_method"])
        self.assertFalse(parsed["calorie_is_estimate"])


def _kit(**overrides):
    kit = {
        "brand": "Emergency Essentials",
        "store_domain": "beprepared.com",
        "name": "Kit",
        "price": 151.99,
        "total_calories": 56650,
        "calorie_is_estimate": False,
        "calorie_method": "total calories stated on the product page",
        "calorie_source_quote": "56,650 (1,888 daily calories)",
        "advertised_days": 30,
        "advertised_days_basis": "title: 30-Day → 30 days",
        "exclude_from_ranking": False,
        "servings": None,
        "kcal_per_serving_basis": "",
    }
    kit.update(overrides)
    return kit


class StatedMultipleTest(unittest.TestCase):
    def test_named_year_is_twelve_months(self):
        self.assertEqual(named_months(_kit(name="NEW 1-Month (30-Day) Emergency Food Kit")), 1)
        self.assertEqual(
            named_months(_kit(
                name="NEW 3-Month Emergency Food Kit",
                advertised_days=90,
                advertised_days_basis="title: 3-Month → 90 days (30 days per named month)",
            )),
            3,
        )
        self.assertEqual(
            named_months(_kit(
                name="NEW 1 Year Emergency Food Kit",
                advertised_days=365,
                advertised_days_basis="title: 1 Year → 365 days",
            )),
            12,
        )
        self.assertIsNone(named_months(_kit(name="2-Week True Survival Food Kit", advertised_days=14, advertised_days_basis="title: 2-Week → 14 days")))

    def test_year_uses_twelve_times_the_stated_month_total(self):
        month = _kit(name="NEW 1-Month (30-Day) Emergency Food Kit - Emergency Essentials")
        three = _kit(
            name="NEW 3-Month Emergency Food Kit - Emergency Essentials",
            advertised_days=90,
            advertised_days_basis="title: 3-Month → 90 days (30 days per named month)",
            price=455.97,
            total_calories=1888 * 90,
            calorie_is_estimate=True,
            calorie_method="est. 1888 kcal/day × 90 advertised days",
            calorie_source_quote="1,888 calories per day. Multiplied by advertised length (title: 3-Month → 90 days).",
        )
        six = _kit(
            name="NEW 6-Month Emergency Food Kit - Emergency Essentials",
            advertised_days=180,
            advertised_days_basis="title: 6-Month → 180 days (30 days per named month)",
            price=911.94,
            total_calories=1888 * 180,
            calorie_is_estimate=True,
            calorie_method="est. 1888 kcal/day × 180 advertised days",
            calorie_source_quote="1,888 calories per day. Multiplied by advertised length (title: 6-Month → 180 days).",
        )
        year = _kit(
            name="NEW 1 Year Emergency Food Kit - Emergency Essentials",
            advertised_days=365,
            advertised_days_basis="title: 1 Year → 365 days",
            price=1823.88,
            total_calories=1888 * 365,
            calorie_is_estimate=True,
            calorie_method="est. 1888 kcal/day × 365 advertised days",
            calorie_source_quote="With 1,888 calories and 45 grams of protein per day. Multiplied by advertised length (title: 1 Year → 365 days).",
        )
        other = _kit(
            name="2-Week True Survival Food Kit",
            advertised_days=14,
            advertised_days_basis="title: 2-Week → 14 days",
            price=309.90,
            total_calories=31155,
            calorie_source_quote="Total Calories 31,155",
        )
        kits = [month, three, six, year, other]
        apply_stated_multiples(kits)
        apply_stated_multiples(kits)
        self.assertEqual(month["total_calories"], 56650)
        self.assertFalse(month["calorie_is_estimate"])
        self.assertEqual(other["total_calories"], 31155)
        self.assertEqual(three["total_calories"], 56650 * 3)
        self.assertEqual(six["total_calories"], 56650 * 6)
        self.assertEqual(year["total_calories"], 56650 * 12)
        self.assertTrue(year["calorie_is_estimate"])
        self.assertIn("12 × 56,650", year["calorie_method"])
        self.assertIn("NEW 1-Month (30-Day)", year["calorie_method"])
        self.assertIn("56,650 (1,888 daily calories)", year["calorie_source_quote"])
        self.assertIn("1,888 calories and 45 grams of protein per day", year["calorie_source_quote"])

    def test_another_estimate_is_not_a_base_total(self):
        month = _kit(
            brand="Mountain House",
            store_domain="mountainhouse.com",
            name="30-Day Emergency Food Supply Kit",
            price=939.99,
            total_calories=1732 * 30,
            calorie_is_estimate=True,
            calorie_method="est. 1732 kcal/day × 30 advertised days",
            calorie_source_quote="approximately 1,732 calories per day",
        )
        year = _kit(
            brand="Mountain House",
            store_domain="mountainhouse.com",
            name="1-Year Emergency Food Supply",
            advertised_days=365,
            advertised_days_basis="title: 1-Year → 365 days",
            price=round(939.99 * 12, 2),
            total_calories=1732 * 365,
            calorie_is_estimate=True,
            calorie_method="est. 1732 kcal/day × 365 advertised days",
            calorie_source_quote="approximately 1,732 calories per day",
        )
        apply_stated_multiples([month, year])
        self.assertEqual(year["total_calories"], 1732 * 365)
        self.assertIn("kcal/day", year["calorie_method"])

    def test_mismatched_price_does_not_copy_the_smaller_total(self):
        month = _kit(name="30-Day Kit")
        year = _kit(
            name="1 Year Kit",
            advertised_days=365,
            advertised_days_basis="title: 1 Year → 365 days",
            price=2000.00,
            total_calories=1888 * 365,
            calorie_is_estimate=True,
            calorie_method="est. 1888 kcal/day × 365 advertised days",
            calorie_source_quote="1,888 calories per day",
        )
        apply_stated_multiples([month, year])
        self.assertEqual(year["total_calories"], 1888 * 365)


if __name__ == "__main__":
    unittest.main()
