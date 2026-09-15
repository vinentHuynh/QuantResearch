"""Historical Pine ports: explicit completed-day features and per-bar orders."""
import math
import numpy as np
import pandas as pd


def clock(index, timezone):
    local = pd.DatetimeIndex(index).tz_convert(timezone)
    return local.hour * 60 + local.minute


def inside(value, start, end):
    return (value >= start) & (value < end) if start < end else (value >= start) | (value < end)


def daily_features(bars, parameters):
    """Known daily values at each chart bar OPEN (security lookahead_off [1]).

    Daily prices come from the selected futures' 18:00–17:00 NY session,
    not TradingView settlement prices or a second signal symbol.
    """
    daily = bars.groupby('session_date', sort=True).agg(open=('open', 'first'), close=('close', 'last'))
    # Publish on the calendar session close, never the final observed bar of an
    # incomplete input prefix. This keeps missing/partial days causal.
    publication = (pd.DatetimeIndex(pd.to_datetime(daily.index)) + pd.Timedelta(hours=17)).tz_localize('America/New_York')
    close = daily.close
    lengths = [parameters.get(k, v) for k, v in [('fast_length', 20), ('medium_length', 60), ('slow_length', 120), ('annual_length', 252)]]
    votes = pd.concat([np.sign(close - close.shift(n)) for n in lengths], axis=1)
    score = votes.mean(axis=1, skipna=False)
    window = parameters.get('volatility_length', 60)
    vol = close.diff().rolling(window).std(ddof=0)
    overnight = (daily.open - close.shift(1)).rolling(window).std(ddof=0)
    exposure = (score * parameters.get('annual_risk', .2) / np.sqrt(252) / vol * close.abs()).clip(-parameters.get('maximum_leverage', 2.), parameters.get('maximum_leverage', 2.)).where(vol > 0)
    known = pd.DataFrame({'score': score.to_numpy(), 'exposure': exposure.to_numpy(), 'overnight_vol': overnight.to_numpy(), 'daily_close': close.to_numpy()}, index=publication)
    return known.reindex(bars.index, method='ffill')


def quantity(raw, rounding='Nearest'):
    if not math.isfinite(raw):
        return 0
    value = math.floor(max(0., raw) + (.5 if rounding == 'Nearest' else 0.))
    if value > 100:
        raise ValueError('Position exceeds the workbench 100-contract limit; reduce risk or capital')
    return value


def validate(parameters, request):
    if request['session'] != 'full-trading-day':
        raise ValueError('Pine ports require Full trading day so overnight bars and daily signals are retained')
    if request.get('delay_bars', 0):
        raise ValueError('Pine event ports do not support delayed-execution stress yet')
    if 'annual_length' in parameters and request['warmup_days'] < 2 * max(parameters[k] for k in ('fast_length', 'medium_length', 'slow_length', 'annual_length')):
        raise ValueError('Use at least twice the longest daily lookback in warmup calendar days')
    if 'entry_hour' in parameters and (parameters['entry_hour'], parameters['entry_minute']) == (parameters['exit_hour'], parameters['exit_minute']):
        raise ValueError('Entry and exit clocks must differ')
    if 'rth_start' in parameters and parameters['rth_start'] >= parameters['rth_end']:
        raise ValueError('RTH start must be earlier than RTH end')
    if 'opening_start' in parameters and not (parameters['opening_start'] < parameters['opening_end'] <= parameters['entry_start'] < parameters['entry_end'] <= parameters['flatten_start'] < parameters['flatten_end']):
        raise ValueError('Opening, entry, and flatten windows must be ordered and non-overlapping')


class OvernightBlock:
    def __init__(self, bars, p, request):
        self.p = p
        self.window = inside(clock(bars.availability_time, p['timezone']), p['entry_hour'] * 60 + p['entry_minute'], p['exit_hour'] * 60 + p['exit_minute'])

    def on_close(self, i, bar, state):
        if not state['tradable']:
            return None
        now = self.window[i]
        prior = self.window[i - 1] if i else False
        if now and not prior:
            return {'target': self.p['contracts'], 'timing': 'next-open'}
        if not now and (prior or state['position']):
            return {'target': 0, 'timing': 'next-open'}


