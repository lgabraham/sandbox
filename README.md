# Amazon Price Checker

Tracks the price of an Amazon product daily and alerts you via GitHub Issues.

## What it does

- **Daily (9 AM UTC):** Fetches the current price, logs it to `price_history.json`, and creates a 🔔 **Price Alert** issue if the price drops below $18.
- **Friday (6 PM UTC):** Creates a 📊 **Weekly Price Report** issue with a table of the last 7 days of prices, plus low/high/average stats.

## Setup

1. Add these repository secrets (Settings → Secrets and variables → Actions):
   - `AMAZON_CLIENT_ID` — your Creators API credential ID
   - `AMAZON_CLIENT_SECRET` — your Creators API secret

2. The workflows run automatically. You can also trigger manually from the **Actions** tab (choose `--check` or `--summary` mode).

## Configuration

Edit these values in `.github/workflows/price-check.yml`:

| Variable | Default | Description |
|----------|---------|-------------|
| `AMAZON_ASIN` | `B0002E2EYY` | The product to track |
| `PRICE_THRESHOLD` | `18.00` | Alert when price is below this |
| `AMAZON_PARTNER_TAG` | `spokenio00-20` | Your Associates tag |
