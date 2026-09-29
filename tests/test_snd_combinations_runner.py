"""Checks of coverage identities and compact accounting, not trading-rule copies."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('combination_runner_tests',ROOT/'scripts/research-snd-combinations.py')
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

class CombinationRunnerTests(unittest.TestCase):
    def test_zero_trade_case_keeps_complete_training_period_and_weekly_records(self):
        from strategies import _snd_combination_reference as reference
        analysis=runner.load_module('empty_case_analysis',ROOT/'scripts/analyze-snd-combinations.py')
        trades=pd.DataFrame(columns=reference.TRADE_COLUMNS)
        stamps=pd.to_datetime(['2023-12-31T23:59Z','2024-12-31T23:59Z',
                               '2025-12-31T23:59Z','2026-07-31T23:59Z'],utc=True)
        source=pd.DataFrame({'close':[100.]*4},index=stamps)
        equity=pd.DataFrame(dict(timestamp=stamps+pd.Timedelta(minutes=1),equity=100000.,
                                balance=100000.,unrealized_pnl=0.,net_pnl=0.,contracts=0))
        model=SimpleNamespace(run_model=lambda *a:dict(trades=trades,equity=equity,diagnostics={'trades':0}))
        config=dict(config_id='empty',parameters={key:values[0] for key,values in runner.GRID.items()})
        dataset=dict(symbol='MNQ',start='2022-01-01',end='2026-08-01',tick_size=.25,point_value=2.)
        protocol=dict(capital=100000.,folds=[dict(id=str(year),training_start='2022-01-01',cutoff=f'{year}-01-01')
                                           for year in [2024,2025,2026]])
        tables,result=runner.case_tables(config,dataset,None,source,model,analysis,protocol)
        self.assertEqual(len(tables['trades.parquet']),0)
        self.assertEqual(len(tables['training.parquet']),3)
        self.assertEqual(tables['training.parquet'].trades.tolist(),[0,0,0])
        self.assertEqual(tables['weekly.parquet'].trades.sum(),0)
        self.assertEqual(result['summary']['trades'],0)
        self.assertEqual(result['summary']['net_pnl'],0)
        self.assertEqual(result['summary']['max_drawdown'],0)

    def test_parallel_shards_are_disjoint_complete_and_resume_stable(self):
        for count in [1,63,64,65,10368]:
            for limit in [None,1,3]:
                expected=runner.shard_partition(count,64,limit)
                for workers in [1,2,3,8]:
                    partitions=[runner.shard_partition(count,64,limit,offset,workers) for offset in range(workers)]
                    actual=[item for partition in partitions for item in partition]
                    self.assertEqual(sorted(actual),expected)
                    self.assertEqual(len(actual),len(set(actual)))

    def test_complete_unique_cartesian_coverage(self):
        configs=runner.configurations({})
        self.assertEqual(len(configs),10368)
        self.assertEqual(configs[0]['config_id'],'c00000')
        self.assertEqual(configs[-1]['config_id'],'c10367')
        for key,levels in runner.GRID.items():
            for value in levels:
                self.assertEqual(sum(c['parameters'][key]==value for c in configs),len(configs)//len(levels))

    def test_daily_midnight_and_accounting(self):
        equity=pd.DataFrame(dict(timestamp=pd.to_datetime(['2024-01-01T12:00Z','2024-01-02T00:00Z',
             '2024-01-02T12:00Z','2024-01-03T00:00Z'],utc=True),equity=[110.,105.,95.,108.],
             net_pnl=[10.,-5.,-10.,13.],balance=[110.,105.,95.,108.],unrealized_pnl=0.,contracts=0))
        daily=runner.daily_equity(equity,100.)
        self.assertEqual(daily.equity.tolist(),[105.,108.])
        self.assertEqual(daily.net_pnl.tolist(),[5.,3.])
        self.assertEqual(daily.net_pnl.sum(),equity.net_pnl.sum())

    def test_period_drawdown_keeps_initial_capital_and_intraday_low(self):
        equity=pd.DataFrame(dict(timestamp=pd.to_datetime(['2024-01-01T00:00Z','2024-01-01T12:00Z',
            '2024-01-02T00:00Z','2025-01-01T00:00Z'],utc=True),equity=[100.,80.,102.,103.]))
        trades=pd.DataFrame(columns=['exit_time','exit_reason','entry_time','net_pnl','gross_pnl','cost','risk_cash','net_r'])
        record=next(r for r in runner.period_metrics(trades,equity,100.) if r['period']=='year_2024')
        self.assertEqual(record['max_drawdown'],20.)
        self.assertEqual(record['net_pnl'],3.)
        self.assertEqual(record['marked_observations'],3)

    def test_forced_exit_boundary_and_weekly_partial_period(self):
        t=pd.DataFrame(dict(exit_time=pd.to_datetime(['2025-01-01T00:00Z']*2,utc=True),
            exit_reason=['target','end-of-test'],net_r=[2.,-1.],net_pnl=[20.,-10.],cost=[1.,1.],risk_cash=[10.,10.]))
        mask=runner.closed_mask(t,pd.Timestamp('2025-01-01',tz='UTC'),pd.Timestamp('2026-01-01',tz='UTC'))
        self.assertEqual(mask.tolist(),[True,False])
        weekly=runner.weekly_metrics(t.loc[mask])
        self.assertEqual(weekly.net_r_sum.sum(),2.)
        self.assertEqual(weekly.trades.sum(),1.)
        self.assertEqual(len(weekly),240)

    def test_successful_resume_rechecks_every_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)/'shard-0000'
            attempt=folder/'attempt-000'
            attempt.mkdir(parents=True)
            identity=dict(protocol_checksum='p',source_hash='s',configurations_checksum='c')
            for name in runner.ARTIFACTS: (attempt/name).write_text('immutable',encoding='utf-8')
            runner.save(attempt/'result.json',dict(status='succeeded',config_ids=['c00000'],**identity,
                artifacts=[dict(name=name,checksum=runner.checksum(attempt/name)) for name in runner.ARTIFACTS]))
            runner.save(attempt/'status.json',dict(status='succeeded'))
            self.assertIsNotNone(runner.existing_attempt(folder,identity,['c00000'])[0])
            (attempt/'weekly.parquet').write_text('changed',encoding='utf-8')
            with self.assertRaisesRegex(AssertionError,'Artifact modified'):
                runner.existing_attempt(folder,identity,['c00000'])

if __name__=='__main__': unittest.main()
