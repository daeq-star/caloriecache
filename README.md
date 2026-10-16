# CalorieCache

Emergency and survival food kits, ranked by listed price per 2,000 kcal.

Stores sell kits by the bucket, the month, or the serving. Those labels are hard to compare. CalorieCache copies the price and the calorie claim from each brand’s own store and ranks kits by:

**listed price × 2,000 ÷ total calories**

The public site is meant to be hosted at [https://daeq-star.github.io/caloriecache/](https://daeq-star.github.io/caloriecache/). Links and assets use the `/caloriecache/` base path so a GitHub project site works.

2,000 kcal is the reference line on a nutrition label. It is a comparison yardstick, not diet advice.

## What is in the ranking

Tracked stores:

- Emergency Essentials (beprepared.com)
- ReadyWise (readywise.com)
- Augason Farms (augasonfarms.com)
- Mountain House (mountainhouse.com)
- Legacy Food Storage (legacyfoodstorage.com)
- Valley Food Storage (valleyfoodstorage.com)
- 4Patriots (4patriots.com)
- Nutrient Survival (nutrientsurvival.com)
- Peak Refuel (peakrefuel.com)

A kit is ranked only when the store published both a positive price and a single calorie total (or calories per day, which is marked **est.**). When a longer kit is priced as a whole number of a shorter kit that states a calorie total, the estimate is that multiple of the stated total. A 1-year kit priced as 12 of the 30-day kit uses 12 × the 30-day total. Kits we could not verify are listed separately and are not ranked. A **calorie check** badge means the calories-per-pound (or per serving) look physically off. Those kits stay on the board so the odd figure is visible.

Prices and stock come from each store’s public Shopify product endpoint (`/products/<handle>.js`, which includes whether the variant is available; price is in cents). `/products/<handle>.json` is the fallback for the dollar price. The product HTML is a last resort. Calorie text is quoted on the kit page. Nothing here is invented to fill a gap. Affiliate URLs are empty.

## Run it locally

Python 3.11 or newer. The standard library is enough; there is no install step.

```bash
python3 -m unittest tests.test_metrics
python3 scripts/harvest_kits.py    # re-read calorie claims from product pages
python3 scripts/update_prices.py   # refresh prices; append today's row to price history
python3 scripts/recalls.py         # openFDA food enforcement, last 12 months
python3 scripts/build_site.py      # write dist/
```

`harvest_kits.py` is the slow one. Day-to-day updates only need `update_prices.py`, `recalls.py`, and `build_site.py`. A failed price fetch keeps the last good price and does not add a history row. Running the price update twice on the same day replaces that day’s row instead of duplicating it.

Preview the project-site path:

```bash
python3 scripts/build_site.py
mkdir -p /tmp/caloriecache-preview
ln -sfn "$PWD/dist" /tmp/caloriecache-preview/caloriecache
python3 -m http.server 8765 --directory /tmp/caloriecache-preview
```

Open `http://127.0.0.1:8765/caloriecache/`.

## Data files

| File | Role |
| --- | --- |
| `data/kits.json` | Full records: price, calories, quote, method, stock, flags |
| `data/kits.csv` | The same kits in a spreadsheet |
| `data/price_history.csv` | One row per kit per day after a successful price fetch |
| `data/recalls.json` | Matching openFDA food-enforcement reports |

## Daily deploy

`.github/workflows/daily.yml` runs at 11:00 UTC, and also on a manual run or a push to `main` that changes more than `data/`. It refreshes prices and recalls, commits those files back with `[skip ci]`, builds `dist/`, and deploys with `actions/upload-pages-artifact` and `actions/deploy-pages`.

The data commit is ignored by the push trigger (`paths-ignore: data/**`) and marked `[skip ci]`, so it does not start another run.

## One-time setup you have to click

GitHub will not serve the site until Pages is pointed at Actions:

1. Open the repository **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to **GitHub Actions**.
3. If the first run waits on the `github-pages` environment, approve it.
4. After a green deploy, the site is at `https://daeq-star.github.io/caloriecache/`.

If `main` is protected, allow `github-actions[bot]` to push the daily data commit, or the price history will not land.

The newsletter form on `/newsletter/` is a placeholder. It does not send mail. Connect an email provider before enabling the fields. That work is marked TODO on the page.

To add affiliate links later, put the URL in `affiliate_url` on that kit. The footer already says the field is empty and that rankings are not paid.
