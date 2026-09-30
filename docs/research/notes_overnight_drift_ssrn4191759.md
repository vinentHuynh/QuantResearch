# Notes — "The Overnight Drift" (SSRN 4191759 / abstract 3546173)

**Paper:** Boyarchenko, Larsen, Whelan — *The Overnight Drift*
**Version read:** FRB New York Staff Report No. 917, Feb 2020, revised Aug 2022 (the SSRN link's `ssrn_id4191759` file is this revision). Published version: *Review of Financial Studies* 36(9), 2023, 3502–3547.
**Source used:** SSRN presigned link had expired (403); text extracted from `newyorkfed.org/medialibrary/media/research/staff_reports/sr917.pdf` (98 pp.).

---

## 1. What the paper claims

Returns on S&P 500 e-mini futures (ES) do not accrue linearly around the 24-hour clock. The single largest positive hour is **02:00–03:00 ET**, the opening of European markets, averaging **3.7% annualized (1.48 bps/day)**. Authors name this the "overnight drift" (OD) and attribute it to overnight resolution of **end-of-day US order imbalances** by inventory-constrained liquidity providers — not to information arrival.

## 2. Data

- Tick-by-tick trades and quotes on ES front contract, Refinitiv Datascope Select + CME direct.
- Sample **Jan 1998 – Dec 2020** (23 years). Order book depth (5 levels) from 2009.
- Returns from mid-quotes of best bid/offer; hourly, 15-min, 5-min, 1-min.
- Order imbalance proxy: **relative signed volume** RSV = signed volume / gross volume; closing measure sampled 15:15–16:15.

## 3. Headline numbers

| Window | Avg return | t-stat |
|---|---|---|
| Close-to-close (CTC) | 5.9% p.a. | — |
| Overnight session 16:15→09:30 | 3.6% p.a. | — |
| **02:00–03:00 (OD)** | **3.7% p.a. / 1.48 bps/day** | **7.1** |
| 00:00–01:00 | 0.46 bps/day | 2.8 |
| 01:00–02:00 | 0.43 bps/day | 2.8 |
| 09:00–10:00 ("opening hour") | −1.2 bps/day | −2.6 |
| 17:00–18:00 | −0.43 bps/day | −3.6 |

Other observations: OD hour median quote return is +0.64 bps (not driven by outliers); OD positive in 20 of 23 years, individually significant in 17; significant on every weekday and in 9 of 12 months; return builds continuously across 01:00–04:00 rather than jumping.

## 4. Statistical hygiene (better than typical for this literature)

- Block bootstrap (10,000 draws, Patton–Politis–White block length) over all 24 hourly windows. OD's 2.5% lower bound on both point estimates and t-stats lies **above** the pooled 97.5% bound.
- Multiple-testing correction with Bonferroni and Benjamini–Yekutieli critical values: 02:00–03:00 is the only hour surviving in full sample **and** subsamples.
- HAC standard errors; predictive regressions cluster within months.

## 5. Mechanism evidence

- **Information channel rejected:** macro releases, monetary policy announcements and earnings surprises (CRSP/Compustat/IBES + Bloomberg international and central bank announcements) do not explain the OD.
- **Inventory channel supported (Grossman–Miller):** sorting on closing RSV, negative end-of-day imbalances are followed by large overnight reversals; positive imbalances produce muted reversals; near-zero imbalances produce reversals indistinguishable from zero. Contemporaneous overnight order flow moves in the predicted direction.
- **Uncertainty interaction:** double sorts on closing RSV × VIX — reversals larger when imbalance is large *and* VIX high. VIX distribution similar across positive/negative imbalance days, so asymmetry is not a variance artifact.
- **Asymmetry rationalized** by dealer VaR constraints (Daníelsson–Shin–Zigrand; Adrian–Shin): sell-offs raise variance, tighten constraints, raise effective risk aversion, raise required compensation.
- **Volume-time recasting:** returns increase roughly linearly in signed volume up to ~60,000 contracts — about the cumulative volume reached by 03:00. Asian-hours volume runs 50–100× below US-hours volume (2009–2020), which is why reversal takes until Europe opens.
- **DST natural experiment (strongest identification):** Japan does not observe DST, US does, so Tokyo's open shifts 19:00→20:00 ET between US winter and summer. RSV loadings shift forward by exactly one hour: β_RSV = {−9.34, −13.46, −6.70} for 18–19/19–20/20–21 in winter versus {1.43, −1.43, −6.85} in summer. Repeating on the ~3 weeks of asynchronous US/EU DST moves predictability to 04:00–05:00 as expected.

## 6. Trading results (Table IX; 2004.1–2020.12, annualized %)

**Gross (mid-quote):**

| | CTC | CTO | OTC | OD (2:00–3:00) | OD+ (1:30–3:30) | BtD (OD+ if RSV_close<0) |
|---|---|---|---|---|---|---|
| Mean | 8.95 | 4.62 | 4.20 | 3.75 | 6.21 | 6.07 |
| SD | 19.35 | 11.23 | 14.90 | 2.65 | 4.13 | 2.95 |
| Sharpe | 0.42 | 0.34 | 0.23 | **1.10** | **1.30** | **1.78** |
| Beta | 1.00 | 0.37 | 0.63 | 0.02 | 0.04 | 0.02 |
| Skew / Kurt | 0.01 / 20.1 | −0.67 / 20.9 | −0.33 / 13.7 | 1.18 / 32.9 | 2.16 / 41.9 | 4.89 / 98.6 |

**Net of bid-ask (crossing the spread both legs):**

| | CTC | CTO | OTC | OD | OD+ | BtD |
|---|---|---|---|---|---|---|
| Mean | 8.95 | 0.38 | −0.05 | **−0.59** | 1.91 | **4.04** |
| Sharpe | 0.42 | −0.04 | −0.06 | **−0.54** | 0.26 | **1.10** |

Cumulative $1 from 2004: gross OD → $1.9, OD+ → $2.8; net of costs OD is unprofitable, BtD → $1.9 (below passive CTC but with far higher Sharpe and no business-cycle drawdowns). Sample starts 2004 because the overnight spread hits the 1-tick minimum there.

Authors' own summary: the pattern is "not easily profitable"; the practical takeaway they push is **execution timing for asset managers**, not a standalone strategy.

---

## 7. Evaluation

### Holds up well
- **The statistical fact is real and carefully established.** Bootstrap + BY/Bonferroni + subsample stability + day-of-week/month breakdowns is more multiple-testing discipline than most intraday-seasonality papers apply. t = 7.1 over 23 years on ~5,800 daily observations is not a marginal result.
- **The mechanism is tested, not asserted.** Most "overnight return" papers stop at the decomposition. Here the imbalance sorts, VIX conditioning, volume-time recasting, and especially the DST experiment give a causal chain: EOD imbalance → dealer inventory → compensation paid when new counterparties arrive. The DST test is hard to fake with data mining, since the treatment timing is exogenous to markets.
- **Costs are reported honestly.** Full-spread crossing on both legs is a conservative execution assumption, and the authors publish the negative net Sharpe rather than burying it.

### Real weaknesses
- **The tradable version is thin by construction.** Gross edge is ~1.5 bps/day. One ES tick (0.25 index points) is ~0.6 bps at index 4000 and ~2 bps at index 1200 (2004). A round-trip crossing consumes roughly the entire gross return over most of the sample — which is exactly the paper's own finding (OD net Sharpe −0.54). Any conclusion depends almost entirely on execution assumptions.
- **Only the conditional strategy survives, and it survives partly by trading less.** BtD's net Sharpe of 1.1 comes from trading ~50% of days, on the days with the highest gross returns. Its skew 4.9 / kurtosis 98.6 means the P&L is concentrated in a small number of sell-off nights; the effective sample of return-generating events is much smaller than 4,300 days, so the Sharpe is less precisely estimated than it appears.
- **No market impact, commissions, financing, slippage, or capacity analysis.** Bid-ask only. Also no analysis of how much capital the strategy absorbs before the imbalance it monetizes is itself competed away — which matters, since the claimed source of the return is finite dealer risk-bearing capacity.
- **Passive-crossing assumption is one-sided.** The authors argue market makers deliberately set books so the "correct" trade pays the spread. Fair, but it also means the strategy is only viable for someone posting liquidity — and if you are posting, you are competing directly with the dealers whose compensation the paper is measuring. Fill probability is not modeled.
- **The asymmetry explanation is the least-tested link.** The VaR-constraint story is a conjecture with a simple model extension and a dealer-VaR calibration, not a direct test on intermediary balance-sheet data. It is the piece that carries the *unconditional* positivity of the drift, so it matters.
- **Single instrument.** ES only. No cross-market replication in the main paper (Nikkei, DAX, Treasury or FX futures) — the geographic mechanism predicts analogues elsewhere and testing them would sharpen the claim considerably.

### Out-of-sample status (important)
- Bondarenko and Muravyev (2020) independently replicate the fact that most CTC futures returns accrue around the European open.
- **NightShares** launched NSPY/NIWM ETFs in June 2022 explicitly to harvest the drift; both closed after ~14 months.
- The same authors published **"The Disappearing Overnight Drift"** (SSRN 7035838; NY Fed Liberty Street Economics, July 2026): the 02:00–03:00 window is **flat over Jan 2021 – Dec 2025** while CTC still returned 5.9% p.a. Their diagnosis is consistent with the original mechanism rather than a repudiation of it: the **standard deviation of closing RSV fell from 6.5% to 2.9%** (>50% compression), with VIX and overnight liquidity roughly unchanged — i.e. algorithmic execution now slices EOD orders finely enough that little residual inventory is passed into the night. No imbalance, no compensation.

### Bottom line
Strong empirical economics, weak standalone trading signal, and now an expired one. The in-sample fact is well established and the inventory-risk mechanism is unusually well identified for this literature. But the headline edge is roughly one tick per day, the only cost-surviving variant depends on a fat-tailed subset of days, and the effect has been flat for five years since the paper's sample ends — with the authors themselves attributing that to the disappearance of the input variable the whole mechanism runs on. Most useful today as (a) a template for how to test an intraday seasonality (bootstrap + BY + exogenous timing experiment) and (b) a caution that a t-stat of 7 over 23 years says nothing about whether an effect will still be there next year.

### Adjacent but distinct
The retail/attention-based overnight anomaly in *individual stocks* (Lou–Polk–Skouras "tug of war"; Elm Wealth's long-short version reporting large gross returns pre-cost) is a different effect with a different proposed mechanism. Do not pool the numbers.

---

## Sources
- FRB NY Staff Report 917 (revised Aug 2022) — full text, all numbers above.
- SSRN abstract 3546173 / paper 4191759; RFS 36(9), 2023.
- Liberty Street Economics, "The Disappearing Overnight Drift," July 2026.
- Bogousslavsky, FMA 2022 discussion of the paper (not readable in extraction; not relied on).
