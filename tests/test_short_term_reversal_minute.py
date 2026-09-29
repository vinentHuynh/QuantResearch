import unittest

import pandas as pd

from strategies.short_term_reversal_minute import STRATEGY, MinuteReversal, completed_rth_days, schedule, signals
from workbench.contract import resolve_parameters
from workbench.events import simulate_events


class ReversalMinuteTests(unittest.TestCase):
    def bars(self):
        parts=[]
        for date, price in [('2024-03-06',80.),('2024-03-07',100.),('2024-03-08',98.),('2024-03-11',99.),('2024-03-12',101.)]:
            index=pd.date_range(date+' 09:25',date+' 16:00',freq='min',tz='America/New_York')
            part=pd.DataFrame({'open':price,'high':price+.1,'low':price-.1,'close':price,
                               'availability_time':index+pd.Timedelta(minutes=1)},index=index)
            parts.append(part)
        return pd.concat(parts)

    def params(self, **edits):
        return resolve_parameters(STRATEGY, {'trend_lookback':3, **edits})

    def test_no_incomplete_daily_bar_can_leak(self):
        bars=self.bars()
        prefix=bars.loc[:'2024-03-08 12:00']
        self.assertEqual(len(completed_rth_days(prefix)),2)
        self.assertTrue((signals(prefix,self.params())==0).all())

    def test_monday_entry_dst_and_tuesday_exit(self):
        bars=self.bars()
        target=signals(bars,self.params())
        request={'start':'2024-03-06','end':'2024-03-12','capital':100000,'fee':2.5,'slippage':1,
                 'dataset':{'point_value':20,'tick_size':.25}}
        _,trades,_=simulate_events(bars,MinuteReversal(bars,self.params()),request)
        self.assertEqual(len(trades),1)
        self.assertEqual(pd.Timestamp(trades.iloc[0].entry_time),pd.Timestamp('2024-03-11 09:30',tz='America/New_York'))
        self.assertEqual(pd.Timestamp(trades.iloc[0].exit_time),pd.Timestamp('2024-03-12 09:30',tz='America/New_York'))
        self.assertEqual(trades.iloc[0].net_pnl,25.)

    def test_offset_applies_to_both_sides(self):
        bars=self.bars(); target=signals(bars,self.params(open_delay_minutes=5))
        request={'start':'2024-03-06','end':'2024-03-12','capital':100000,'fee':2.5,'slippage':1,
                 'dataset':{'point_value':20,'tick_size':.25}}
        _,trades,_=simulate_events(bars,MinuteReversal(bars,self.params(open_delay_minutes=5)),request)
        self.assertEqual(pd.Timestamp(trades.iloc[0].entry_time).minute,35)
        self.assertEqual(pd.Timestamp(trades.iloc[0].exit_time).minute,35)

    def test_future_and_partial_day_changes_preserve_past(self):
        bars=self.bars(); p=self.params(); expected=signals(bars,p)
        for ending in ['2024-03-08 12:00','2024-03-11 09:29','2024-03-11 10:00','2024-03-11 16:00']:
            prefix=bars.loc[:ending]
            pd.testing.assert_series_equal(expected.loc[prefix.index],signals(prefix,p))
        changed=bars.copy(); changed.loc['2024-03-11 10:00':,['high','close']]=1000.
        pd.testing.assert_series_equal(expected.loc[:'2024-03-11 09:59'],signals(changed,p).loc[:'2024-03-11 09:59'])

    def test_missing_deadline_does_not_backdate_and_late_entry_is_skipped(self):
        bars=self.bars()
        bars=bars.drop(bars.loc['2024-03-11 09:29':'2024-03-11 09:40'].index)
        updates=schedule(bars,self.params())
        monday=updates.loc[updates.decision_time.dt.date==pd.Timestamp('2024-03-11').date()].iloc[0]
        self.assertGreater(monday.lateness_minutes,5)
        self.assertEqual(monday.target,0)

    def test_missing_rth_quotes_expire_entry_before_evening_reopen(self):
        bars=self.bars()
        bars=bars.drop(bars.loc['2024-03-11 09:30':'2024-03-11 16:00'].index)
        evening=bars.iloc[-1:].copy()
        evening.index=pd.DatetimeIndex([pd.Timestamp('2024-03-11 18:00',tz='America/New_York')])
        evening['availability_time']=evening.index+pd.Timedelta(minutes=1)
        bars=pd.concat([bars,evening]).sort_index()
        request={'start':'2024-03-06','end':'2024-03-12','capital':100000,'fee':2.5,'slippage':1,
                 'dataset':{'point_value':20,'tick_size':.25}}
        _,trades,_=simulate_events(bars,MinuteReversal(bars,self.params()),request)
        self.assertEqual(len(trades),1)
        self.assertEqual(pd.Timestamp(trades.iloc[0].entry_time),pd.Timestamp('2024-03-12 09:30',tz='America/New_York'))

    def test_scoring_does_not_open_a_warmup_position_on_evening_reopen(self):
        bars=self.bars()
        request={'start':'2024-03-11 17:00','end':'2024-03-12','capital':100000,'fee':2.5,'slippage':1,
                 'dataset':{'point_value':20,'tick_size':.25}}
        _,trades,_=simulate_events(bars,MinuteReversal(bars,self.params()),request)
        self.assertTrue(trades.empty)

    def test_exit_on_closed_day_expires_and_retries_next_rth_open(self):
        bars=self.bars()
        bars=bars.drop(bars.loc['2024-03-12 09:30':'2024-03-12 16:00'].index)
        extra=pd.DatetimeIndex([pd.Timestamp('2024-03-12 18:00',tz='America/New_York'),
                               pd.Timestamp('2024-03-13 09:29',tz='America/New_York'),
                               pd.Timestamp('2024-03-13 09:30',tz='America/New_York')])
        frame=pd.DataFrame({'open':102.,'high':103.,'low':101.,'close':102.,'availability_time':extra+pd.Timedelta(minutes=1)},index=extra)
        bars=pd.concat([bars,frame]).sort_index()
        request={'start':'2024-03-06','end':'2024-03-13','capital':100000,'fee':2.5,'slippage':1,
                 'dataset':{'point_value':20,'tick_size':.25}}
        _,trades,_=simulate_events(bars,MinuteReversal(bars,self.params()),request)
        self.assertEqual(len(trades),1)
        self.assertEqual(pd.Timestamp(trades.iloc[0].exit_time),pd.Timestamp('2024-03-13 09:30',tz='America/New_York'))
        self.assertEqual(trades.iloc[0].exit_reason,'scheduled-reversal-exit')


if __name__=='__main__':
    unittest.main()
