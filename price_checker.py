"""
Amazon Price Checker — Creators API (v3.x OAuth2)

Modes:
  --check   (default) Fetch today's price, log it, and alert if below threshold.
  --summary           Read the last 7 days of prices and create a weekly summary issue.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Configuration (all from environment variables)
# ---------------------------------------------------------------------------
CLIENT_ID = os.environ["AMAZON_CLIENT_ID"]
CLIENT_SECRET = os.environ["AMAZON_CLIENT_SECRET"]
PARTNER_TAG = os.environ.get("AMAZON_PARTNER_TAG", "spokenio00-20")
ASIN = os.environ.get("AMAZON_ASIN", "B0002E2EYY")
PRICE_THRESHOLD = float(os.environ.get("PRICE_THRESHOLD", "18.00"))
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY", "lgabraham/sandbox")

TOKEN_URL = "https://api.amazon.com/auth/o2/token"
ITEMS_URL = "https://creatorsapi.amazon/catalog/v1/getItems"
PRICE_LOG = Path("price_history.json")


# ---------------------------------------------------------------------------
# OAuth2 token
# ---------------------------------------------------------------------------
def get_access_token() -> str:
    """Exchange client credentials for a bearer token."""
    body = urlencode({
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "creatorsapi::default",
    }).encode()

    req = Request(TOKEN_URL, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded",
    })

    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())["access_token"]
    except HTTPError as e:
        print(f"Token request failed ({e.code}): {e.read().decode()}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Fetch price from Creators API
# ---------------------------------------------------------------------------
def get_item_price(token: str) -> dict:
    """Fetch price info for the configured ASIN."""
    payload = json.dumps({
        "itemIds": [ASIN],
        "itemIdType": "ASIN",
        "languagesOfPreference": ["en_US"],
        "marketplace": "www.amazon.com",
        "partnerTag": PARTNER_TAG,
        "partnerType": "Associates",
        "resources": [
            "ItemInfo.Title",
            "OffersV2.Listings.Price",
            "OffersV2.Listings.Condition",
        ],
    }).encode()

    req = Request(ITEMS_URL, data=payload, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })

    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        print(f"GetItems failed ({e.code}): {e.read().decode()}")
        sys.exit(1)


def extract_price(response: dict) -> tuple[str, float | None]:
    """Return (title, price) from the API response."""
    items = response.get("itemsResult", {}).get("items", [])
    if not items:
        return ("Unknown", None)

    item = items[0]
    title = (
        item.get("itemInfo", {})
        .get("title", {})
        .get("displayValue", "Unknown")
    )

    listings = item.get("offersV2", {}).get("listings", [])
    if not listings:
        return (title, None)

    price = listings[0].get("price", {}).get("money", {}).get("amount")
    return (title, price)


# ---------------------------------------------------------------------------
# Price history (stored as a JSON file committed to the repo)
# ---------------------------------------------------------------------------
def load_price_history() -> list[dict]:
    """Load price history from the JSON log file."""
    if PRICE_LOG.exists():
        return json.loads(PRICE_LOG.read_text())
    return []


def save_price_history(history: list[dict]):
    """Write price history back to the JSON log file."""
    PRICE_LOG.write_text(json.dumps(history, indent=2) + "\n")


def log_price(product_name: str, price: float):
    """Append today's price to the history and commit it."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history = load_price_history()

    # Don't double-log if already ran today
    if history and history[-1].get("date") == today:
        print(f"Price already logged for {today}, updating.")
        history[-1] = {"date": today, "price": price, "product": product_name}
    else:
        history.append({"date": today, "price": price, "product": product_name})

    save_price_history(history)

    # Commit the updated log
    subprocess.run(["git", "config", "user.email", "price-bot@github.com"], check=True)
    subprocess.run(["git", "config", "user.name", "Price Bot"], check=True)
    subprocess.run(["git", "add", str(PRICE_LOG)], check=True)
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        capture_output=True,
    )
    if result.returncode != 0:  # there are staged changes
        subprocess.run(
            ["git", "commit", "-m", f"Log price for {today}: ${price:.2f}"],
            check=True,
        )
        subprocess.run(["git", "push"], check=True)
        print(f"Committed price log for {today}.")
    else:
        print("No changes to commit.")


