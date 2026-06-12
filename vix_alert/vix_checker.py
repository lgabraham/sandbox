"""
VIX Alert — notify when the CBOE Volatility Index crosses a threshold.

Fetches the latest VIX level from a free, no-auth quote source and opens a
GitHub Issue when it is at or above the threshold (default 35). De-dupes so
it won't open a new issue while one is already open.

Modes:
  --check   (default) Fetch the latest VIX, log it, alert if >= threshold.

Data sources (tried in order, no API key required):
  1. Yahoo Finance chart API  (^VIX)
  2. Stooq CSV                 (^vix)

Env:
  VIX_THRESHOLD       Alert at/above this level (default: 35).
  GITHUB_REPOSITORY   owner/repo for issue creation.
  GH_TOKEN            Token used by the `gh` CLI.
"""

import csv
import io
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
THRESHOLD = float(os.environ.get("VIX_THRESHOLD", "35"))
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY", "lgabraham/sandbox")

HISTORY_LOG = Path(__file__).with_name("vix_history.json")
ALERT_LABEL = "vix-alert"

# Assign the alert issue to this GitHub user so it reliably triggers an
# email notification (issue assignment always notifies the assignee, even
# if they aren't "watching" the repo). Empty string = don't assign.
ALERT_ASSIGNEE = os.environ.get("ALERT_ASSIGNEE", "")

USER_AGENT = "Mozilla/5.0 (compatible; vix-alert/1.0)"

YAHOO_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX"
    "?interval=1d&range=1d"
)
STOOQ_URL = "https://stooq.com/q/l/?s=%5Evix&f=sd2t2ohlcv&h&e=csv"


