# Expanded strategy search source

`expanded.py` is the maintained campaign implementation for the preserved
expanded-search study. Raw plans, prepared bars, ledgers, reports, and results
remain under:

```text
<WORKBENCH_ARTIFACTS>/research/expanded-search-2026-09-16/
```

The source reads the preserved dataset inventory from
`<WORKBENCH_ARTIFACTS>/research/all-strategies-all-charts-2026-09-16/inventory.json`
by default. Both locations can be selected explicitly without writing into the
source tree:

```powershell
.venv/Scripts/python.exe research/campaigns/expanded-search-2026-09-16/expanded.py prepare `
  --campaign-dir artifacts/research/expanded-search-2026-09-16 `
  --inventory artifacts/research/all-strategies-all-charts-2026-09-16/inventory.json
```

`AW_EXPANDED_CAMPAIGN_DIR` and `AW_EXPANDED_INVENTORY` provide equivalent
environment overrides for worker processes. The pure execution-stress helpers
can be imported without the artifact store; full campaign stages require the
preserved inventory and datasets.