class DailyTrend:
    def __init__(self, bars, p, request):
        self.p, self.request, self.bars = p, request, bars
        self.known = daily_features(bars, p)

    def on_close(self, i, bar, state):
        if not state['tradable'] or (i and bar.session_date == self.bars.session_date.iloc[i - 1]):
            return None
        target = self.known.exposure.iloc[i]
        p = self.p
        raw = max(state['equity'], 0) / p['sleeve_count'] * abs(target) / (abs(bar.close) * self.request['dataset']['point_value']) if bar.close else 0
        count = p['contracts'] if p['sizing_mode'] == 'Fixed contracts' and pd.notna(target) and target != 0 else quantity(raw, p['rounding']) if p['sizing_mode'] == 'Vol-targeted' else 0
        return {'target': int(np.sign(target) * count) if pd.notna(target) else 0}


class OvernightDrift:
    def __init__(self, bars, p, request):
        self.p, self.request, self.bars = p, request, bars
        self.rth = inside(clock(bars.index, p['timezone']), p['rth_start'], p['rth_end'])
        self.known = daily_features(bars, p)
        self.open = self.high = self.low = self.close = np.nan

    def on_close(self, i, bar, state):
        current = self.rth[i]
        previous = self.rth[i - 1] if i else False
        if current and not previous:
            self.open, self.high, self.low = bar.open, bar.high, bar.low
        if current:
            self.high = max(self.high, bar.high) if pd.notna(self.high) else bar.high
            self.low = min(self.low, bar.low) if pd.notna(self.low) else bar.low
            self.close = bar.close
        if not state['tradable']:
            return None
        if current and not previous and state['position']:
            return {'target': 0, 'reason': 'RTH-start bar close'}
        if previous and not current and not state['position']:
            p = self.p
            if not p['trade_weekend'] and bar.name.tz_convert('America/Chicago').weekday() == 4:
                return None
            move = self.close - self.open
            location = (self.close - self.low) / (self.high - self.low) if self.high > self.low else .5
            direction = {'Long after up close': int(move > 0), 'Long after down close': int(move < 0),
                         'Long up / short down': int(np.sign(move)) if pd.notna(move) else 0,
                         'Strong close only (long)': int(location >= p['strong_threshold']), 'Always (no filter)': 1}[p['close_rule']]
            known = self.known.iloc[i]
            leverage = min(p['annual_risk'] / np.sqrt(252) / known.overnight_vol * abs(known.daily_close), p['maximum_leverage']) if known.overnight_vol > 0 else np.nan
            raw = max(0., state['equity']) / p['sleeve_count'] * leverage / (abs(bar.close) * self.request['dataset']['point_value']) if bar.close else 0
            count = p['contracts'] if p['sizing_mode'] == 'Fixed contracts' else quantity(raw)
            if direction and count:
                return {'target': direction * count, 'reason': 'RTH-ended bar close'}


class IntradayORB:
    def __init__(self, bars, p, request):
        self.p, self.request = p, request
        self.known = daily_features(bars, p)
        minutes = clock(bars.index, p['timezone'])
        self.opening = inside(minutes, p['opening_start'], p['opening_end'])
        self.entry = inside(minutes, p['entry_start'], p['entry_end'])
        self.flatten = inside(minutes, p['flatten_start'], p['flatten_end'])
        self.high = self.low = np.nan
        self.attempted = False

    def on_close(self, i, bar, state):
        p = self.p
        opening = self.opening[i]
        prior = self.opening[i - 1] if i else False
        if opening and not prior:
            self.high, self.low, self.attempted = bar.high, bar.low, False
            if state['tradable'] and state['position']:
                return {'target': 0, 'reason': 'overnight safety'}
        elif opening:
            self.high, self.low = max(self.high, bar.high), min(self.low, bar.low)
        if not state['tradable']:
            return None
        if self.flatten[i] and state['position']:
            return {'target': 0, 'reason': 'force-flat window'}
        score = self.known.score.iloc[i]
        direction = 1 if score >= p['minimum_score'] else -1 if score <= -p['minimum_score'] else 0
        long_break = direction > 0 and (bar.close > self.high if p['require_close_break'] else bar.high >= self.high)
        short_break = direction < 0 and (bar.close < self.low if p['require_close_break'] else bar.low <= self.low)
        if not opening and self.high > self.low and self.entry[i] and not self.attempted and not state['position'] and (long_break or short_break):
            self.attempted = True
            stop = self.low if long_break else self.high
            risk = abs(bar.close - stop)
            count = min(p['maximum_contracts'], math.floor(p['risk_budget'] / (risk * self.request['dataset']['point_value']))) if risk > 0 else 0
            if count:
                return {'target': count * direction, 'bracket': (stop, bar.close + direction * p['reward_risk'] * risk)}
