# Multi-touch cluster failure test: development result

Decision: **No-go for the frozen executable rule.** The Workbench baseline succeeded and reconciled, but the declared development gates failed. No 2025 evaluation, 2026 extension, parameter search, or transfer test was launched.

## Workbench record

- Run: `9528c4f6-f074-4401-8f0b-adbfcbc9aef9` (Succeeded; experiment `51df3542-b289-4fa4-9c7c-78e2e4c4c043`).
- Adapter: `multi-touch-cluster-failure` version 1.0.0; file hash `991273e294822bcb78fe50fbf097e38985ef630bfe080618ec74500420c1b1f9`; execution source hash `e974f6f1d1191c77fc9e607954190f2a173d78c9bac515d20757de3d088d767e`.
- Data: NQ `3b9114199a2f6f0e51b70a63edc43de00940ae5df8d047b3aaa6aa8424aac9f1-v1`, 15-minute full trading day; 2022-01-01 through 2024-12-31; 30 calendar days requested warmup. Dataset checksum `67092a9b6201747c46ae08029068fd03b42c5def68339ac2434dba78a77386c7`.
- Economics: one NQ contract; $100,000 initial capital; $2.50 commission and one tick slippage per side. One-minute execution for working stops. The run starts flat and liquidates at the scored end.

## Result

| Measure | Value |
| --- | ---: |
| Closed trades | 412 |
| Net P&L | +$75 |
| Mean net P&L per trade | +$0.18 |
| Total costs | $6,180 |
| Profit factor | 1.001 |
| Win rate | 12.4% |
| Maximum marked drawdown | 22.4% |
| Maximum marked drawdown, dollars | $27,567.50 |

| Year | Trades | Net P&L |
| --- | ---: | ---: |
| 2022 | 131 | +$22,130 |
| 2023 | 129 | -$17,590 |
| 2024 | 152 | -$4,465 |

The 51 time exits gained $73,890 net; the 361 stop exits lost $73,815 net. The ten largest winners contributed $41,360, or 56.0% of total gross winning P&L. Long trades gained $7,865 net and short trades lost $7,790 net.

The frozen minimum trade count (100) and positive net P&L gates passed. Profit factor missed its 1.05 gate, and only one year was positive versus the required two. The $75 cumulative profit is too small relative to the $27,567.50 peak-to-trough marked drawdown to support advancement.

## Verification and limits

The Workbench published all five artifacts. An independent read of the trade CSV reconciled 412 trades, $75 net and $6,180 costs with the manifest; the final equity was $100,075. All five saved artifact checksums matched. Two focused recognizer tests passed. The repository-wide production build currently fails in portfolio page imports from the separate ongoing repository reorganization; that failure did not affect this Python strategy run.

The test answers whether this one fixed cluster plus sweep/reclaim trade made money under the recorded assumptions. It does not isolate the incremental information in the cluster location because no matched generic-failure-test control was run. The data use unadjusted continuous contract rolls, and the historical period has been inspected by other research. Stops use one-minute OHLC, not tick-level ordering or order-book fills. The Workbench reported warmup coverage as undeclared, though 30 calendar days were requested.

The exact rules and stop conditions are in [PROTOCOL.md](PROTOCOL.md). The complete run artifacts are in `data/workbench/runs/9528c4f6-f074-4401-8f0b-adbfcbc9aef9/`.