# ---------------------------------------------------------------------------
# Fetching the VIX level
# ---------------------------------------------------------------------------
def _get(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urlopen(req, timeout=30) as resp:
        return resp.read()


def fetch_from_yahoo() -> float | None:
    """Latest VIX close from Yahoo Finance chart API."""
    data = json.loads(_get(YAHOO_URL))
    result = data["chart"]["result"][0]
    meta = result.get("meta", {})

    # Prefer the live/regular-market price; fall back to last close in the series.
    price = meta.get("regularMarketPrice")
    if price is not None:
        return float(price)

    closes = result["indicators"]["quote"][0].get("close", [])
    closes = [c for c in closes if c is not None]
    return float(closes[-1]) if closes else None


def fetch_from_stooq() -> float | None:
    """Latest VIX close from Stooq CSV."""
    text = _get(STOOQ_URL).decode("utf-8", "replace")
    row = next(csv.DictReader(io.StringIO(text)), None)
    if not row:
        return None
    close = row.get("Close")
    if close in (None, "", "N/D"):
        return None
    return float(close)


def fetch_vix() -> float:
    """Return the latest VIX level, trying each source in turn."""
    sources = [("Yahoo Finance", fetch_from_yahoo), ("Stooq", fetch_from_stooq)]
    errors = []
    for name, fn in sources:
        try:
            value = fn()
            if value is not None:
                print(f"  VIX from {name}: {value:.2f}")
                return value
            errors.append(f"{name}: no value in response")
        except (HTTPError, URLError, KeyError, ValueError, TimeoutError) as e:
            errors.append(f"{name}: {e}")

    print("Failed to fetch VIX from all sources:")
    for err in errors:
        print(f"  - {err}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# History  (lightweight log for context in alerts)
# ---------------------------------------------------------------------------
def load_history() -> list[dict]:
    if HISTORY_LOG.exists():
        return json.loads(HISTORY_LOG.read_text())
    return []


def log_value(value: float) -> float | None:
    """Append today's VIX to history, commit, and return the previous close."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history = load_history()

    previous = history[-1]["vix"] if history else None
    entry = {"date": today, "vix": round(value, 2)}

    if history and history[-1].get("date") == today:
        # Same-day re-run: previous close is the one before today's entry.
        previous = history[-2]["vix"] if len(history) >= 2 else None
        history[-1] = entry
    else:
        history.append(entry)

    HISTORY_LOG.write_text(json.dumps(history, indent=2) + "\n")
    _commit_history(today)
    return previous


def _commit_history(today: str):
    try:
        subprocess.run(["git", "config", "user.email", "vix-bot@github.com"], check=True)
        subprocess.run(["git", "config", "user.name", "VIX Bot"], check=True)
        subprocess.run(["git", "add", str(HISTORY_LOG)], check=True)
        staged = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True)
        if staged.returncode != 0:
            subprocess.run(["git", "commit", "-m", f"Log VIX for {today}"], check=True)
            subprocess.run(["git", "push"], check=True)
            print(f"  Committed VIX log for {today}.")
        else:
            print("  No VIX history changes to commit.")
    except subprocess.CalledProcessError as e:
        # Logging history is best-effort; never block an alert on a git failure.
        print(f"  Warning: could not commit VIX history ({e}).")


# ---------------------------------------------------------------------------
# GitHub Issue helpers
# ---------------------------------------------------------------------------
def open_alert_exists() -> bool:
    """True if an open issue with the alert label already exists (de-dupe)."""
    result = subprocess.run(
        ["gh", "issue", "list", "--repo", GITHUB_REPO,
         "--state", "open", "--label", ALERT_LABEL, "--json", "number"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # If we can't tell, fail open (allow the alert) rather than stay silent.
        print(f"  Warning: could not list issues ({result.stderr.strip()}).")
        return False
    try:
        return len(json.loads(result.stdout or "[]")) > 0
    except json.JSONDecodeError:
        return False


def create_github_issue(title: str, body: str, label: str = ALERT_LABEL):
    base = ["gh", "issue", "create", "--repo", GITHUB_REPO,
            "--title", title, "--body", body]
    if ALERT_ASSIGNEE:
        base += ["--assignee", ALERT_ASSIGNEE]

    result = subprocess.run(base + ["--label", label], capture_output=True, text=True)
    if result.returncode != 0:
        # Label may not exist yet — retry without it (keep the assignee).
        result = subprocess.run(base, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  Issue created: {result.stdout.strip()}")
    else:
        print(f"  Failed to create issue: {result.stderr}")


# ---------------------------------------------------------------------------
# Mode: check
# ---------------------------------------------------------------------------
def check():
    print(f"Checking VIX (alert threshold: {THRESHOLD:.0f})...")
    vix = fetch_vix()
    previous = log_value(vix)

    if vix < THRESHOLD:
        print(f"  VIX {vix:.2f} < {THRESHOLD:.0f} — no alert.")
        return

    print(f"  VIX {vix:.2f} >= {THRESHOLD:.0f} — threshold breached.")

    if open_alert_exists():
        print("  An open VIX alert already exists — skipping duplicate.")
        return

    # Context line about the move from the previous close.
    move = ""
    if previous is not None:
        delta = vix - previous
        arrow = "\U0001f4c8" if delta >= 0 else "\U0001f4c9"
        move = (
            f"{arrow} {'+' if delta >= 0 else ''}{delta:.2f} "
            f"from the previous close of {previous:.2f}.\n\n"
        )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    body = (
        f"**⚠️ VIX Alert: {vix:.2f} (at/above {THRESHOLD:.0f})**\n\n"
        f"{move}"
        f"| | |\n"
        f"|---|---|\n"
        f"| Current VIX | **{vix:.2f}** |\n"
        f"| Alert threshold | {THRESHOLD:.0f} |\n"
        f"| As of | {today} (UTC) |\n\n"
        f"The CBOE Volatility Index has reached **{vix:.2f}**, at or above your "
        f"alert level of {THRESHOLD:.0f} — elevated market stress.\n\n"
        f"[\U0001f4ca View VIX on Yahoo Finance →](https://finance.yahoo.com/quote/%5EVIX)\n\n"
        f"---\n"
        f"*Checked automatically. You won't get another alert while this issue "
        f"is open — close it to re-arm.*"
    )
    create_github_issue(
        title=f"⚠️ VIX at {vix:.2f} (above {THRESHOLD:.0f})",
        body=body,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    if mode == "--check":
        check()
    else:
        print(f"Unknown mode: {mode}. Use --check.")
        sys.exit(1)


if __name__ == "__main__":
    main()
