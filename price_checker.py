"""
Amazon Price Checker — Creators API (v3.x OAuth2)

Tracks prices for multiple ASINs, logs daily history, and alerts
via GitHub Issues when prices drop below their thresholds.

Modes:
  --check   (default) Fetch today's prices, log them, alert if below threshold.
  --summary           Create a weekly summary issue with the last 7 days of prices.
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
# Configuration
# ---------------------------------------------------------------------------
CLIENT_ID = os.environ["AMAZON_CLIENT_ID"]
CLIENT_SECRET = os.environ["AMAZON_CLIENT_SECRET"]
PARTNER_TAG = os.environ.get("AMAZON_PARTNER_TAG", "spokenio00-20")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY", "lgabraham/sandbox")

TOKEN_URL = "https://api.amazon.com/auth/o2/token"
ITEMS_URL = "https://creatorsapi.amazon/catalog/v1/getItems"
PRICE_LOG = Path("price_history.json")

# Products to track: (ASIN, friendly label, price threshold)
PRODUCTS = [
    {"asin": "B0002E2EYY", "label": "Lavazza DEK",         "threshold": 18.00},
    {"asin": "B084YXNC2J", "label": "Lavazza DEK Filtro",  "threshold": 18.00},
]


# ---------------------------------------------------------------------------
# OAuth2 token
# ---------------------------------------------------------------------------
def get_access_token() -> str:
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
# Fetch prices from Creators API (batch — up to 10 ASINs per call)
# ---------------------------------------------------------------------------
def get_items(token: str, asins: list[str]) -> dict:
    payload = json.dumps({
        "itemIds": asins,
        "itemIdType": "ASIN",
        "languagesOfPreference": ["en_US"],
        "marketplace": "www.amazon.com",
        "partnerTag": PARTNER_TAG,
        "partnerType": "Associates",
        "resources": [
            "itemInfo.title",
            "offersV2.listings.price",
            "offersV2.listings.condition",
        ],
    }).encode()

    req = Request(ITEMS_URL, data=payload, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-marketplace": "www.amazon.com",
    })

    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        print(f"GetItems failed ({e.code}): {e.read().decode()}")
        sys.exit(1)


def extract_all_prices(response: dict) -> dict[str, tuple[str, float | None]]:
    """Return {asin: (title, price)} for every item in the response."""
    results = {}
    items = response.get("itemsResult", {}).get("items", [])

    for item in items:
        asin = item.get("asin", item.get("ASIN", ""))

        # Title
        item_info = item.get("itemInfo", item.get("ItemInfo", {}))
        title_obj = item_info.get("title", item_info.get("Title", {}))
        title = title_obj.get("displayValue", title_obj.get("DisplayValue", "Unknown"))

        # Price
        offers = item.get("offersV2", item.get("OffersV2", item.get("Offers", {})))
        listings = offers.get("listings", offers.get("Listings", []))
        if listings:
            price_obj = listings[0].get("price", listings[0].get("Price", {}))
            money = price_obj.get("money", price_obj.get("Money", {}))
            price = money.get("amount", money.get("Amount"))
        else:
            price = None

        results[asin] = (title, price)

    return results


# ---------------------------------------------------------------------------
# Price history  (keyed by ASIN)
#
# Format: {
#   "B0002E2EYY": [ {"date": "2026-06-02", "price": 25.00, "product": "..."}, ... ],
#   "B084YXNC2J": [ ... ],
# }
# ---------------------------------------------------------------------------
def load_price_history() -> dict[str, list[dict]]:
    if PRICE_LOG.exists():
        data = json.loads(PRICE_LOG.read_text())
        # Migrate from old flat-list format
        if isinstance(data, list):
            return {"B0002E2EYY": data}
        return data
    return {}


def save_price_history(history: dict[str, list[dict]]):
    PRICE_LOG.write_text(json.dumps(history, indent=2) + "\n")


def log_prices(price_data: dict[str, tuple[str, float]]):
    """Append today's prices to the history and commit."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history = load_price_history()

    for asin, (product_name, price) in price_data.items():
        if price is None:
            continue
        entries = history.setdefault(asin, [])
        entry = {"date": today, "price": price, "product": product_name}

        if entries and entries[-1].get("date") == today:
            print(f"  [{asin}] Updating existing entry for {today}.")
            entries[-1] = entry
        else:
            entries.append(entry)

    save_price_history(history)

    # Commit
    subprocess.run(["git", "config", "user.email", "price-bot@github.com"], check=True)
    subprocess.run(["git", "config", "user.name", "Price Bot"], check=True)
    subprocess.run(["git", "add", str(PRICE_LOG)], check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
    if result.returncode != 0:
        subprocess.run(
            ["git", "commit", "-m", f"Log prices for {today}"],
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
    result = subprocess.run(
        ["gh", "issue", "create", "--repo", GITHUB_REPO,
         "--title", title, "--body", body, "--label", label],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        result = subprocess.run(
            ["gh", "issue", "create", "--repo", GITHUB_REPO,
             "--title", title, "--body", body],
            capture_output=True, text=True,
        )
    if result.returncode == 0:
        print(f"  Issue created: {result.stdout.strip()}")
    else:
        print(f"  Failed to create issue: {result.stderr}")


# ---------------------------------------------------------------------------
# Mode: daily check
# ---------------------------------------------------------------------------
def daily_check():
    asins = [p["asin"] for p in PRODUCTS]
    thresholds = {p["asin"]: p["threshold"] for p in PRODUCTS}
    labels = {p["asin"]: p["label"] for p in PRODUCTS}

    print(f"Checking prices for {len(PRODUCTS)} products...")
    token = get_access_token()
    response = get_items(token, asins)
    price_data = extract_all_prices(response)

    # Print summary
    for asin in asins:
        title, price = price_data.get(asin, ("Unknown", None))
        if price is not None:
            print(f"  {labels[asin]}: ${price:.2f}")
        else:
            print(f"  {labels[asin]}: price unavailable")

    # Log all prices
    log_prices(price_data)

    # Alert for each product below its threshold
    for asin in asins:
        title, price = price_data.get(asin, ("Unknown", None))
        if price is None:
            continue
        threshold = thresholds[asin]
        if price < threshold:
            print(f"  {labels[asin]} ${price:.2f} < ${threshold:.2f} — creating alert!")
            body = (
                f"The price of **{title}** (ASIN: `{asin}`) "
                f"has dropped to **${price:.2f}**, which is below your "
                f"threshold of **${threshold:.2f}**.\n\n"
                f"[View on Amazon](https://www.amazon.com/dp/{asin}?tag={PARTNER_TAG})\n\n"
                f"---\n"
                f"*This issue was created automatically by the price checker.*"
            )
            create_github_issue(
                title=f"\U0001f514 Price Alert: {labels[asin]} is ${price:.2f}",
                body=body,
                label="price-alert",
            )


# ---------------------------------------------------------------------------
# Mode: weekly summary
# ---------------------------------------------------------------------------
def weekly_summary():
    history = load_price_history()
    if not history:
        print("No price history found.")
        return

    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Build per-product sections
    sections = []
    for product in PRODUCTS:
        asin = product["asin"]
        label = product["label"]
        threshold = product["threshold"]
        entries = history.get(asin, [])
        week = [e for e in entries if e["date"] >= cutoff]

        if not week:
            sections.append(f"### {label} (`{asin}`)\nNo data this week.\n")
            continue

        prices = [e["price"] for e in week]
        low, high, avg = min(prices), max(prices), sum(prices) / len(prices)

        rows = "\n".join(
            f"| {e['date']} | ${e['price']:.2f} | "
            f"{'✅ Below' if e['price'] < threshold else '—'} |"
            for e in week
        )

        sections.append(
            f"### {label} (`{asin}`)\n"
            f"**Threshold:** ${threshold:.2f}\n\n"
            f"| Date | Price | Alert? |\n"
            f"|------|-------|--------|\n"
            f"{rows}\n\n"
            f"**Low:** ${low:.2f} · **High:** ${high:.2f} · "
            f"**Avg:** ${avg:.2f}\n\n"
            f"[View on Amazon](https://www.amazon.com/dp/{asin}?tag={PARTNER_TAG})\n"
        )

    body = (
        f"## \U0001f4ca Weekly Price Report\n"
        f"**Period:** {cutoff} → {today}\n\n"
        + "\n---\n\n".join(sections)
        + "\n---\n*Weekly summary generated automatically.*"
    )

    create_github_issue(
        title=f"\U0001f4ca Weekly Price Report ({today})",
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
