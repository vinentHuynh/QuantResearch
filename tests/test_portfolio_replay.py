"""Portfolio replay verification and crash-safe catalog overlay tests."""
from __future__ import annotations

import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('portfolio_replay_under_test',ROOT/'scripts/portfolio-replay.py')
replay=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)
builder=replay.builder


def day(day,pnl,terminal=False):
    return {'date':day,'pnl':pnl,'segment':'2026-01-01/2026-01-02','terminal':terminal}


def trade(day,pnl,synthetic=False):
    return {'entry':f'{day}T12:00:00+00:00','exit':f'{day}T13:00:00+00:00',
            'pnl':pnl,'quantity':1,'cost':1,'exit_reason':'end-of-test' if synthetic else 'signal',
            'synthetic_exit':synthetic}


class ReplayMergeTest(unittest.TestCase):
    def setUp(self):
        self.item={'id':'book','source':'Current workbench','start':'2026-01-01','end':'2026-01-02',
                   'coverage':[{'start':'2026-01-01','end':'2026-01-02'}],
                   'capital':1000,'parameters':{},'reasons':[],'source_run_ids':['base']}
        self.old={'id':'book','daily':[day('2026-01-01',5),day('2026-01-02',10,True)],
                  'trades':[trade('2026-01-01',5),trade('2026-01-02',10)],
                  'coverage':self.item['coverage']}
        self.new={'daily':[day('2026-01-01',5),day('2026-01-02',10),day('2026-01-03',5,True)],
                  'trades':[trade('2026-01-01',5),trade('2026-01-02',10),trade('2026-01-03',5)]}

    def test_exact_overlap_and_reconciled_extension(self):
        series,audit=replay.replace_tail(self.item,self.old,self.new,'2026-01-01','2026-01-03','tracking')
        self.assertEqual(audit['overlap_days'],2)
        self.assertEqual(series['coverage'],[{'start':'2026-01-01','end':'2026-01-03'}])
        self.assertEqual(sum(row['pnl'] for row in series['daily']),20)
        self.assertEqual(sum(row['pnl'] for row in series['trades']),20)
        self.assertEqual({row['source_run'] for row in series['trades']},{'tracking'})
        self.assertFalse(series['daily'][1]['terminal'])

    def test_changed_overlap_fails_closed(self):
        changed=copy.deepcopy(self.new)
        changed['daily'][0]['pnl']=6
        with self.assertRaisesRegex(ValueError,'marked P&L diverged'):
            replay.replace_tail(self.item,self.old,changed,'2026-01-01','2026-01-03')
        changed=copy.deepcopy(self.new)
        changed['trades'][1]['pnl']=11
        with self.assertRaisesRegex(ValueError,'trades diverged'):
            replay.replace_tail(self.item,self.old,changed,'2026-01-01','2026-01-03')

    def test_no_new_marks_compares_existing_synthetic_close_exactly(self):
        old=copy.deepcopy(self.old)
        old['trades'][-1]=trade('2026-01-02',10,True)
        self.assertEqual(replay.verify_overlap(old,old,'2026-01-01','2026-01-02',
                                               terminal_continues=False)['overlap_trades'],2)

    def test_forced_terminal_exit_is_replaced_with_continuation(self):
        old=copy.deepcopy(self.old)
        old['daily'][1]['pnl']=15
        old['trades'][1]=trade('2026-01-02',15,True)
        new={'daily':[day('2026-01-01',5),day('2026-01-02',10),day('2026-01-03',10,True)],
             'trades':[trade('2026-01-01',5),
                       {'entry':'2026-01-02T12:00:00+00:00','exit':'2026-01-03T13:00:00+00:00',
                        'pnl':20,'quantity':1,'cost':1,'exit_reason':'signal','synthetic_exit':False}]}
        series,audit=replay.replace_tail(self.item,old,new,'2026-01-01','2026-01-03')
        self.assertEqual(audit['removed_synthetic_pnl'],15)
        self.assertEqual(audit['terminal_mark_delta'],-5)
        self.assertEqual(sum(row['pnl'] for row in series['daily']),25)
        self.assertEqual(sum(row['pnl'] for row in series['trades']),25)

    def test_overnight_weekend_and_incomplete_session_boundaries(self):
        friday=date(2026,9,25)
        opened=pd.Timestamp(replay.SESSION.open_datetime(friday))
        closed=pd.Timestamp(replay.SESSION.close_datetime(friday))-replay.ONE_MINUTE
        bars=pd.DataFrame({'session_date':['2026-09-25','2026-09-25']},index=pd.DatetimeIndex([opened,closed]))
        self.assertEqual(replay.complete_overnight_sessions(bars,'2026-09-25','2026-09-27'),
                         ['2026-09-25'])
        monday=date(2026,9,28)
        partial=pd.DataFrame({'session_date':['2026-09-28']},
                             index=pd.DatetimeIndex([pd.Timestamp(replay.SESSION.open_datetime(monday))]))
        with self.assertRaisesRegex(ValueError,'complete endpoints'):
            replay.complete_overnight_sessions(pd.concat([bars,partial]),'2026-09-25','2026-09-28')


