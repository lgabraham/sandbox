# Amazon Price Checker

Tracks the price of Amazon products daily and alerts you via GitHub Issues when prices are genuinely good deals.

## How it works

### Dynamic thresholds
Instead of fixed price targets, alerts use the **25th percentile** of all historical prices. This means you only get notified when a price is in the **bottom quarter** of everything we've seen — an actual deal, not just a number you picked.

- As the price history grows, the threshold adapts automatically
- Each product has a **hard ceiling** (`max_price`) as a sanity check — no alerts above this regardless of percentile math
- For the first 7 days (before enough data exists), the hard ceiling is used as a fallback

### Schedules
- **Daily (9 AM UTC):** Fetches current prices, logs them to `price_history.json`, and creates a ☕ **Deal Alert** issue if the price is at or below the 25th percentile
- **Friday (6 PM UTC):** Creates a 📊 **Weekly Price Report** issue with a table of the last 7 days of prices, stats, and current thresholds

## Products tracked

| Product | ASIN | Hard ceiling |
|---------|------|-------------|
| Lavazza DEK | `B0002E2EYY` | $20.00 |
| Lavazza DEK Filtro | `B084YXNC2J` | $18.00 |

## Setup

1. Add these repository secrets (Settings → Secrets and variables → Actions):
   - `AMAZON_CLIENT_ID` — your Creators API credential ID
   - `AMAZON_CLIENT_SECRET` — your Creators API secret

2. The workflows run automatically. You can also trigger manually from the **Actions** tab.

## Configuration

In `price_checker.py`:
- `ALERT_PERCENTILE` — which percentile to alert on (default: 25)
- `MIN_HISTORY_FOR_DYNAMIC` — data points needed before percentile kicks in (default: 7)
- `PRODUCTS` — add/remove ASINs, labels, and hard ceilings
