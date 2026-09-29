"""Frozen NinjaTrader CME US Index Futures ETH daytime-session calendar.

Derived from installed template version 5119 (Central Standard Time), copied to
reports/tsmom-orb-fix-2026-09-29/audit-calendar-CME-US-Index-Futures-ETH.xml.
The template is vendor-maintained exchange schedule metadata, NOT proof of the
calendar vintage known on each historical date. No close is inferred from
future market bars. Coverage is explicitly limited to 2016-2026; refresh/review
rather than extrapolate. End times are Chicago HHMM, including DST conversion.

The only late-begin override, Christmas 2024, begins 18:00 ET for the following
session and has no daytime ORB session on that calendar date. Return None.
Full and partial holiday tables were checked and have no date conflicts.
Good Friday 2026 is partial 09:15 ET, not a full-day holiday in this snapshot.
"""
from __future__ import annotations

import pandas as pd

FIRST_YEAR = 2016
LAST_YEAR = 2026
TEMPLATE_NAME = 'CME US Index Futures ETH'
TEMPLATE_VERSION = 5119
SOURCE_SHA256 = '370b17f23eeea694e686394b5fdb9b55681089c22d5232d5e6a354a314325620'
SOURCE_REPORT_PATH = 'reports/tsmom-orb-fix-2026-09-29/audit-calendar-CME-US-Index-Futures-ETH.xml'
CALENDAR_VERSION = 'nt-eth-5119-370b17f23eee-2016-2026'

FULL_HOLIDAYS = {'2016-01-01': "New Year's Day",
 '2016-03-25': 'Good Friday',
 '2016-12-26': 'Christmas Day',
 '2017-01-02': "New Year's Day",
 '2017-04-14': 'Good Friday',
 '2017-12-25': 'Christmas Day',
 '2018-01-01': "New Year's Day",
 '2018-03-30': 'Good Friday',
 '2018-12-25': 'Christmas Day',
 '2019-01-01': "New Year's Day",
 '2019-04-19': 'Good Friday',
 '2019-12-25': 'Christmas Day',
 '2020-01-01': "New Year's Day",
 '2020-04-10': 'Good Friday',
 '2020-12-25': 'Christmas Day',
 '2021-01-01': "New Year's Day",
 '2021-12-24': 'Christmas Eve',
 '2022-01-01': "New Year's Day",
 '2022-12-24': 'Christmas Eve',
 '2022-12-26': 'Boxing Day',
 '2023-01-02': "New Year's Day",
 '2023-12-24': 'Christmas Eve',
 '2023-12-25': 'Christmas Day',
 '2024-01-01': "New Year's Day",
 '2024-03-29': 'Good Friday',
 '2025-01-01': "New Year's Day",
 '2025-04-18': 'Good Friday',
 '2025-12-25': 'Christmas Day',
 '2026-01-01': "New Year's Day",
 '2026-12-25': 'Christmas Day'}
