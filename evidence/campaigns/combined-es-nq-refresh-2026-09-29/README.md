# ES/NQ combined portfolio refresh — September 29, 2026

The original research runs, evaluations, campaign reports, and dataset versions
were retained. `pre-refresh-index.json` captures the catalog before this update.

Five existing portfolio sleeves were replayed with the newly registered,
immutable ES and NQ minute datasets. The replay scripts used frozen Workbench
source snapshots for the Pine overnight, Pine TSMOM ORB, and minute reversal
rules, and the original `session_drift` rule for the two Expanded overnight
books. Raw ledgers, inputs, source/data identities, session checks, and
checksums are in `workbench/` and `expanded/`.

`scripts/build-collective.py` loads all five checked extensions together. It
preserves the existing catalog IDs, removes the ES Pine overnight run's
artificial August 31 end-of-test trade in the derived history, and adjusts the
August 31 marked P&L for positions opened that evening. The frozen source
artifacts remain unchanged. The refreshed catalog and series are served by the
Workbench API; `portfolio-verification.json` records the calculated results.

ES overnight histories reach September 29. NQ histories reach September 28;
the September 29 NQ overnight session was incomplete at the Databento cutoff.
The five ES/NQ sleeves have a common window through September 28. The original
seven-book combination still has a common end of August 31 because its YM and
MNQ sleeves were not refreshed. The September continuation is exploratory
historical evidence. Earlier evaluation labels do not validate the new dates.
The two ES overnight sleeves are highly correlated exposures.

Verification: focused collective importer tests, the real collective check,
the production build, and live API catalog/series checks passed. The app's
browser page was not visually inspected because no browser surface was
available in this session.