# ---------------------------------------------------------------------------
# GitHub Issue helpers
# ---------------------------------------------------------------------------
def create_github_issue(title: str, body: str, label: str = "price-alert"):
    """Create a GitHub Issue via the gh CLI."""
    result = subprocess.run(
        ["gh", "issue", "create", "--repo", GITHUB_REPO,
         "--title", title, "--body", body, "--label", label],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Label might not exist yet; retry without it
        result = subprocess.run(
            ["gh", "issue", "create", "--repo", GITHUB_REPO,
             "--title", title, "--body", body],
            capture_output=True, text=True,
        )
    if result.returncode == 0:
        print(f"Issue created: {result.stdout.strip()}")
    else:
        print(f"Failed to create issue: {result.stderr}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Mode: daily check
# ---------------------------------------------------------------------------
def daily_check():
    """Fetch today's price, log it, and alert if below threshold."""
    print(f"Checking price for ASIN {ASIN} (threshold: ${PRICE_THRESHOLD:.2f})...")

    token = get_access_token()
    response = get_item_price(token)
    product_name, price = extract_price(response)

    if price is None:
        print(f"Could not retrieve price for {ASIN}. The item may be unavailable.")
        sys.exit(1)

    print(f"Product: {product_name}")
    print(f"Current price: ${price:.2f}")

    log_price(product_name, price)

    if price < PRICE_THRESHOLD:
        print(f"Price ${price:.2f} is BELOW threshold — creating alert!")
        body = (
            f"The price of **{product_name}** (ASIN: `{ASIN}`) "
            f"has dropped to **${price:.2f}**, which is below your "
            f"threshold of **${PRICE_THRESHOLD:.2f}**.\n\n"
            f"[View on Amazon](https://www.amazon.com/dp/{ASIN}?tag={PARTNER_TAG})\n\n"
            f"---\n"
            f"*This issue was created automatically by the price checker.*"
        )
        create_github_issue(
            title=f"🔔 Price Alert: {product_name} is ${price:.2f}",
            body=body,
            label="price-alert",
        )
    else:
        print(f"Price is above threshold. No alert needed.")


# ---------------------------------------------------------------------------
# Mode: weekly summary
# ---------------------------------------------------------------------------
def weekly_summary():
    """Create a GitHub Issue with the last 7 days of prices."""
    history = load_price_history()
    if not history:
        print("No price history found. Nothing to summarize.")
        return

    # Filter to last 7 days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    week = [e for e in history if e["date"] >= cutoff]

    if not week:
        print("No prices recorded in the last 7 days.")
        return

    product_name = week[-1].get("product", "Unknown")
    prices = [e["price"] for e in week]
    low = min(prices)
    high = max(prices)
    avg = sum(prices) / len(prices)
    latest = prices[-1]

    # Build a nice markdown table
    rows = "\n".join(
        f"| {e['date']} | ${e['price']:.2f} | "
        f"{'✅ Below' if e['price'] < PRICE_THRESHOLD else '—'} |"
        for e in week
    )

    body = (
        f"## Weekly Price Summary — {product_name}\n"
        f"**ASIN:** `{ASIN}` · "
        f"**Threshold:** ${PRICE_THRESHOLD:.2f} · "
        f"**Period:** {week[0]['date']} → {week[-1]['date']}\n\n"
        f"| Date | Price | Alert? |\n"
        f"|------|-------|--------|\n"
        f"{rows}\n\n"
        f"### Stats\n"
        f"- **Low:** ${low:.2f}\n"
        f"- **High:** ${high:.2f}\n"
        f"- **Average:** ${avg:.2f}\n"
        f"- **Latest:** ${latest:.2f}\n\n"
        f"[View on Amazon](https://www.amazon.com/dp/{ASIN}?tag={PARTNER_TAG})\n\n"
        f"---\n"
        f"*Weekly summary generated automatically.*"
    )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    create_github_issue(
        title=f"📊 Weekly Price Report ({today}): {product_name}",
        body=body,
        label="weekly-summary",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"

    if mode == "--check":
        daily_check()
    elif mode == "--summary":
        weekly_summary()
    else:
        print(f"Unknown mode: {mode}. Use --check or --summary.")
        sys.exit(1)


if __name__ == "__main__":
    main()