class ReplayPublicationTest(unittest.TestCase):
    def fixture(self,state,legacy_nq_momentum=False):
        item_id=(replay.LEGACY_NQ_MOMENTUM_ID if legacy_nq_momentum else 'book')
        source_id=(replay.LEGACY_NQ_MOMENTUM_RUN if legacy_nq_momentum else 'base')
        symbol='NQ' if legacy_nq_momentum else 'ES'
        timeframe='1h' if legacy_nq_momentum else '1m'
        out=state/'collective';out.mkdir()
        sources=state/'sources';sources.mkdir()
        source=sources/'strategy.py';source.write_text('# frozen adapter\n',encoding='utf-8')
        strategy={'id':'multi-speed-momentum' if legacy_nq_momentum else 'fixture',
                  'name':'Fixture','file':'strategy.py','file_hash':builder.sha(source)}
        dataset_file=state/'bars.parquet';dataset_file.write_bytes(b'checksum-verified fixture')
        dataset={'id':'new-data','symbol':symbol,'path':str(dataset_file),'checksum':builder.sha(dataset_file),
                 'first':'2025-12-31T00:00:00+00:00','last':'2026-01-03T23:59:00+00:00'}
        base={'protocol':1,'id':source_id,'strategy':strategy,'dataset':dataset,'parameters':{},
              'start':'2026-01-01','end':'2026-01-02','timeframe':timeframe,'session':'full-trading-day',
              'capital':1000,'fee':1,'slippage':1,'warmup_days':1,'source_dir':str(sources),
              'source_hash':'frozen'}
        tracked={**base,'id':'tracking','end':'2026-01-03',
                 'portfolio_replay':{'item_id':item_id,'source_run_id':source_id}}
        series={'id':item_id,'provenance_version':2,'coverage':[{'start':'2026-01-01','end':'2026-01-02'}],
                'daily':[day('2026-01-01',5),day('2026-01-02',10,True)],
                'trades':[trade('2026-01-01',5),trade('2026-01-02',10)]}
        payload=json.dumps(series,separators=(',',':')).encode()
        checksum=hashlib.sha256(payload).hexdigest();name=f'{item_id}-{checksum[:16]}.json'
        (out/name).write_bytes(payload)
        item={'id':item_id,'key':'multi-speed-momentum__NQ__1h' if legacy_nq_momentum else 'fixture',
              'name':'Fixture','symbol':symbol,'timeframe':timeframe,
              'session':'full-trading-day','source':'Workbench' if legacy_nq_momentum else 'Current workbench','start':'2026-01-01',
              'end':'2026-01-02','coverage':series['coverage'],'capital':1000,'parameters':{},
              'source_run_ids':[source_id],'working':True,'feasible':False,'tested':False,
              'reasons':[],'series_file':name,'checksum':checksum,'net_pnl':15,'recent_pnl':15,
              'trades':2,'chart_points':[0,5,15]}
        builder.dump(out/'index.json',{'version':1,'items':[item],'errors':[],'sources':[]})
        run=state/'runs'/'tracking';run.mkdir(parents=True)
        builder.dump(run/'input.json',tracked)
        (run/'trades.csv').write_text('entry_time,exit_time,net_pnl,quantity,cost,exit_reason\n'
                                      '2026-01-01T12:00:00Z,2026-01-01T13:00:00Z,5,1,1,signal\n'
                                      '2026-01-02T12:00:00Z,2026-01-02T13:00:00Z,10,1,1,signal\n'
                                      '2026-01-03T12:00:00Z,2026-01-03T13:00:00Z,5,1,1,signal\n')
        (run/'equity.csv').write_text('timestamp,equity\n2026-01-01T13:00:00Z,1005\n'
                                      '2026-01-02T13:00:00Z,1015\n2026-01-03T13:00:00Z,1020\n')
        builder.dump(run/'manifest.json',{'run_id':'tracking','metrics':{'net_pnl':20},
                     'artifacts':[{'name':name,'checksum':builder.sha(run/name)}
                                  for name in ('trades.csv','equity.csv')]})
        with sqlite3.connect(state/'workbench.sqlite3') as db:
            db.execute('CREATE TABLE records (kind TEXT,id TEXT,body TEXT)')
            db.executemany('INSERT INTO records VALUES (?,?,?)',[
                ('dataset',dataset['id'],json.dumps(dataset)),
                ('run',source_id,json.dumps({'id':source_id,'status':'Succeeded','input':base})),
                ('run','tracking',json.dumps({'id':'tracking','status':'Succeeded','input':tracked})),
            ])
        db.close()
        return out,item,series

    def test_publish_run_retains_original_record_and_refresh_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);out,base,series=self.fixture(state)
            with patch.object(builder,'OUT',out),patch.dict(os.environ,{'WORKBENCH_HOME':str(state)}):
                result=replay.publish_run('book','tracking')
                self.assertEqual(result['end'],'2026-01-03')
                index=builder.read(out/'index.json');updated=index['items'][0]
                self.assertEqual(updated['id'],base['id'])
                self.assertEqual(updated['source_run_ids'],['base'])
                self.assertEqual(updated['verified_replay']['source_run_id'],'tracking')
                self.assertEqual(updated['verified_replay']['dataset_checksum'],
                                 builder.read(out/'verified-replays.json')['book']['item']['verified_replay']['dataset_checksum'])
                self.assertTrue((out/updated['series_file']).is_file())
                self.assertFalse(builder.baseline_run({'input':{'portfolio_replay':{'item_id':'book'}}}))
                self.assertEqual(replay.sqlite_record('run','base')['input']['end'],'2026-01-02')
                self.assertEqual(builder.apply_verified_overlays([base],[updated],[])[0],updated)

    def test_legacy_nq_momentum_publishes_only_after_verified_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);out,base,_=self.fixture(state,legacy_nq_momentum=True)
            item_id=replay.LEGACY_NQ_MOMENTUM_ID
            with patch.object(builder,'OUT',out),patch.dict(os.environ,{'WORKBENCH_HOME':str(state)}):
                result=replay.publish_run(item_id,'tracking')
                self.assertEqual(result['end'],'2026-01-03')
                updated=builder.read(out/'index.json')['items'][0]
                self.assertEqual(updated['id'],item_id)
                self.assertEqual(updated['source_run_ids'],[replay.LEGACY_NQ_MOMENTUM_RUN])
                self.assertEqual(updated['verified_replay']['source_run_id'],'tracking')
                self.assertEqual(replay.sqlite_record('run',replay.LEGACY_NQ_MOMENTUM_RUN)['input']['end'],
                                 base['end'])

        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);out,base,_=self.fixture(state,legacy_nq_momentum=True)
            run=state/'runs'/'tracking';trades=run/'trades.csv';equity=run/'equity.csv'
            trades.write_text(trades.read_text().replace(',10,1,1,signal',',11,1,1,signal'))
            equity.write_text(equity.read_text().replace('1015','1016').replace('1020','1021'))
            manifest=builder.read(run/'manifest.json');manifest['metrics']['net_pnl']=21
            for row in manifest['artifacts']:row['checksum']=builder.sha(run/row['name'])
            builder.dump(run/'manifest.json',manifest)
            with patch.object(builder,'OUT',out),patch.dict(os.environ,{'WORKBENCH_HOME':str(state)}):
                with self.assertRaises(ValueError):replay.publish_run(item_id,'tracking')
                self.assertEqual(builder.read(out/'index.json')['items'][0],base)
                self.assertFalse((out/'verified-replays.json').exists())

    def test_unextended_other_workbench_book_still_requires_manual_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);out,_,_=self.fixture(state)
            index=builder.read(out/'index.json');index['items'][0]['source']='Workbench'
            builder.dump(out/'index.json',index)
            with patch.object(builder,'OUT',out),patch.dict(os.environ,{'WORKBENCH_HOME':str(state)}):
                with self.assertRaisesRegex(ValueError,'manual update'):
                    replay.publish_run('book','tracking')
                self.assertFalse((out/'verified-replays.json').exists())

    def test_corrupted_overlap_leaves_old_index_and_no_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);out,base,_=self.fixture(state)
            run=state/'runs'/'tracking';trades=run/'trades.csv'
            trades.write_text(trades.read_text().replace(',10,1,1,signal',',11,1,1,signal'))
            equity=run/'equity.csv'
            equity.write_text(equity.read_text().replace('1015','1016').replace('1020','1021'))
            manifest=builder.read(run/'manifest.json')
            next(row for row in manifest['artifacts'] if row['name']=='trades.csv')['checksum']=builder.sha(trades)
            next(row for row in manifest['artifacts'] if row['name']=='equity.csv')['checksum']=builder.sha(equity)
            manifest['metrics']['net_pnl']=21
            builder.dump(run/'manifest.json',manifest)
            with patch.object(builder,'OUT',out),patch.dict(os.environ,{'WORKBENCH_HOME':str(state)}):
                with self.assertRaises(ValueError):replay.publish_run('book','tracking')
                self.assertEqual(builder.read(out/'index.json')['items'][0],base)
                self.assertFalse((out/'verified-replays.json').exists())

    def test_pinned_book_requires_manual_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);out,base,_=self.fixture(state)
            index=builder.read(out/'index.json');index['items'][0]['source']='Pinned workbench'
            builder.dump(out/'index.json',index)
            with patch.object(builder,'OUT',out),patch.dict(os.environ,{'WORKBENCH_HOME':str(state)}):
                with self.assertRaisesRegex(ValueError,'manual update'):
                    replay.publish_run('book','tracking')
                self.assertFalse((out/'verified-replays.json').exists())

    def test_refresh_preserves_last_verified_item_if_frozen_base_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);out,base,_=self.fixture(state)
            with patch.object(builder,'OUT',out),patch.dict(os.environ,{'WORKBENCH_HOME':str(state)}):
                replay.publish_run('book','tracking')
                saved=builder.read(out/'index.json')['items'][0]
                changed={**base,'checksum':'different-source-checksum'}
                errors=[]
                kept=builder.apply_verified_overlays([changed],[saved],errors)
                self.assertEqual(kept,[saved])
                self.assertIn('needs verification again',errors[0]['error'])

    def test_complete_weekend_without_new_marks_does_not_publish(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);out,base,_=self.fixture(state)
            run=state/'runs'/'tracking'
            tracked=builder.read(run/'input.json');tracked['end']='2026-01-04'
            builder.dump(run/'input.json',tracked)
            trades=run/'trades.csv';trades.write_text('\n'.join(trades.read_text().splitlines()[:3])+'\n')
            equity=run/'equity.csv';equity.write_text('\n'.join(equity.read_text().splitlines()[:3])+'\n')
            manifest=builder.read(run/'manifest.json');manifest['metrics']['net_pnl']=15
            for row in manifest['artifacts']:row['checksum']=builder.sha(run/row['name'])
            builder.dump(run/'manifest.json',manifest)
            with sqlite3.connect(state/'workbench.sqlite3') as db:
                dataset=json.loads(db.execute("SELECT body FROM records WHERE kind='dataset'").fetchone()[0])
                dataset['last']='2026-01-04T23:59:00+00:00'
                db.execute("UPDATE records SET body=? WHERE kind='dataset'",(json.dumps(dataset),))
                tracked['dataset']=dataset
                builder.dump(run/'input.json',tracked)
                db.execute("UPDATE records SET body=? WHERE kind='run' AND id='tracking'",
                           (json.dumps({'id':'tracking','status':'Succeeded','input':tracked}),))
            db.close()
            with patch.object(builder,'OUT',out),patch.dict(os.environ,{'WORKBENCH_HOME':str(state)}):
                result=replay.publish_run('book','tracking')
                self.assertTrue(result['no_new_session'])
                self.assertEqual(result['end'],base['end'])
                self.assertEqual(builder.read(out/'index.json')['items'][0],base)
                self.assertFalse((out/'verified-replays.json').exists())

    def test_full_evidence_refresh_reapplies_verified_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);out,_,_=self.fixture(state)
            (state/'strategy.py').write_bytes((state/'sources'/'strategy.py').read_bytes())
            baseline=state/'runs'/'base';baseline.mkdir()
            with sqlite3.connect(state/'workbench.sqlite3') as db:
                base=json.loads(db.execute("SELECT body FROM records WHERE kind='run' AND id='base'").fetchone()[0])['input']
            db.close()
            builder.dump(baseline/'input.json',base)
            tracked=state/'runs'/'tracking'
            for name in ('trades.csv','equity.csv'):
                (baseline/name).write_text('\n'.join((tracked/name).read_text().splitlines()[:3])+'\n')
            builder.dump(baseline/'manifest.json',{'metrics':{'net_pnl':15},
                'artifacts':[{'name':name,'checksum':builder.sha(baseline/name)}
                             for name in ('trades.csv','equity.csv')]})
            missing=state/'missing'
            with patch.multiple(builder,ROOT=state,OUT=out,FIRST=missing,EXPANDED=missing,SND=missing), \
                    patch.dict(os.environ,{'WORKBENCH_HOME':str(state)}),contextlib.redirect_stdout(io.StringIO()):
                builder.main()
                imported=builder.read(out/'index.json')['items'][0]
                self.assertEqual(imported['source_run_ids'],['base'])
                tracked_input=builder.read(tracked/'input.json')
                tracked_input['portfolio_replay']['item_id']=imported['id']
                builder.dump(tracked/'input.json',tracked_input)
                with sqlite3.connect(state/'workbench.sqlite3') as db:
                    db.execute("UPDATE records SET body=? WHERE kind='run' AND id='tracking'",
                               (json.dumps({'id':'tracking','status':'Succeeded','input':tracked_input}),))
                db.close()
                replay.publish_run(imported['id'],'tracking')
                published=builder.read(out/'index.json')['items'][0]
                self.assertEqual(published['end'],'2026-01-03')
                builder.main()
                refreshed=builder.read(out/'index.json')['items'][0]
                self.assertEqual(refreshed['checksum'],published['checksum'])
                self.assertEqual(refreshed['verified_replay'],published['verified_replay'])


if __name__=='__main__':unittest.main()