EARLY_CLOSE_CT_HHMM = {'2016-01-18': 1200,
 '2016-02-15': 1200,
 '2016-05-30': 1200,
 '2016-07-04': 1200,
 '2016-09-05': 1200,
 '2016-11-24': 1200,
 '2016-11-25': 1215,
 '2017-01-16': 1200,
 '2017-02-20': 1200,
 '2017-05-29': 1200,
 '2017-07-03': 1215,
 '2017-07-04': 1200,
 '2017-09-04': 1200,
 '2017-11-23': 1200,
 '2017-11-24': 1215,
 '2018-01-15': 1200,
 '2018-02-19': 1200,
 '2018-05-28': 1200,
 '2018-07-03': 1215,
 '2018-07-04': 1200,
 '2018-09-03': 1200,
 '2018-11-22': 1200,
 '2018-11-23': 1215,
 '2018-12-24': 1215,
 '2019-01-21': 1200,
 '2019-02-18': 1200,
 '2019-05-27': 1200,
 '2019-07-03': 1215,
 '2019-07-04': 1200,
 '2019-09-02': 1200,
 '2019-11-28': 1200,
 '2019-11-29': 1215,
 '2019-12-24': 1215,
 '2020-01-20': 1200,
 '2020-02-17': 1200,
 '2020-05-25': 1200,
 '2020-07-03': 1200,
 '2020-09-07': 1200,
 '2020-11-26': 1200,
 '2020-11-27': 1215,
 '2020-12-24': 1215,
 '2021-01-18': 1200,
 '2021-02-15': 1200,
 '2021-04-02': 815,
 '2021-05-31': 1200,
 '2021-07-05': 1200,
 '2021-09-06': 1200,
 '2021-11-25': 1200,
 '2021-11-26': 1215,
 '2022-01-17': 1200,
 '2022-02-21': 1200,
 '2022-04-15': 815,
 '2022-05-30': 1200,
 '2022-06-20': 1200,
 '2022-07-04': 1200,
 '2022-09-05': 1200,
 '2022-11-24': 1200,
 '2022-11-25': 1215,
 '2023-01-16': 1200,
 '2023-02-20': 1200,
 '2023-04-07': 815,
 '2023-05-29': 1200,
 '2023-06-19': 1200,
 '2023-07-03': 1215,
 '2023-07-04': 1200,
 '2023-09-04': 1200,
 '2023-11-23': 1200,
 '2023-11-24': 1215,
 '2024-01-15': 1200,
 '2024-02-19': 1200,
 '2024-03-28': 1600,
 '2024-05-27': 1200,
 '2024-06-19': 1200,
 '2024-07-03': 1215,
 '2024-07-04': 1200,
 '2024-09-02': 1200,
 '2024-11-28': 1200,
 '2024-11-29': 1215,
 '2024-12-24': 1215,
 '2025-01-09': 830,
 '2025-01-20': 1200,
 '2025-02-17': 1200,
 '2025-04-17': 1600,
 '2025-05-26': 1200,
 '2025-06-19': 1200,
 '2025-07-03': 1215,
 '2025-07-04': 1200,
 '2025-09-01': 1200,
 '2025-11-27': 1200,
 '2025-11-28': 1215,
 '2025-12-24': 1215,
 '2026-01-19': 1200,
 '2026-02-16': 1200,
 '2026-04-02': 1600,
 '2026-04-03': 815,
 '2026-05-25': 1200,
 '2026-06-19': 1200,
 '2026-07-03': 1200,
 '2026-09-07': 1200,
 '2026-11-26': 1200,
 '2026-11-27': 1215,
 '2026-12-24': 1215}
NO_DAYTIME_SESSION_LATE_BEGIN_CT_HHMM = {'2024-12-25': 1700}


def session_close_et(date):
    """Return this local calendar day's declared close in New York, or None.

    Accept a date, ISO date string or Timestamp. A timezone-aware Timestamp is
    first converted to New York. Raise ValueError outside frozen year coverage.
    None means weekend, full holiday, or the documented no-daytime-session
    late-begin override. An early close before 09:30 remains a real close; the
    caller must reject any ORB window that cannot finish before it.
    """
    value = pd.Timestamp(date)
    if pd.isna(value):
        raise ValueError('Calendar date must be finite')
    if value.tzinfo is not None:
        value = value.tz_convert('America/New_York').tz_localize(None)
    day = value.normalize()
    if not FIRST_YEAR <= day.year <= LAST_YEAR:
        raise ValueError(f'CME index calendar covers {FIRST_YEAR}-{LAST_YEAR}; requested {day.date()}')
    key = day.date().isoformat()
    if day.dayofweek >= 5 or key in FULL_HOLIDAYS or key in NO_DAYTIME_SESSION_LATE_BEGIN_CT_HHMM:
        return None
    hhmm = EARLY_CLOSE_CT_HHMM.get(key, 1600)
    wall = day + pd.Timedelta(hours=hhmm //100, minutes=hhmm %100)
    return wall.tz_localize('America/Chicago').tz_convert('America/New_York')
