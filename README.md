# QuantResearch

Research and backtesting workspace for futures and equities, including Python research scripts, TradingView Pine studies/strategies, NinjaTrader 8 ports, generated reports, and a local strategy dashboard.

## Repository overview

- [`scripts/`](scripts/) — research, data, and backtest scripts organized by market/theme: `cme/`, `mnq/`, `mgc/`, `es_nq/`, `orb/`, `overnight/`, `spy_qqq_intraday/`, `lucid/`, and `misc/`.
- [`pine/`](pine/) — TradingView Pine indicators and strategies.
- [`ninjatrader/`](ninjatrader/) — NinjaTrader 8 strategy ports and tooling, including `OrbCarver.cs` and `OvernightDriftCarver.cs`, plus dedicated docs.
- [`data/`](data/) — local/cacheable market datasets used by scripts. Contents vary by what has been fetched/generated locally.
- [`reports/`](reports/) — generated analysis outputs (CSV/PNG/HTML/Markdown/text reports).
- [`FINDINGS.md`](FINDINGS.md) — detailed research handoff, conclusions, methodology notes, and data caveats.

## Quick start

1. Create and activate a virtual environment.

**Windows (PowerShell):**

```powershell
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
```

**macOS/Linux (bash/zsh):**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Create your local environment file from [`.env.example`](.env.example):

**Windows (PowerShell):**

```powershell
Copy-Item .env.example .env
```

**macOS/Linux (bash/zsh):**

```bash
cp .env.example .env
```

3. Fill in keys in `.env` for workflows that need external data access.
   - `PWB_API_KEY`: required for scripts that use Papers With Backtest datasets/utilities.
   - `DATABENTO_API_KEY`: required for scripts that fetch/use Databento futures data.
   - Never commit credentials.

4. Run scripts from the repository root, for example:

```bash
python scripts/misc/smoke_test.py
```

## Strategy dashboard (optional)

A local React/Redux/Mantine dashboard is available for running allowlisted workflows.

```bash
npm install
npm run dev:full
```

Install dashboard Python dependencies in the same virtual environment first:

**Windows (PowerShell):**

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dashboard.txt
```

**macOS/Linux (bash/zsh):**

```bash
./.venv/bin/python -m pip install -r requirements-dashboard.txt
```

Run from the repository root with your virtual environment active. `npm run dev:full`
starts the web UI and local API together; open `http://127.0.0.1:5173`.

## Research notes / limitations

- Backtests and reports here are research artifacts, not investment advice.
- Historical performance does not guarantee live-trading results.
- Assumptions around costs, contract rolls, fills/slippage, and data quality materially affect outcomes.
- Out-of-sample testing and robust validation are required before any live deployment.

## Related documentation

- Research handoff and findings: [`FINDINGS.md`](FINDINGS.md)
- NinjaTrader overview: [`ninjatrader/README.md`](ninjatrader/README.md)
- NinjaTrader validation workflow: [`ninjatrader/TESTING.md`](ninjatrader/TESTING.md)
- NinjaTrader automation setup: [`ninjatrader/AUTOTRADING.md`](ninjatrader/AUTOTRADING.md)
