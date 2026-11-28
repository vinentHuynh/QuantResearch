"""Weekday breaks of the previous completed week's NQ high and low."""

import pandas as pd

from study import ROOT, load_bars


AS_OF = pd.Timestamp("2026-11-27")
OUTPUT = ROOT / "artifacts/research/prior-period-extremes/nq-weekdays.csv"


def daily_observations():
    bars = load_bars("NQ")
    daily = bars.groupby("date").agg(
        high=("high", "max"), low=("low", "min"), offset=("offset", "first"),
        late_session=("late_session", "any"),
    )
    week = daily.index.to_period("W-SUN")
    weekly = daily.groupby(week).agg(
        prior_high=("high", "max"), prior_low=("low", "min"), late=("late_session", "any"),
    )
    # Join on the actual preceding calendar week. A missing week cannot shift the reference.
    daily["reference_week"] = week - 1
    daily = daily.join(weekly[["prior_high", "prior_low"]], on="reference_week")
    start = AS_OF - pd.DateOffset(years=3)
    complete = (week.start_time >= start) & (week < daily.index[-1].to_period("W-SUN"))
    complete &= (week.end_time.normalize() - pd.Timedelta(days=2)) <= AS_OF
    complete &= ~(week.map(weekly.late) | (week - 1).isin(weekly.index[weekly.late]))
    daily = daily.loc[complete].copy()
    assert daily[["prior_high", "prior_low"]].notna().all().all()
    daily["week_start"] = daily.index.to_period("W-SUN").start_time
    daily["weekday"] = daily.index.day_name()
    daily["above_prior_high"] = daily.high > daily.prior_high
    daily["below_prior_low"] = daily.low < daily.prior_low
    for side, flag in [("high", "above_prior_high"), ("low", "below_prior_low")]:
        earlier_breaks = daily.groupby("week_start")[flag].cumsum() - daily[flag].astype(int)
        daily[f"{side}_intact_at_start"] = earlier_breaks.eq(0)
        daily[f"first_{side}_break"] = daily[flag] & earlier_breaks.eq(0)
    daily["neither"] = ~(daily.above_prior_high | daily.below_prior_low)
    # Display all price levels on the contract scale at the start of each session.
    prices = ["prior_high", "prior_low", "high", "low"]
    daily[prices] = daily[prices].add(daily.offset, axis="index")
    return daily.drop(columns=["offset", "late_session"])


def main():
    daily = daily_observations()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(OUTPUT)
    counts = daily.groupby(daily.index.dayofweek).agg(
        weekday=("weekday", "first"), sessions=("weekday", "size"),
        high=("above_prior_high", "sum"), low=("below_prior_low", "sum"), neither=("neither", "sum"),
        high_intact=("high_intact_at_start", "sum"), first_high=("first_high_break", "sum"),
        low_intact=("low_intact_at_start", "sum"), first_low=("first_low_break", "sum"),
    )
    print(counts.to_string(index=False))
    print(f"{daily.week_start.nunique()} weeks, {len(daily)} sessions")


if __name__ == "__main__":
    main()
