# Amazon Price Checker

Checks the price of an Amazon product daily and creates a GitHub Issue when it drops below a threshold.

## Setup

1. Add these repository secrets (Settings → Secrets and variables → Actions):
   - `AMAZON_CLIENT_ID` — your Creators API credential ID
   - `AMAZON_CLIENT_SECRET` — your Creators API secret

2. The workflow runs daily at 9:00 AM UTC. You can also trigger it manually from the Actions tab.

## Configuration

Edit these values in `.github/workflows/price-check.yml`:
- `AMAZON_ASIN` — the product to track (default: `B0002E2EYY`)
- `PRICE_THRESHOLD` — alert when price is below this (default: `18.00`)
- `AMAZON_PARTNER_TAG` — your Associates tag (default: `spokenio00-20`)
