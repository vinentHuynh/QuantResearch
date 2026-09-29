"""Combined geometry must preserve both established reference families."""
import itertools
import unittest
import numpy as np
import pandas as pd
from strategies import _snd_combination_reference as combined
from strategies import _snd_zone_quality as quality
from strategies import _snd_body_retest as body
from test_snd_zone_quality import source_frame, prepare, HISTORY, BASE, FILL, run

class CombinationReferenceTests(unittest.TestCase):
    def test_wick_parity_for_crossed_rules(self):
        for mirror,eligibility,ttl,stop,fvg,htf in itertools.product(
                [False,True],['first_touch','any_touch'],[1,3],['zone','candle'],[False,True],[False,True]):
            frame=source_frame(HISTORY+BASE+[FILL],mirror=mirror,minute=True)
            data=prepare(frame,execution_minutes=1,bias=-1 if mirror else 1)
            p=dict(entry_eligibility=eligibility,order_lifetime_bars=ttl,stop_model=stop,require_fvg=fvg,use_htf=htf)
            old=run(data,model=quality,**p)
            new=run(data,model=combined,**p)
            pd.testing.assert_frame_equal(old['trades'],new['trades'],check_exact=True)
            pd.testing.assert_frame_equal(old['equity'],new['equity'],check_exact=True)

    def test_body_matches_historical_body_engine(self):
        rows=HISTORY+[(100,101,99,99.5),(98,104,97,103),(103,104,102,103.5),(102,103,99,102),FILL]
        for mirror,stop in itertools.product([False,True],['zone','candle']):
            data=prepare(source_frame(rows,mirror=mirror,minute=True),execution_minutes=1,bias=-1 if mirror else 1)
            p=dict(zone_boundary='body',stop_model=stop)
            old=run(data,model=body,**p)
            new=run(data,model=combined,**p)
            self.assertGreater(len(old['trades']),0)
            pd.testing.assert_frame_equal(old['trades'],new['trades'][old['trades'].columns],check_exact=True)
            pd.testing.assert_frame_equal(old['equity'],new['equity'],check_exact=True)

    def test_body_width_uses_body_edges_and_prior_atr(self):
        rows=HISTORY+[(100,101,99,99.5),(98,104,97,103),(103,104,102,103.5),(102,103,99,102),FILL]
        data=prepare(source_frame(rows,minute=True),execution_minutes=1)
        t=run(data,model=combined,zone_boundary='body')['trades'].iloc[0]
        self.assertEqual(t.zone_width_atr,(t.zone_top-t.zone_bottom)/t.prior_atr20)
        self.assertEqual(len(run(data,model=combined,zone_boundary='body',max_zone_width_atr=t.zone_width_atr)['trades']),1)
        self.assertEqual(len(run(data,model=combined,zone_boundary='body',max_zone_width_atr=t.zone_width_atr-.01)['trades']),0)

    def test_invalid_boundary_rejected(self):
        data=prepare(source_frame(HISTORY+BASE+[FILL]))
        with self.assertRaisesRegex(ValueError,'zone_boundary'):
            run(data,model=combined,zone_boundary='close_only')

if __name__=='__main__': unittest.main()
