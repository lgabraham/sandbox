"""
Amazon Price Checker — Creators API (v3.x OAuth2)

Checks the price of a given ASIN via the Amazon Creators API and
creates a GitHub Issue if the price drops below a threshold.
"""

import json
import os
import subprocess
import sys
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError

# ---------------------------------------------------------------------------
# Configuration (all from environment variables)
# ---------------------------------------------------------------------------
CLIENT_ID = os.environ["AMAZON_CLIENT_ID"]
CLIENT_SECRET = os.environ["AMAZON_CLIENT_SECRET"]
PARTNER_TAG = os.environ.get("AMAZON_PARTNER_TAG", "spokenio00-20")
ASIN = os.environ.get("AMAZON_ASIN", "B0002E2EYY")
PRICE_THRESHOLD = float(os.environ.get("PRICE_THRESHOLD", "18.00"))
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY", "lgabraham/sandbox")

# ---------------------------------------------------------------------------
# Step 1: Get an OAuth2 access token (v3.x — Login with Amazon)
# ---------------------------------------------------------------------------
TOKEN_URL = "https://api.amazon.com/auth/o2/token"
ITEMS_URL = "https://creatorsapi.amazon/catalog/v1/getItems"


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
            data = json.loads(resp.read())
            return data["access_token"]
    except HTTPError as e:
        print(f"Token request failed ({e.code}): {e.read().decode()}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Step 2: Call GetItems to retrieve the current price
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
# Step 3: Create a GitHub Issue if the price is below threshold
# ---------------------------------------------------------------------------
def create_github_issue(title: str, product_name: str, price: float):
    """Create a GitHub Issue via the gh CLI."""
    body = (
        f"The price of **{product_name}** (ASIN: `{ASIN}`) "
        f"has dropped to **${price:.2f}**, which is below your "
        f"threshold of **${PRICE_THRESHOLD:.2f}**.\n\n"
        f"[View on Amazon](https://www.amazon.com/dp/{ASIN}?tag={PARTNER_TAG})\n\n"
        f"---\n"
        f"*This issue was created automatically by the price checker workflow.*"
    )

    result = subprocess.run(
        [
            "gh", "issue", "create",
            "--repo", GITHUB_REPO,
            "--title", title,
            "--body", body,
            "--label", "price-alert",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # Label might not exist yet; retry without it
        result = subprocess.run(
            [
                "gh", "issue", "create",
                "--repo", GITHUB_REPO,
                "--title", title,
                "--body", body,
            ],
            capture_output=True,
            text=True,
        )

    if result.returncode == 0:
        print(f"Issue created: {result.stdout.strip()}")
    else:
        print(f"Failed to create issue: {result.stderr}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"Checking price for ASIN {ASIN} (threshold: ${PRICE_THRESHOLD:.2f})...")

    token = get_access_token()
    response = get_item_price(token)
    product_name, price = extract_price(response)

    if price is None:
        print(f"Could not retrieve price for {ASIN}. The item may be unavailable.")
        sys.exit(1)

    print(f"Product: {product_name}")
    print(f"Current price: ${price:.2f}")

    if price < PRICE_THRESHOLD:
        print(f"Price ${price:.2f} is BELOW threshold ${PRICE_THRESHOLD:.2f} — creating issue!")
        create_github_issue(
            title=f"Price Alert: {product_name} is ${price:.2f}",
            product_name=product_name,
            price=price,
        )
    else:
        print(f"Price ${price:.2f} is above threshold ${PRICE_THRESHOLD:.2f}. No alert needed.")


if __name__ == "__main__":
    main()
