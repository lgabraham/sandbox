# sandbox

A home for small, self-contained automation projects. Each lives in its own
folder with its own README, script, and data; each is driven by its own
scheduled GitHub Actions workflow and alerts via GitHub Issues.

## Projects

| Project | What it does | Folder | Workflow |
|---------|--------------|--------|----------|
| **Amazon Price Checker** | Tracks Amazon product prices daily and opens a Deal Alert issue when a price hits the bottom 25% of its history. | [`amazon_price_checker/`](amazon_price_checker/) | [`price-check.yml`](.github/workflows/price-check.yml) |
| **VIX Alert** | Watches the CBOE Volatility Index and opens an issue when it crosses a threshold (default 35). | [`vix_alert/`](vix_alert/) | [`vix-check.yml`](.github/workflows/vix-check.yml) |

See each project's README for setup, configuration, and how it works.

## Layout

```
.
├── amazon_price_checker/   # price tracking + deal alerts
├── vix_alert/              # volatility index alerts
└── .github/workflows/      # one scheduled workflow per project
```

## Adding a new project

1. Create a new top-level folder (e.g. `my_project/`) with its script and a `README.md`.
2. Make file paths relative to the script (`Path(__file__).with_name(...)`) so it
   runs regardless of the working directory.
3. Add a workflow in `.github/workflows/` that runs it on a schedule and/or on demand.
4. Add a row to the **Projects** table above.
