"""User-requested smaller-target extension; preserve the prior failed campaign."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
from replay import simulate_day

OUT = ROOT / "reports/mnq-open-fade-small-targets-2026-10-28"
PRIOR = ROOT / "reports/mnq-open-fade-2026-10-28"
BASE = ROOT / "reports/mnq-ny-open-2026-10-28"
P = json.loads((HERE/"protocol.json").read_text())
SCENARIOS = {
    "baseline": ("conservative", 2.24, 0),
    "favorable_order": ("favorable", 2.24, 0),
    "double_cost": ("conservative", 4.48, 0),
    "entry_delay_1m": ("conservative", 2.24, 1),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe(value):
    if isinstance(value, dict):
        return {str(k):safe(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(x) for x in value]
    if isinstance(value, np.generic):
        return safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def stats(daily):
    trades = daily[daily.filled]
    net = trades.net_dollars
    all_net = daily.net_dollars
    positive, negative = net[net>0].sum(), -net[net<0].sum()
    pf = positive/negative if negative else math.inf if positive else 0.
    curve = np.r_[0., all_net.cumsum().to_numpy()]
    dd = float(np.max(np.maximum.accumulate(curve)-curve))
    streak = longest = 0
    for value in net:
        streak = streak+1 if value < 0 else 0
        longest = max(longest, streak)
    monthly = daily.assign(month=daily.date.str[:7]).groupby("month").net_dollars.sum()
    total = float(net.sum())
    return {"sessions":len(daily),"trades":len(trades),"net_profit":total,"gross_points":float(trades.gross_points.sum()),
        "costs_dollars":float(trades.cost_dollars.sum()),"win_pct":float((net>0).mean()*100) if len(net) else None,
        "profit_factor":float(pf),"no_losing_trades":bool(negative==0 and len(trades)),
        "expectancy_dollars":float(net.mean()) if len(net) else None,
        "median_net_dollars":float(net.median()) if len(net) else None,
        "average_win":float(net[net>0].mean()) if (net>0).any() else None,
        "average_loss":float(net[net<0].mean()) if (net<0).any() else None,
        "max_daily_closed_drawdown":dd,"net_to_drawdown":total/dd if dd else math.inf if total>0 else 0.,
        "largest_loss":float(net.min()) if len(net) else None,"longest_loss_streak":longest,
        "positive_month_pct":float((monthly>0).mean()*100),
        "direction_ambiguous_sessions":int(daily.direction_ambiguous.sum()),
        "entrybar_target_ambiguous_trades":int(trades.entrybar_target_ambiguous.sum()),
        "bracket_collision_trades":int(trades.bracket_collision.sum()),
        "first_minute_trades":int((trades.entry_idx==0).sum()),
        "long_trades":int((trades.side==1).sum()),"short_trades":int((trades.side==-1).sum()),
        "target_exits":int(trades.exit_reason.str.contains("target",na=False).sum()),
        "stop_exits":int(trades.exit_reason.str.contains("stop",na=False).sum()),
        "time_exits":int(trades.exit_reason.str.contains("time",na=False).sum())}


def criteria(row, minimum_trades, minimum_pf):
    failures = []
    if row["trades"] < minimum_trades:
        failures.append(f"trades {row['trades']} < {minimum_trades}")
    if row["net_profit"] <= 0:
        failures.append(f"net P&L {row['net_profit']:.2f} <= 0")
    if row["profit_factor"] < minimum_pf:
        failures.append(f"profit factor {row['profit_factor']:.3f} < {minimum_pf:.2f}")
    return failures


def load_sessions():
    meta = json.loads((BASE/"summary.json").read_text())["metadata"]
    source = Path(meta["data_path"])
    assert sha(source) == meta["sha256"]
    raw = pd.read_parquet(source).tz_convert("America/New_York")
    frame = raw.between_time("09:30", "11:44").copy()
    frame["date"] = frame.index.strftime("%Y-%m-%d")
    groups = dict(tuple(frame.groupby("date")))
    dates = pd.read_csv(BASE/"cash_calendar.csv").cash_session.tolist()
    excluded, sessions = [], {}
    for date in dates:
        expected = pd.date_range(pd.Timestamp(date+" 09:30",tz="America/New_York"),periods=135,freq="min")
        g = groups.get(date, frame.iloc[:0])
        missing = expected.difference(g.index)
        if len(missing) or g.instrument_id.nunique()!=1:
            excluded.append({"date":date,"missing_minutes":len(missing),"reason":"missing minutes" if len(missing) else "contract change"})
            continue
        assert g.index.equals(expected.rename(g.index.name))
        sessions[date] = g[["open","high","low","close"]].to_numpy(dtype=float)
    assert len(sessions)==meta["included_sessions"]
    pd.DataFrame(excluded).to_csv(OUT/"excluded_sessions.csv",index=False)
    return sessions,meta


class Campaign:
    def __init__(self,sessions):
        self.sessions=sessions
        self.cache={}
        self.results=[]
        self.decisions=[]
        self.details={}

    def run(self,mode,trigger,target,horizon,start,end,stage,scenario="baseline",stop=None):
        policy,cost,delay=SCENARIOS[scenario]
        stop=trigger/2 if stop is None else stop
        label=f"{stage}_{mode}_D{trigger}_T{target}_S{stop}_H{horizon}_{scenario}"
        ledger=[]
        for date,bars in self.sessions.items():
            if not start<=date<=end:
                continue
            key=(date,mode,trigger,target,stop,horizon,policy,cost,delay)
            if key not in self.cache:
                self.cache[key]=simulate_day(bars,mode=mode,trigger=trigger,horizon=horizon,policy=policy,delay_bars=delay,round_trip_cost_points=cost/2,target_points=target,stop_points=stop)
            result=dict(self.cache[key])
            branches=result.pop("branches",[])
            row=dict(result,date=date,case_id=label,mode=mode,trigger=trigger,target=target,stop=stop,horizon=horizon,scenario=scenario)
            row["cost_dollars"]=cost if row["filled"] else 0.
            row["net_dollars"]=row["gross_points"]*2-row["cost_dollars"]
            for field,index_field in [("entry_minute_et","entry_idx"),("exit_observation_time_et","exit_clock_idx")]:
                minute=row[index_field]
                row[field]=(f"{(570+int(minute))//60:02d}:{(570+int(minute))%60:02d}" if minute is not None else "")
            assert abs(row["net_dollars"]-row["net_points"]*2)<1e-8
            assert not row["filled"] or (0<=row["entry_idx"]<15 and row["exit_idx"]<=row["entry_idx"]+horizon)
            row["ambiguity_branches"]=json.dumps(safe(branches),separators=(",",":")) if branches else ""
            ledger.append(row)
        daily=pd.DataFrame(ledger)
        daily["equity_dollars"]=daily.net_dollars.cumsum()
        daily.to_csv(OUT/"ledgers"/(label+".csv"),index=False)
        summary=dict(case_id=label,stage=stage,mode=mode,trigger=trigger,target=target,stop=stop,horizon=horizon,scenario=scenario,policy=policy,
            cost_dollars=cost,delay_bars=delay,start=start,end=end,**stats(daily))
        summary["target_hit_pct"]=summary["target_exits"]/summary["trades"]*100 if summary["trades"] else None
        summary["two_exit_breakeven_win_pct"]=(stop+cost/2)/(stop+target)*100
        summary["gross_reward_risk"]=target/stop
        summary["original_control"]=bool(target==trigger/2 and stop==trigger/2)
        if stage=="development" and summary["original_control"]:
            original=pd.read_csv(PRIOR/"ledgers"/f"development_{mode}_D{trigger}_H{horizon}_{scenario}.csv")
            assert original.date.tolist()==daily.date.tolist()
            for col in ["filled","side","gross_points","net_dollars","entry_idx","exit_idx","exit_reason"]:
                a,b=original[col].reset_index(drop=True),daily[col].reset_index(drop=True)
                if col in ["gross_points","net_dollars","entry_idx","exit_idx"]:
                    assert np.allclose(a.to_numpy(float),b.to_numpy(float),equal_nan=True,rtol=0,atol=1e-8),(label,col)
                else:
                    assert a.fillna("").equals(b.fillna("")),(label,col)
            summary["prior_control_parity"]="passed"
        self.results.append(summary)
        self.details[label]=daily
        return summary

    def select(self,mode,end,stage):
        rows=[]
        for trigger in [40,60,80]:
            for horizon in [60,120]:
                for target in [5,10,15,trigger/2]:
                    row=self.run(mode,trigger,target,horizon,"2019-05-06",end,stage)
                    row["eligibility_failures"]=criteria(row,150,1.10)
                    row["eligible"]=not row["eligibility_failures"]
                    rows.append(row)
                    if stage=="development":
                        self.run(mode,trigger,target,horizon,"2019-05-06",end,stage,"favorable_order")
        eligible=[r for r in rows if r["eligible"]]
        chosen=max(eligible,key=lambda r:(r["net_to_drawdown"],r["net_profit"],-r["trigger"],-r["horizon"],r["target"])) if eligible else None
        self.decisions.append({"stage":stage,"mode":mode,"train_end":end,"selected_case":chosen["case_id"] if chosen else None,
            "outcome":"selected" if chosen else "failed","reason":"Frozen eligibility and net/drawdown ranking" if chosen else "No candidate met minimum 150 trades, positive net profit and PF >= 1.10"})
        return chosen

    def evaluate(self,mode):
        chosen=self.select(mode,"2023-12-31","development")
        if not chosen:
            return {"mode":mode,"outcome":"failed","stage":"development","reason":"No eligible development candidate","tested_through":"2023-12-31"}
        passed=[]
        for index,fold in enumerate(P["chronological_evaluation"]["folds"]):
            year=fold["test_start"][:4]
            if index:
                chosen=self.select(mode,fold["train_end"],"training_for_"+year)
                if not chosen:
                    return {"mode":mode,"outcome":"failed","stage":"training_for_"+year,"reason":"No eligible expanding-training candidate","passed_folds":passed,"tested_through":fold["train_end"]}
            rows=[]
            # All predeclared stress cases for this selected configuration form
            # one evaluation; none is used to reselect parameters in this fold.
            for scenario in SCENARIOS:
                row=self.run(mode,chosen["trigger"],chosen["target"],chosen["horizon"],fold["test_start"],fold["test_end"],"evaluation_"+year,scenario,stop=chosen["stop"])
                row["evaluation_failures"]=criteria(row,30,1.05) if scenario!="favorable_order" else []
                rows.append(row)
            failed=[{"scenario":r["scenario"],"failures":r["evaluation_failures"]} for r in rows if r["evaluation_failures"]]
            self.decisions.append({"stage":"evaluation_"+year,"mode":mode,"selected_training_case":chosen["case_id"],"trigger":chosen["trigger"],"target":chosen["target"],"stop":chosen["stop"],"horizon":chosen["horizon"],"outcome":"failed" if failed else "passed","failures":failed})
            if failed:
                return {"mode":mode,"outcome":"failed","stage":"evaluation_"+year,"reason":failed,"passed_folds":passed,"tested_through":fold["test_end"],"selected_trigger":chosen["trigger"],"selected_target":chosen["target"],"selected_stop":chosen["stop"],"selected_horizon":chosen["horizon"]}
            passed.append(year)
        failures=[]
        neighbors=[("target_80pct",chosen["trigger"],round(chosen["target"]*.8/.25)*.25),
                   ("target_120pct",chosen["trigger"],round(chosen["target"]*1.2/.25)*.25),
                   ("trigger_90pct",round(chosen["trigger"]*.9/.25)*.25,chosen["target"]),
                   ("trigger_110pct",round(chosen["trigger"]*1.1/.25)*.25,chosen["target"])]
        for name,trigger,target in neighbors:
            row=self.run(mode,trigger,target,chosen["horizon"],"2024-01-01","2026-09-03","nearby_"+name,"double_cost",stop=chosen["stop"])
            row["robustness_failures"]=criteria(row,100,1.05)
            if row["robustness_failures"]:
                failures.append({"trigger":trigger,"target":target,"failures":row["robustness_failures"]})
                break
        self.decisions.append({"stage":"nearby_parameters","mode":mode,"outcome":"failed" if failures else "passed","failures":failures})
        return {"mode":mode,"outcome":"failed" if failures else "historical_research_pass","stage":"nearby_parameters","reason":failures or "Frozen historical tests passed; tick execution and prospective evidence remain untested","passed_folds":passed,"tested_through":"2026-09-03","selected_trigger":chosen["trigger"],"selected_target":chosen["target"],"selected_stop":chosen["stop"],"selected_horizon":chosen["horizon"]}


def main():
    (OUT/"ledgers").mkdir(parents=True,exist_ok=True)
    sessions,meta=load_sessions()
    campaign=Campaign(sessions)
    dispositions=[]
    for mode in ["touch","confirm"]:
        dispositions.append(campaign.evaluate(mode))
        print(json.dumps(safe(dispositions[-1])),flush=True)
    table=pd.DataFrame(campaign.results)
    table.to_csv(OUT/"all_attempts.csv",index=False)
    # Summaries of exported development and selected evaluation ledgers only;
    # later unattempted windows stay unscored after a decisive failure.
    breakdowns=[]
    for result in campaign.results:
        if result["scenario"]!="baseline" or result["stage"].startswith("training"):
            continue
        daily=campaign.details[result["case_id"]]
        for year,g in daily.groupby(daily.date.str[:4]):
            breakdowns.append(dict(case_id=result["case_id"],mode=result["mode"],trigger=result["trigger"],target=result["target"],stop=result["stop"],horizon=result["horizon"],stage=result["stage"],year=int(year),**stats(g)))
    pd.DataFrame(breakdowns).to_csv(OUT/"yearly_breakdown.csv",index=False)
    selected=[]
    for mode in ["touch","confirm"]:
        candidates=[r for r in campaign.results if r["mode"]==mode and r["stage"]=="development" and r["scenario"]=="baseline"]
        # Best development row shown even if it failed eligibility. This does
        # not promote it, advance evaluation, or change the frozen selector.
        eligible=[r for r in candidates if r["eligible"]]
        best=max(eligible,key=lambda r:(r["net_to_drawdown"],r["net_profit"],-r["trigger"],-r["horizon"],r["target"])) if eligible else max(candidates,key=lambda r:r["net_profit"])
        selected.append(best)
        campaign.details[best["case_id"]].to_csv(OUT/(mode+"_development_best_daily.csv"),index=False)
        campaign.details[best["case_id"]].query("filled").to_csv(OUT/(mode+"_development_best_trades.csv"),index=False)
    summary={"study_id":P["study_id"],"protocol":P,"data":{"path":meta["data_path"],"sha256":meta["sha256"],"version":meta["data_version"],"available_sessions":len(sessions),"available_first":min(sessions),"available_last":max(sessions)},
        "dispositions":dispositions,"decisions":campaign.decisions,"attempts":campaign.results,"development_best_descriptive":selected,"yearly_breakdown":breakdowns,
        "source_checksums":{p.name:sha(p) for p in [HERE/"protocol.json",HERE/"replay.py",Path(__file__)]},
        "prior_campaign":P["prior_campaign"],"workbench_status":"Standalone audited replay; no official workbench run/evaluation or stage advancement"}
    (OUT/"summary.json").write_text(json.dumps(safe(summary),indent=2,allow_nan=False),encoding="utf-8")
    (OUT/"decisions.json").write_text(json.dumps(safe(campaign.decisions),indent=2),encoding="utf-8")
    for name in ["protocol.json","replay.py","test_replay.py","run_campaign.py"]:
        shutil.copyfile(HERE/name,OUT/name)
    print(table.query("stage=='development' and scenario=='baseline'")[["mode","trigger","target","stop","horizon","trades","win_pct","profit_factor","net_profit","expectancy_dollars","max_daily_closed_drawdown","eligible"]].round(3).to_string(index=False))
    print("Outputs:",OUT)


if __name__=="__main__":
    main()
