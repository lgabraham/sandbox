# VIX Alert

Watches the [CBOE Volatility Index (VIX)](https://finance.yahoo.com/quote/%5EVIX)
and opens a GitHub Issue when it crosses a threshold (default **35**).

Self-contained and separate from the Amazon price checker — only this folder
plus `.github/workflows/vix-check.yml` are involved.

## How it works

- **Schedule:** `.github/workflows/vix-check.yml` runs once per weekday at
  14:30 UTC — around the 9:30am ET market open, so the alert lands early
  (6:30am PST / 7:30am PDT) while it's still actionable. You can also trigger
  it manually from the **Actions** tab.
- **Data:** the latest VIX level is fetched from a free, no-auth source —
  Yahoo Finance first, with Stooq as a fallback. No API keys required.
- **Alert:** if VIX is at or above the threshold, a `vix-alert` Issue is opened
  with the current level and the move from the previous close. The issue is
  **assigned to `ALERT_ASSIGNEE`** so it reliably emails you (assignment
  notifies even if you aren't watching the repo).
- **De-dupe:** while a `vix-alert` issue is open, no new alert is created.
  **Close the issue to re-arm** the alert.
- **History:** each run appends the day's level to `vix_history.json` for
  context in alerts.

## Configuration

| Setting | Where | Default |
|---|---|---|
| Threshold | `VIX_THRESHOLD` env in `.github/workflows/vix-check.yml` | `35` |
| Schedule | `cron` in the workflow | weekdays 14:30 UTC (~market open) |
| Notify | `ALERT_ASSIGNEE` env in the workflow | repo owner |

To change the alert level, edit `VIX_THRESHOLD` in the workflow — no code
changes needed.

## Run locally

```bash
VIX_THRESHOLD=35 GITHUB_REPOSITORY=lgabraham/sandbox python vix_alert/vix_checker.py --check
```

(Issue creation needs the `gh` CLI authenticated; fetching the VIX needs
outbound network access to the quote source.)
