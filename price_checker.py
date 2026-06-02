"""
Amazon Price Checker — Creators API (v3.x OAuth2)

Tracks prices for multiple ASINs, logs daily history, and alerts
via GitHub Issues when prices drop below a dynamic threshold based
on the 25th percentile of historical prices.

Modes:
  --check   (default) Fetch today's prices, log them, alert if a deal.
  --summary           Create a weekly summary issue with the last 7 days of prices.
"""

import json
import math
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

# Alert percentile: alert when price is in the bottom N% of history.
# 25 = bottom quarter — "cheaper than 75% of prices we've seen."
ALERT_PERCENTILE = 25

# Minimum number of data points before dynamic thresholds kick in.
# Until we have this many, we use the fallback hard ceiling.
MIN_HISTORY_FOR_DYNAMIC = 7

# Products to track.
# "max_price" is a hard ceiling — never alert above this even if the
# percentile math says to (guards against sparse/weird early data).
PRODUCTS = [
    {"asin": "B0002E2EYY", "label": "Lavazza DEK",         "max_price": 20.00},
    {"asin": "B084YXNC2J", "label": "Lavazza DEK Filtro",  "max_price": 16.00},
]


# ---------------------------------------------------------------------------
# Percentile math
# ---------------------------------------------------------------------------
def percentile(values: list[float], pct: float) -> float:
    """Compute the pct-th percentile of a sorted list using linear interpolation."""
    if not values:
        return 0.0
    s = sorted(values)
    k = (pct / 100) * (len(s) - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def dynamic_threshold(asin: str, max_price: float) -> tuple[float, str]:
    """Return (threshold, explanation) for a product.

    Uses the 25th percentile of all historical prices once we have
    enough data; otherwise falls back to max_price.
    """
    history = load_price_history()
    entries = history.get(asin, [])
    prices = [e["price"] for e in entries]

    if len(prices) >= MIN_HISTORY_FOR_DYNAMIC:
        p25 = percentile(prices, ALERT_PERCENTILE)
        threshold = min(p25, max_price)  # never exceed hard ceiling
        return (threshold, f"p{ALERT_PERCENTILE} of {len(prices)} data points")
    else:
        return (max_price, f"fallback (only {len(prices)}/{MIN_HISTORY_FOR_DYNAMIC} data points)")


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
# ---------------------------------------------------------------------------
def load_price_history() -> dict[str, list[dict]]:
    if PRICE_LOG.exists():
        data = json.loads(PRICE_LOG.read_text())
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
# Price stats from history
# ---------------------------------------------------------------------------
def compute_stats(asin: str) -> dict:
    """Compute price stats for an ASIN from the history file."""
    history = load_price_history()
    entries = history.get(asin, [])
    if not entries:
        return {}

    prices = [e["price"] for e in entries]
    cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    week_prices = [e["price"] for e in entries if e["date"] >= cutoff_7d]

    stats = {
        "all_time_low": min(prices),
        "all_time_high": max(prices),
        "all_time_avg": sum(prices) / len(prices),
        "data_points": len(prices),
    }

    if week_prices:
        stats["week_avg"] = sum(week_prices) / len(week_prices)

    if len(entries) >= 2:
        stats["previous_price"] = entries[-2]["price"]

    return stats


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
    labels = {p["asin"]: p["label"] for p in PRODUCTS}
    max_prices = {p["asin"]: p["max_price"] for p in PRODUCTS}

    print(f"Checking prices for {len(PRODUCTS)} products...")
    token = get_access_token()
    response = get_items(token, asins)
    price_data = extract_all_prices(response)

    # Log all prices first (so today's price is included in stats)
    log_prices(price_data)

    # Compute dynamic thresholds (now includes today's data point)
    for asin in asins:
        title, price = price_data.get(asin, ("Unknown", None))
        threshold, explanation = dynamic_threshold(asin, max_prices[asin])

        if price is not None:
            print(f"  {labels[asin]}: ${price:.2f}  (threshold: ${threshold:.2f} — {explanation})")
        else:
            print(f"  {labels[asin]}: price unavailable")
            continue

        if price <= threshold:
            print(f"  {labels[asin]} ${price:.2f} <= ${threshold:.2f} — creating alert!")
            stats = compute_stats(asin)

            # Context lines
            context_lines = []
            if "week_avg" in stats:
                diff = stats["week_avg"] - price
                context_lines.append(
                    f"That's **${diff:.2f} below** your ${stats['week_avg']:.2f} weekly average"
                )
            if "all_time_low" in stats:
                if price <= stats["all_time_low"]:
                    context_lines.append("and a new **all-time low**! \U0001f389")
                else:
                    gap = price - stats["all_time_low"]
                    context_lines.append(
                        f"and only **${gap:.2f} above** the all-time low of ${stats['all_time_low']:.2f}!"
                    )

            context = " ".join(context_lines) if context_lines else ""

            # Stats table
            table_rows = [
                f"| Current | **${price:.2f}** |",
                f"| Deal threshold | ${threshold:.2f} (p{ALERT_PERCENTILE}) |",
            ]
            if "week_avg" in stats:
                table_rows.append(f"| 7-day avg | ${stats['week_avg']:.2f} |")
            if "all_time_low" in stats:
                table_rows.append(f"| All-time low | ${stats['all_time_low']:.2f} |")
            if "all_time_high" in stats:
                table_rows.append(f"| All-time high | ${stats['all_time_high']:.2f} |")
            if "data_points" in stats:
                table_rows.append(f"| Data points | {stats['data_points']} |")
            table = "\n".join(table_rows)

            body = (
                f"**☕ Deal Alert: {labels[asin]} — ${price:.2f}**\n\n"
                f"{context}\n\n"
                f"| | |\n"
                f"|---|---|\n"
                f"{table}\n\n"
                f"**[☕ Buy it on Amazon →](https://www.amazon.com/dp/{asin}?tag={PARTNER_TAG})**\n\n"
                f"---\n"
                f"*Price checked automatically — threshold is the 25th percentile "
                f"of {stats.get('data_points', '?')} historical prices. "
                f"Close this issue to dismiss.*"
            )
            create_github_issue(
                title=f"☕ Deal Alert: {labels[asin]} — ${price:.2f}",
                body=body,
                label="price-alert",
            )
        else:
            print(f"  {labels[asin]}: no alert needed.")


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

    sections = []
    for product in PRODUCTS:
        asin = product["asin"]
        label = product["label"]
        max_price = product["max_price"]
        entries = history.get(asin, [])
        week = [e for e in entries if e["date"] >= cutoff]

        threshold, explanation = dynamic_threshold(asin, max_price)

        if not week:
            sections.append(f"### {label} (`{asin}`)\nNo data this week.\n")
            continue

        prices = [e["price"] for e in week]
        low, high, avg = min(prices), max(prices), sum(prices) / len(prices)

        rows = "\n".join(
            f"| {e['date']} | ${e['price']:.2f} | "
            f"{'✅ Deal' if e['price'] <= threshold else '—'} |"
            for e in week
        )

        sections.append(
            f"### {label} (`{asin}`)\n"
            f"**Deal threshold:** ${threshold:.2f} ({explanation})\n\n"
            f"| Date | Price | Deal? |\n"
            f"|------|-------|-------|\n"
            f"{rows}\n\n"
            f"**Low:** ${low:.2f} · **High:** ${high:.2f} · "
            f"**Avg:** ${avg:.2f}\n\n"
            f"[View on Amazon](https://www.amazon.com/dp/{asin}?tag={PARTNER_TAG})\n"
        )

    body = (
        f"## \U0001f4ca Weekly Price Report\n"
        f"**Period:** {cutoff} → {today}\n\n"
        + "\n---\n\n".join(sections)
        + "\n---\n*Weekly summary generated automatically. "
        f"Thresholds use the 25th percentile of all historical prices.*"
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
