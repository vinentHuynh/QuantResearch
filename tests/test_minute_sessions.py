import unittest

import numpy as np
import pandas as pd

from strategy_engine.data import session_bars, _resampled_session_bars
from strategy_engine.sessions import SESSIONS


class MinuteSessionParityTests(unittest.TestCase):
    def frame(self, start, end):
        index=pd.date_range(start,end,freq='min',inclusive='left',tz='UTC',name='ts_event')
        close=100+np.arange(len(index))*.001
        return pd.DataFrame({'open':close,'high':close+1,'low':close-1,'close':close+.2,
                             'volume':np.arange(len(index),dtype=np.uint64)},index=index)

    def check(self, frame, session):
        pd.testing.assert_frame_equal(session_bars(frame,session,'1m'),_resampled_session_bars(frame,session,'1m'))

    def test_all_sessions_weekends_and_dst(self):
        for start,end in [('2024-03-08','2024-03-12'),('2024-11-01','2024-11-05')]:
            frame=self.frame(start,end)
            frame=frame.drop(frame.index[::73])
            for session in SESSIONS.values():
                with self.subTest(start=start,session=session.id):
                    self.check(frame,session)

    def test_subminute_duplicates_unordered_empty_and_nulls(self):
        frame=self.frame('2024-03-11 13:00','2024-03-11 21:00')
        session=SESSIONS['new-york-rth']
        for changed in [frame.iloc[::-1],pd.concat([frame,frame.iloc[:3]]).sort_index(),
                        frame.set_axis(frame.index+pd.Timedelta(seconds=5)),frame.iloc[:0]]:
            self.check(changed,session)
        frame['volume']=frame.volume.astype(float)
        frame.iloc[45,frame.columns.get_loc('volume')]=float('nan')
        frame.iloc[46,frame.columns.get_loc('close')]=float('nan')
        self.check(frame,session)

    def test_daily_resampling_unchanged(self):
        frame=self.frame('2024-03-08','2024-03-12')
        session=SESSIONS['new-york-rth']
        pd.testing.assert_frame_equal(session_bars(frame,session,'1d'),_resampled_session_bars(frame,session,'1d'))


if __name__=='__main__':
    unittest.main()
